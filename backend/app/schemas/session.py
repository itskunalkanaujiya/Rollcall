from __future__ import annotations

from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SessionBase(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    start_time: time
    end_time: time
    late_cutoff: time | None = None
    days_of_week: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], description="Mon=0 ... Sun=6")
    early_checkin_minutes: int = Field(default=15, ge=0, le=240)
    department: str | None = Field(default=None, description="Restrict to a department/class (optional)")
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("days_of_week")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if not v or any(d < 0 or d > 6 for d in v):
            raise ValueError("days_of_week must be a non-empty list of 0-6")
        return sorted(set(v))

    @model_validator(mode="after")
    def _times(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time (sessions cannot cross midnight)")
        if self.late_cutoff is not None and not (self.start_time <= self.late_cutoff <= self.end_time):
            raise ValueError("late_cutoff must be between start_time and end_time")
        return self


class SessionCreate(SessionBase):
    pass


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    start_time: time
    end_time: time
    late_cutoff: time | None
    days_of_week: list[int]
    early_checkin_minutes: int
    department: str | None
    is_active: bool
    created_at: datetime
