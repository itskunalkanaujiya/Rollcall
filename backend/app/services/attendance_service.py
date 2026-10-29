"""Attendance business rules. All writes go through here.

Guarantees
- At most one record per (person, session, occurrence date) - enforced by a DB unique
  constraint; the insert runs inside a SAVEPOINT so a concurrent duplicate is detected from
  the IntegrityError and returned as "already marked" instead of failing or double-writing.
- The timestamp is always the server's clock (UTC); the occurrence date/late rule use the
  configurable attendance timezone.
- Absent is computed (never stored) and only once the occurrence has ended.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Iterator

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.timeutil import local_date_time, local_to_utc, to_local, utc_now
from app.models import (
    AttendanceRecord, AttendanceSession, AttendanceStatus, Method, Person, PersonStatus, User,
)

ATTENDED = (AttendanceStatus.present, AttendanceStatus.late, AttendanceStatus.corrected)


# ---------------------------------------------------------------------------
# session resolution
# ---------------------------------------------------------------------------
def occurrence_window(s: AttendanceSession, d: date, tz: str) -> tuple[datetime, datetime]:
    """UTC instants for [start - early check-in, end] of the occurrence on local date d."""
    start = local_to_utc(d, s.start_time, tz)
    end = local_to_utc(d, s.end_time, tz)
    return start - timedelta(minutes=s.early_checkin_minutes), end


def occurrence_ended(s: AttendanceSession, d: date, tz: str, now: datetime) -> bool:
    return now > local_to_utc(d, s.end_time, tz)


def sessions_for_date(db: Session, d: date, only_active: bool = True) -> list[AttendanceSession]:
    q = select(AttendanceSession).options(joinedload(AttendanceSession.department))
    if only_active:
        q = q.where(AttendanceSession.is_active.is_(True))
    return [s for s in db.scalars(q).unique() if d.weekday() in s.weekdays]


def resolve_open_session(db: Session, person: Person, tz: str, now: datetime | None = None
                         ) -> tuple[AttendanceSession, date] | None:
    """The session occurrence a scan at `now` belongs to, or None when nothing is open.

    A session applies to a person when it is unrestricted or restricted to their department.
    If several are open the one that started most recently wins (deterministic)."""
    now = now or utc_now()
    local_d, _ = local_date_time(now, tz)
    open_ones: list[tuple[datetime, AttendanceSession]] = []
    for s in sessions_for_date(db, local_d):
        if s.department_id is not None and s.department_id != person.department_id:
            continue
        opens, closes = occurrence_window(s, local_d, tz)
        if opens <= now <= closes:
            open_ones.append((local_to_utc(local_d, s.start_time, tz), s))
    if not open_ones:
        return None
    open_ones.sort(key=lambda t: t[0], reverse=True)
    return open_ones[0][1], local_d


def status_for_time(s: AttendanceSession, local_time: time) -> AttendanceStatus:
    """Late = strictly after the late cut-off. Without a cut-off nobody is late."""
    if s.late_cutoff is not None and local_time > s.late_cutoff:
        return AttendanceStatus.late
    return AttendanceStatus.present


# ---------------------------------------------------------------------------
# marking
# ---------------------------------------------------------------------------
@dataclass
class MarkOutcome:
    created: bool
    record: AttendanceRecord


def mark_face_attendance(db: Session, person: Person, session: AttendanceSession, session_date: date,
                         tz: str, similarity: float, meta: dict | None = None,
                         now: datetime | None = None) -> MarkOutcome:
    """Create the attendance record for a face match, or return the existing one.

    Safe to call repeatedly and concurrently."""
    now = now or utc_now()
    _, local_t = local_date_time(now, tz)
    existing = find_record(db, person.id, session.id, session_date)
    if existing is not None:
        return MarkOutcome(False, existing)
    record = AttendanceRecord(
        person_id=person.id, session_id=session.id, session_date=session_date, marked_at=now,
        status=status_for_time(session, local_t), method=Method.face,
        similarity=round(float(similarity), 4), decision_meta=meta, created_at=now,
    )
    try:
        with db.begin_nested():       # SAVEPOINT: a lost race rolls back only this insert
            db.add(record)
            db.flush()
    except IntegrityError:
        existing = find_record(db, person.id, session.id, session_date)
        if existing is None:           # constraint failed for some other reason - do not hide it
            raise
        return MarkOutcome(False, existing)
    db.commit()
    return MarkOutcome(True, record)


def find_record(db: Session, person_id: int, session_id: int, session_date: date) -> AttendanceRecord | None:
    return db.scalar(select(AttendanceRecord).where(
        AttendanceRecord.person_id == person_id, AttendanceRecord.session_id == session_id,
        AttendanceRecord.session_date == session_date))


class AttendanceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def create_manual(db: Session, user: User, person_id: int, session_id: int, session_date: date,
                  status: AttendanceStatus, note: str, tz: str, now: datetime | None = None) -> AttendanceRecord:
    now = now or utc_now()
    person = db.get(Person, person_id)
    session = db.get(AttendanceSession, session_id)
    if person is None:
        raise AttendanceError("person_not_found", "Person not found", 404)
    if session is None:
        raise AttendanceError("session_not_found", "Session not found", 404)
    if status == AttendanceStatus.absent:
        raise AttendanceError("invalid_status", "Absent is computed automatically; to override a record use PUT")
    if session_date.weekday() not in session.weekdays:
        raise AttendanceError("not_a_session_day", "The session does not run on that weekday")
    if local_to_utc(session_date, session.start_time, tz) > now:
        raise AttendanceError("future_session", "Cannot record attendance for a session that has not started")
    record = AttendanceRecord(
        person_id=person.id, session_id=session.id, session_date=session_date, marked_at=now,
        status=status, method=Method.manual, note=note, created_by=user.id, created_at=now,
    )
    try:
        with db.begin_nested():
            db.add(record)
            db.flush()
    except IntegrityError:
        raise AttendanceError("duplicate", "An attendance record already exists for this person, session and date; "
                                           "edit it instead", 409) from None
    db.commit()
    return record


def correct_record(db: Session, user: User, record: AttendanceRecord, status: AttendanceStatus, note: str,
                   now: datetime | None = None) -> AttendanceRecord:
    if status == AttendanceStatus.absent:
        raise AttendanceError("invalid_status", "Delete the record instead of setting it to absent")
    record.original_status = record.original_status or record.status.value
    record.status = AttendanceStatus.corrected if status == AttendanceStatus.corrected else status
    record.note = note
    record.corrected_by = user.id
    record.corrected_at = now or utc_now()
    db.commit()
    return record


# ---------------------------------------------------------------------------
# computed absences / occurrence matrix
# ---------------------------------------------------------------------------
def _daterange(a: date, b: date) -> Iterator[date]:
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


@dataclass
class Row:
    """One person-in-one-occurrence: a stored record, or a computed absence (record=None)."""
    person: Person
    session: AttendanceSession
    session_date: date
    status: AttendanceStatus
    record: AttendanceRecord | None


def expected_people(db: Session, s: AttendanceSession, cache: dict[int | None, list[Person]]) -> list[Person]:
    key = s.department_id
    if key not in cache:
        q = select(Person).options(joinedload(Person.department)).where(
            Person.status == PersonStatus.active, Person.anonymized.is_(False))
        if key is not None:
            q = q.where(Person.department_id == key)
        cache[key] = list(db.scalars(q).unique())
    return cache[key]


def build_rows(db: Session, date_from: date, date_to: date, tz: str, now: datetime | None = None,
               session_id: int | None = None, department_id: int | None = None,
               person_id: int | None = None) -> list[Row]:
    """Stored records plus computed absences for occurrences that have already ended.

    Expected attendees are the people who are ACTIVE NOW and belong to the session's department;
    historical roster changes are not tracked (documented limitation)."""
    now = now or utc_now()
    q = (select(AttendanceRecord)
         .options(joinedload(AttendanceRecord.person).joinedload(Person.department),
                  joinedload(AttendanceRecord.session))
         .where(AttendanceRecord.session_date >= date_from, AttendanceRecord.session_date <= date_to))
    if session_id:
        q = q.where(AttendanceRecord.session_id == session_id)
    if person_id:
        q = q.where(AttendanceRecord.person_id == person_id)
    stored = list(db.scalars(q).unique())
    if department_id:
        stored = [r for r in stored if r.person.department_id == department_id]
    rows = [Row(r.person, r.session, r.session_date, r.status, r) for r in stored]
    have = {(r.person_id, r.session_id, r.session_date) for r in stored}

    sq = select(AttendanceSession).options(joinedload(AttendanceSession.department))
    if session_id:
        sq = sq.where(AttendanceSession.id == session_id)
    sessions = list(db.scalars(sq.where(AttendanceSession.is_active.is_(True))).unique())
    cache: dict[int | None, list[Person]] = {}
    for s in sessions:
        for d in _daterange(date_from, date_to):
            if d.weekday() not in s.weekdays or not occurrence_ended(s, d, tz, now):
                continue
            if d < to_local(s.created_at, tz).date():
                continue  # never invent absences for days before the session existed
            for p in expected_people(db, s, cache):
                if person_id and p.id != person_id:
                    continue
                if department_id and p.department_id != department_id:
                    continue
                if (p.id, s.id, d) in have:
                    continue
                if p.registered_at > local_to_utc(d, s.end_time, tz):
                    continue  # registered after the occurrence ended
                rows.append(Row(p, s, d, AttendanceStatus.absent, None))
    return rows


def summarize(rows: Iterable[Row]) -> dict[str, int]:
    out = {"expected": 0, "present": 0, "late": 0, "corrected": 0, "absent": 0}
    for r in rows:
        out["expected"] += 1
        out[r.status.value] += 1
    out["attended"] = out["present"] + out["late"] + out["corrected"]
    return out
