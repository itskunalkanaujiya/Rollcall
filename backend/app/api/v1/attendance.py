from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.deps import client_ip, current_user, require_admin, require_operator
from app.core.errors import AppError
from app.core.timeutil import local_date_time, utc_now
from app.database.base import get_db
from app.models import AttendanceRecord, AttendanceStatus, Person, User
from app.schemas.attendance import AttendanceOut, AttendanceUpdate, ManualAttendanceCreate
from app.schemas.common import make_page
from app.services import attendance_service as att
from app.services import audit_service, reporting, settings_service

router = APIRouter(tags=["attendance"])
MAX_RANGE_DAYS = 93

SORTS = {
    "date": lambda r: (r.session_date, r.record.marked_at if r.record else datetime.min.replace(tzinfo=None)),
    "name": lambda r: r.person.full_name.lower(),
    "status": lambda r: r.status.value,
    "session": lambda r: r.session.name.lower(),
}


def _filter_rows(db: Session, tz: str, date_from: date | None, date_to: date | None, session_id: int | None,
                 department: str | None, status: AttendanceStatus | None, q: str | None, person_id: int | None = None
                 ) -> list[att.Row]:
    today = local_date_time(utc_now(), tz)[0]
    date_to = date_to or today
    date_from = date_from or (date_to - timedelta(days=29))
    if date_from > date_to:
        raise AppError(422, "bad_range", "date_from must not be after date_to")
    if (date_to - date_from).days > MAX_RANGE_DAYS:
        raise AppError(422, "range_too_large", f"Date range is limited to {MAX_RANGE_DAYS} days")
    dept_id = None
    if department:
        dept_id = reporting.department_id_by_name(db, department)
        if dept_id is None:
            return []
    # computed absences are only built when they can appear in the result
    if status in (None, AttendanceStatus.absent):
        rows = att.build_rows(db, date_from, date_to, tz, None, session_id, dept_id, person_id)
    else:
        rows = _stored_rows(db, date_from, date_to, session_id, dept_id, person_id)
    if status:
        rows = [r for r in rows if r.status == status]
    if q:
        needle = q.strip().lower()
        rows = [r for r in rows if needle in r.person.full_name.lower() or needle in r.person.person_code.lower()]
    return rows


def _stored_rows(db: Session, d1: date, d2: date, session_id: int | None, dept_id: int | None,
                 person_id: int | None) -> list[att.Row]:
    stmt = (select(AttendanceRecord)
            .options(joinedload(AttendanceRecord.person).joinedload(Person.department),
                     joinedload(AttendanceRecord.session))
            .where(AttendanceRecord.session_date >= d1, AttendanceRecord.session_date <= d2))
    if session_id:
        stmt = stmt.where(AttendanceRecord.session_id == session_id)
    if person_id:
        stmt = stmt.where(AttendanceRecord.person_id == person_id)
    recs = list(db.scalars(stmt).unique())
    if dept_id:
        recs = [r for r in recs if r.person.department_id == dept_id]
    return [att.Row(r.person, r.session, r.session_date, r.status, r) for r in recs]


def _sorted(rows: list[att.Row], sort: str, desc: bool) -> list[att.Row]:
    key = SORTS[sort]
    if sort == "date":
        return sorted(rows, key=lambda r: (r.session_date, r.record.marked_at.timestamp() if r.record else 0,
                                           r.person.full_name.lower()), reverse=desc)
    return sorted(rows, key=key, reverse=desc)


@router.get("/attendance")
def list_attendance(
    q: str | None = None, date_from: date | None = None, date_to: date | None = None,
    session_id: int | None = None, department: str | None = None, status: AttendanceStatus | None = None,
    sort: str = Query("date", pattern="^(date|name|status|session)$"), order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=200),
    _: User = Depends(current_user), db: Session = Depends(get_db),
):
    tz = settings_service.get_value(db, "timezone")
    rows = _sorted(_filter_rows(db, tz, date_from, date_to, session_id, department, status, q), sort, order == "desc")
    total = len(rows)
    chunk = rows[(page - 1) * page_size: page * page_size]
    return make_page([AttendanceOut(**reporting.serialize_row(r, tz)).model_dump(mode="json") for r in chunk],
                     total, page, page_size)


