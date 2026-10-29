from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, Enum, Float, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.timeutil import utc_now
from app.database.base import Base, UTCDateTime


class PersonRole(str, enum.Enum):
    student = "student"
    employee = "employee"
    other = "other"


class PersonStatus(str, enum.Enum):
    active = "active"
    disabled = "disabled"


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    people: Mapped[list["Person"]] = relationship(back_populates="department")


class Person(Base):
    __tablename__ = "people"
    __table_args__ = (Index("ix_people_status_dept", "status", "department_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # the "unique ID"
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    role: Mapped[PersonRole] = mapped_column(
        Enum(PersonRole, native_enum=False, length=16), default=PersonRole.student
    )
    status: Mapped[PersonStatus] = mapped_column(
        Enum(PersonStatus, native_enum=False, length=16), default=PersonStatus.active
    )
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    consent_recorded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    anonymized: Mapped[bool] = mapped_column(Boolean, default=False)

    department: Mapped[Department | None] = relationship(back_populates="people")
    embeddings: Mapped[list["FaceEmbedding"]] = relationship(
        back_populates="person", cascade="all, delete-orphan", passive_deletes=True
    )
    attendance: Mapped[list["AttendanceRecord"]] = relationship(  # noqa: F821
        back_populates="person", cascade="all, delete-orphan", passive_deletes=True
    )


class FaceEmbedding(Base):
    """One enrolled face template. The vector is Fernet-encrypted at rest and is
    never serialised into API responses."""

    __tablename__ = "face_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(
        ForeignKey("people.id", ondelete="CASCADE"), index=True
    )
    vector_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    dim: Mapped[int] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String(64))
    det_score: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16), default="webcam")  # webcam | upload
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    person: Mapped[Person] = relationship(back_populates="embeddings")
