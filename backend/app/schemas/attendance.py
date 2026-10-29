from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models import AttendanceStatus


class AttendanceOut(BaseModel):
    id: int | None  # None for computed (virtual) absent rows
    person_id: int
    person_code: str
    person_name: str
    department: str | None
    session_id: int
    session_name: str
    session_date: date
    marked_at: datetime | None
    local_time: str | None
    status: AttendanceStatus
    method: str | None
    similarity: float | None
    note: str | None
    is_computed: bool = False
    corrected: bool = False


class ManualAttendanceCreate(BaseModel):
    person_id: int
    session_id: int
    session_date: date
    status: AttendanceStatus = AttendanceStatus.present
    note: str = Field(min_length=3, max_length=500, description="Reason is mandatory for manual entries")


class AttendanceUpdate(BaseModel):
    status: AttendanceStatus
    note: str = Field(min_length=3, max_length=500)
