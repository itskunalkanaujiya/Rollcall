"""Sessions, dashboard, reports, runtime settings, audit log and data-retention maintenance."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.deps import client_ip, current_user, require_admin, require_operator
from app.core.errors import AppError
from app.core.timeutil import local_date_time, utc_now
from app.database.base import get_db
from app.models import AttendanceRecord, AttendanceSession, AuditLog, Department, User
from app.schemas.common import make_page
from app.schemas.session import SessionCreate, SessionOut
from app.services import audit_service, reporting, settings_service

router = APIRouter(tags=["admin"])


# ---- sessions ----------------------------------------------------------------
def _session_out(s: AttendanceSession) -> dict:
    return {"id": s.id, "name": s.name, "start_time": s.start_time, "end_time": s.end_time,
            "late_cutoff": s.late_cutoff, "days_of_week": s.weekdays, "early_checkin_minutes": s.early_checkin_minutes,
            "department": s.department.name if s.department else None, "is_active": s.is_active,
            "created_at": s.created_at}


def _apply(db: Session, s: AttendanceSession, body: SessionCreate) -> None:
    s.name, s.start_time, s.end_time, s.late_cutoff = body.name, body.start_time, body.end_time, body.late_cutoff
    s.days_of_week = ",".join(str(d) for d in body.days_of_week)
    s.early_checkin_minutes, s.is_active = body.early_checkin_minutes, body.is_active
    s.department_id = None
    if body.department:
        dep = db.scalar(select(Department).where(func.lower(Department.name) == body.department.lower()))
        if dep is None:
            dep = Department(name=body.department)
            db.add(dep)
            db.flush()
        s.department_id = dep.id


def _load(db: Session, sid: int) -> AttendanceSession:
    s = db.scalar(select(AttendanceSession).options(joinedload(AttendanceSession.department))
                  .where(AttendanceSession.id == sid))
    if s is None:
        raise AppError(404, "not_found", "Session not found")
    return s


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(_: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(AttendanceSession).options(joinedload(AttendanceSession.department))
                      .order_by(AttendanceSession.start_time, AttendanceSession.name)).unique()
    return [_session_out(s) for s in rows]


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionCreate, request: Request, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    s = AttendanceSession()
    _apply(db, s, body)
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "duplicate_session", "A session with this name already exists") from None
    audit_service.log(db, "session_create", admin, "session", s.id, {"name": s.name}, client_ip(request))
    return _session_out(_load(db, s.id))


@router.put("/sessions/{session_id}", response_model=SessionOut)
def update_session(session_id: int, body: SessionCreate, request: Request, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    s = _load(db, session_id)
    _apply(db, s, body)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "duplicate_session", "A session with this name already exists") from None
    audit_service.log(db, "session_update", admin, "session", s.id, {"name": s.name}, client_ip(request))
    return _session_out(_load(db, s.id))


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, request: Request, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    s = _load(db, session_id)
    if db.scalar(select(func.count(AttendanceRecord.id)).where(AttendanceRecord.session_id == s.id)):
        raise AppError(409, "session_in_use",
                       "This session has attendance records. Deactivate it instead of deleting it.")
    db.delete(s)
    db.commit()
    audit_service.log(db, "session_delete", admin, "session", session_id, {"name": s.name}, client_ip(request))


# ---- dashboard / reports -----------------------------------------------------
@router.get("/dashboard/summary")
def dashboard_summary(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return reporting.dashboard_summary(db, settings_service.get_value(db, "timezone"))


@router.get("/dashboard/trends")
def dashboard_trends(days: int = Query(14, ge=2, le=90), _: User = Depends(current_user), db: Session = Depends(get_db)):
    return reporting.trends(db, settings_service.get_value(db, "timezone"), days)


@router.get("/reports/attendance")
def attendance_report(date_from: date | None = None, date_to: date | None = None,
                      group_by: str = Query("day", pattern="^(day|week|month)$"),
                      session_id: int | None = None, department: str | None = None,
                      _: User = Depends(current_user), db: Session = Depends(get_db)):
    tz = settings_service.get_value(db, "timezone")
    today = local_date_time(utc_now(), tz)[0]
    date_to = date_to or today
    date_from = date_from or date_to - timedelta(days={"day": 13, "week": 83, "month": 364}[group_by])
    if date_from > date_to:
        raise AppError(422, "bad_range", "date_from must not be after date_to")
    if (date_to - date_from).days > 400:
        raise AppError(422, "range_too_large", "Date range is limited to 400 days")
    dept_id = reporting.department_id_by_name(db, department)
    if department and dept_id is None:
        raise AppError(404, "not_found", "Department not found")
    return reporting.attendance_report(db, tz, date_from, date_to, group_by, session_id, dept_id)


# ---- settings ------------------------------------------------------------------
@router.get("/settings")
def get_settings_(_: User = Depends(require_operator), db: Session = Depends(get_db)):
    return {"values": settings_service.get_all(db),
            "descriptions": {k: s.description for k, s in settings_service.SPECS.items()},
            "sensitive": [k for k, s in settings_service.SPECS.items() if s.sensitive]}


@router.put("/settings")
def put_settings(request: Request, patch: dict[str, Any] = Body(...), admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    try:
        values = settings_service.update(db, patch, admin.id)
    except settings_service.SettingsValidationError as exc:
        raise AppError(422, "invalid_settings", "Some settings are invalid", exc.args[0]) from exc
    audit_service.log(db, "settings_update", admin, "settings", None, {"keys": sorted(patch)}, client_ip(request))
    return {"values": values}


# ---- audit log / retention -----------------------------------------------------
@router.get("/audit-logs")
def audit_logs(page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200), action: str | None = None,
               _: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [{"id": r.id, "created_at": r.created_at, "username": r.username, "action": r.action,
              "entity_type": r.entity_type, "entity_id": r.entity_id, "details": r.details, "ip": r.ip_address}
             for r in rows]
    return make_page(items, total, page, page_size)


@router.post("/maintenance/retention")
def apply_retention(request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Apply the configured retention windows now (audit logs and, if set, attendance history)."""
    cfg = settings_service.get_all(db)
    removed_audit = audit_service.purge_older_than(db, cfg["retention_audit_days"])
    removed_att = 0
    if cfg["retention_attendance_days"] > 0:
        cutoff = local_date_time(utc_now(), cfg["timezone"])[0] - timedelta(days=cfg["retention_attendance_days"])
        removed_att = db.query(AttendanceRecord).filter(AttendanceRecord.session_date < cutoff).delete()
        db.commit()
    audit_service.log(db, "retention_run", admin, "system", None,
                      {"audit_removed": removed_audit, "attendance_removed": removed_att}, client_ip(request))
    return {"audit_removed": removed_audit, "attendance_removed": removed_att}