@router.get("/attendance/today")
def attendance_today(_: User = Depends(current_user), db: Session = Depends(get_db)):
    tz = settings_service.get_value(db, "timezone")
    today = local_date_time(utc_now(), tz)[0]
    rows = _sorted(_stored_rows(db, today, today, None, None, None), "date", True)
    return [AttendanceOut(**reporting.serialize_row(r, tz)).model_dump(mode="json") for r in rows]


@router.get("/attendance/person/{person_id}")
def attendance_for_person(person_id: int, date_from: date | None = None, date_to: date | None = None,
                          _: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.get(Person, person_id) is None:
        raise AppError(404, "not_found", "Person not found")
    tz = settings_service.get_value(db, "timezone")
    rows = _sorted(_filter_rows(db, tz, date_from, date_to, None, None, None, None, person_id), "date", True)
    summary = att.summarize(rows)
    return {"person_id": person_id, "summary": summary,
            "attendance_percentage": reporting._pct(summary["attended"], summary["expected"]),
            "items": [AttendanceOut(**reporting.serialize_row(r, tz)).model_dump(mode="json") for r in rows]}


@router.post("/attendance/manual", response_model=AttendanceOut, status_code=201)
def manual_attendance(body: ManualAttendanceCreate, request: Request, admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    tz = settings_service.get_value(db, "timezone")
    try:
        rec = att.create_manual(db, admin, body.person_id, body.session_id, body.session_date, body.status, body.note, tz)
    except att.AttendanceError as exc:
        raise AppError(exc.status, exc.code, exc.message) from exc
    audit_service.log(db, "attendance_manual", admin, "attendance", rec.id,
                      {"person_id": body.person_id, "session_id": body.session_id,
                       "date": body.session_date.isoformat(), "status": body.status.value}, client_ip(request))
    return _one(db, rec.id, tz)


def _one(db: Session, record_id: int, tz: str) -> dict:
    rec = db.scalar(select(AttendanceRecord).options(
        joinedload(AttendanceRecord.person).joinedload(Person.department), joinedload(AttendanceRecord.session))
        .where(AttendanceRecord.id == record_id))
    if rec is None:
        raise AppError(404, "not_found", "Attendance record not found")
    return reporting.serialize_row(att.Row(rec.person, rec.session, rec.session_date, rec.status, rec), tz)


@router.get("/attendance/{record_id}", response_model=AttendanceOut)
def get_attendance(record_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return _one(db, record_id, settings_service.get_value(db, "timezone"))


@router.put("/attendance/{record_id}", response_model=AttendanceOut)
def correct_attendance(record_id: int, body: AttendanceUpdate, request: Request, admin: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    rec = db.get(AttendanceRecord, record_id)
    if rec is None:
        raise AppError(404, "not_found", "Attendance record not found")
    before = rec.status.value
    try:
        att.correct_record(db, admin, rec, body.status, body.note)
    except att.AttendanceError as exc:
        raise AppError(exc.status, exc.code, exc.message) from exc
    audit_service.log(db, "attendance_correct", admin, "attendance", rec.id,
                      {"from": before, "to": body.status.value}, client_ip(request))
    return _one(db, rec.id, settings_service.get_value(db, "timezone"))


# ---- export ----------------------------------------------------------------
@router.get("/reports/export")
def export_csv(
    request: Request, q: str | None = None, date_from: date | None = None, date_to: date | None = None,
    session_id: int | None = None, department: str | None = None, status: AttendanceStatus | None = None,
    user: User = Depends(require_operator), db: Session = Depends(get_db),
):
    """CSV of exactly the rows the Attendance page shows for the same filters. Admin/operator only."""
    tz = settings_service.get_value(db, "timezone")
    rows = _sorted(_filter_rows(db, tz, date_from, date_to, session_id, department, status, q), "date", True)
    body = reporting.rows_to_csv([reporting.serialize_row(r, tz) for r in rows])
    audit_service.log(db, "attendance_export", user, "attendance", None, {"rows": len(rows)}, client_ip(request))
    return Response(body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="attendance.csv"'})
