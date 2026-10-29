from __future__ import annotations

import enum
from datetime import date, datetime, time

from sqlalchemy import (
    JSON, Boolean, Date, Enum, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutil import utc_now
from app.database.base import Base, UTCDateTime
from app.models.person import Department, Person


class AttendanceStatus(str, enum.Enum):
    present = "present"
    late = "late"
    absent = "absent"
    corrected = "corrected"  # manually corrected; counts as attended


class Method(str, enum.Enum):
    face = "face"
    manual = "manual"


class AttendanceSession(Base):
    """A recurring attendance window (e.g. "Morning shift 09:00-17:00 Mon-Fri").

    Each calendar day on which it runs is one *occurrence*; attendance is unique
    per (person, session, occurrence date)."""

    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    late_cutoff: Mapped[time | None] = mapped_column(Time, nullable=True)
    days_of_week: Mapped[str] = mapped_column(String(20), default="0,1,2,3,4")  # Mon=0
    early_checkin_minutes: Mapped[int] = mapped_column(Integer, default=15)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    department: Mapped[Department | None] = relationship()

    @property
    def weekdays(self) -> list[int]:
        return [int(x) for x in self.days_of_week.split(",") if x != ""]


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("person_id", "session_id", "session_date", name="uq_attendance_person_session_date"),
        Index("ix_attendance_date", "session_date"),
        Index("ix_attendance_person_date", "person_id", "session_date"),
        Index("ix_attendance_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"))
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id", ondelete="RESTRICT"))
    session_date: Mapped[date] = mapped_column(Date)  # local date of the occurrence
    marked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)  # server time, UTC
    status: Mapped[AttendanceStatus] = mapped_column(
        Enum(AttendanceStatus, native_enum=False, length=16)
    )
    method: Mapped[Method] = mapped_column(Enum(Method, native_enum=False, length=16))
    # cosine similarity of the accepted match - NOT a probability
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    corrected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    corrected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    person: Mapped[Person] = relationship(back_populates="attendance")
    session: Mapped[AttendanceSession] = relationship()
