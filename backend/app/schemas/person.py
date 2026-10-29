from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import PersonRole, PersonStatus

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,63}$")


def _clean(v: str) -> str:
    return " ".join(v.split())


class PersonBase(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    email: EmailStr | None = None
    department: str | None = Field(default=None, max_length=120, description="Department/class/team name")
    role: PersonRole = PersonRole.student

    @field_validator("full_name")
    @classmethod
    def _n(cls, v: str) -> str:
        return _clean(v)

    @field_validator("department")
    @classmethod
    def _d(cls, v: str | None) -> str | None:
        return _clean(v) or None if v else None


class PersonCreate(PersonBase):
    person_code: str = Field(description="Unique person ID (student/employee number)")
    status: PersonStatus = PersonStatus.active

    @field_validator("person_code")
    @classmethod
    def _c(cls, v: str) -> str:
        v = v.strip()
        if not CODE_RE.match(v):
            raise ValueError("1-64 chars: letters, digits, '_', '.', '-', '/'")
        return v


class PersonUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    email: EmailStr | None = None
    department: str | None = Field(default=None, max_length=120)
    role: PersonRole | None = None
    status: PersonStatus | None = None
    clear_email: bool = False
    clear_department: bool = False


class PersonOut(BaseModel):
    """Deliberately has no embedding / image fields."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    person_code: str
    full_name: str
    email: str | None
    department: str | None
    role: PersonRole
    status: PersonStatus
    registered_at: datetime
    consent_at: datetime | None
    anonymized: bool
    enrolled_samples: int
    enrollment_status: str  # not_enrolled | partial | enrolled


class EnrollmentRejection(BaseModel):
    index: int
    reason: str
    code: str


class EnrollmentResult(BaseModel):
    person_id: int
    accepted: int
    rejected: list[EnrollmentRejection]
    total_samples: int
    enrollment_status: str
    possible_duplicates: list[dict]
    warnings: list[str]
