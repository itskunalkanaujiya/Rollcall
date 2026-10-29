"""Dashboard / report aggregation, CSV export and row serialisation. All numbers derive from
`attendance_service.build_rows`, i.e. stored records + computed absences."""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import local_date_time, utc_now
from app.models import AttendanceStatus, Department, Person, PersonStatus
from app.services import attendance_service as att
from app.services.attendance_service import Row


def serialize_row(r: Row, tz: str) -> dict:
    rec = r.record
    local_t = local_date_time(rec.marked_at, tz)[1].strftime("%H:%M:%S") if rec else None
    return {
        "id": rec.id if rec else None, "person_id": r.person.id, "person_code": r.person.person_code,
        "person_name": r.person.full_name, "department": r.person.department.name if r.person.department else None,
        "session_id": r.session.id, "session_name": r.session.name, "session_date": r.session_date,
        "marked_at": rec.marked_at if rec else None, "local_time": local_t, "status": r.status,
        "method": rec.method.value if rec else None, "similarity": rec.similarity if rec else None,
        "note": rec.note if rec else None, "is_computed": rec is None,
        "corrected": bool(rec and rec.corrected_at),
    }


def _pct(n: int, d: int) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def _roster_size(db: Session) -> int:
    return db.scalar(select(func.count(Person.id)).where(
        Person.status == PersonStatus.active, Person.anonymized.is_(False))) or 0


def dashboard_summary(db: Session, tz: str, now: datetime | None = None) -> dict:
    now = now or utc_now()
    today = local_date_time(now, tz)[0]
    rows = att.build_rows(db, today, today, tz, now)
    todays_sessions = att.sessions_for_date(db, today)
    cache: dict = {}
    expected_total = sum(len(att.expected_people(db, s, cache)) for s in todays_sessions)
    by_status = att.summarize(rows)
    stored = [r for r in rows if r.record]
    attended = by_status["attended"]
    absent = by_status["absent"]  # only occurrences that have ENDED
    pending = max(0, expected_total - attended - absent)
    # department breakdown (today)
    dept: dict[str, dict] = defaultdict(lambda: {"present": 0, "late": 0, "absent": 0})
    for r in rows:
        name = r.person.department.name if r.person.department else "Unassigned"
        key = "present" if r.status in (AttendanceStatus.present, AttendanceStatus.corrected) else r.status.value
        dept[name][key] += 1
    recent = sorted(stored, key=lambda r: r.record.marked_at, reverse=True)[:8]
    return {
        "date": today, "timezone": tz,
        "total_people": _roster_size(db), "sessions_today": len(todays_sessions),
        "expected": expected_total, "present": by_status["present"] + by_status["corrected"],
        "late": by_status["late"], "absent": absent, "pending": pending, "attended": attended,
        "attendance_percentage": _pct(attended, expected_total),
        "departments": [{"department": k, **v} for k, v in sorted(dept.items())],
        "recent": [serialize_row(r, tz) for r in recent],
    }


def trends(db: Session, tz: str, days: int, now: datetime | None = None) -> list[dict]:
    now = now or utc_now()
    end = local_date_time(now, tz)[0]
    start = end - timedelta(days=days - 1)
    rows = att.build_rows(db, start, end, tz, now)
    per_day: dict[date, dict] = {start + timedelta(days=i): {"present": 0, "late": 0, "absent": 0}
                                 for i in range(days)}
    for r in rows:
        key = "present" if r.status in (AttendanceStatus.present, AttendanceStatus.corrected) else r.status.value
        per_day[r.session_date][key] += 1
    out = []
    for d, v in per_day.items():
        total = v["present"] + v["late"] + v["absent"]
        out.append({"date": d, **v, "expected": total, "attendance_percentage": _pct(v["present"] + v["late"], total)})
    return out


def _bucket(d: date, group_by: str) -> str:
    if group_by == "week":
        return (d - timedelta(days=d.weekday())).isoformat()   # Monday of that week
    if group_by == "month":
        return d.strftime("%Y-%m")
    return d.isoformat()


def attendance_report(db: Session, tz: str, date_from: date, date_to: date, group_by: str,
                      session_id: int | None = None, department_id: int | None = None,
                      now: datetime | None = None) -> dict:
    rows = att.build_rows(db, date_from, date_to, tz, now, session_id=session_id, department_id=department_id)
    series: dict[str, dict] = defaultdict(lambda: {"present": 0, "late": 0, "absent": 0})
    people: dict[int, dict] = {}
    depts: dict[str, dict] = defaultdict(lambda: {"present": 0, "late": 0, "absent": 0})
    for r in rows:
        k = "present" if r.status in (AttendanceStatus.present, AttendanceStatus.corrected) else r.status.value
        series[_bucket(r.session_date, group_by)][k] += 1
        p = people.setdefault(r.person.id, {"person_id": r.person.id, "person_code": r.person.person_code,
                                            "full_name": r.person.full_name, "present": 0, "late": 0, "absent": 0})
        p[k] += 1
        depts[r.person.department.name if r.person.department else "Unassigned"][k] += 1

    def fin(v: dict) -> dict:
        total = v["present"] + v["late"] + v["absent"]
        return {**v, "expected": total, "attendance_percentage": _pct(v["present"] + v["late"], total)}

    return {
        "from": date_from, "to": date_to, "group_by": group_by,
        "series": [{"period": k, **fin(v)} for k, v in sorted(series.items())],
        "people": sorted((fin(v) for v in people.values()), key=lambda x: (x["attendance_percentage"] or 0)),
        "departments": [{"department": k, **fin(v)} for k, v in sorted(depts.items())],
        "totals": fin({k: sum(v[k] for v in series.values()) for k in ("present", "late", "absent")}),
    }


_FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(v: object) -> object:
    """Neutralise spreadsheet formula injection (names are user-controlled)."""
    if isinstance(v, str) and v.startswith(_FORMULA_CHARS):
        return "'" + v
    return v


def rows_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Time", "Person ID", "Name", "Department", "Session", "Status", "Method",
                "Similarity (cosine, not a probability)", "Note"])
    for r in rows:
        w.writerow([_csv_safe(x) for x in (
            r["session_date"].isoformat(), r["local_time"] or "", r["person_code"], r["person_name"],
            r["department"] or "", r["session_name"], r["status"].value, r["method"] or "computed",
            "" if r["similarity"] is None else r["similarity"], r["note"] or "")])
    return buf.getvalue()


def department_id_by_name(db: Session, name: str | None) -> int | None:
    if not name:
        return None
    return db.scalar(select(Department.id).where(func.lower(Department.name) == name.strip().lower()))
