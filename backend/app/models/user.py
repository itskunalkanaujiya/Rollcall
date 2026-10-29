from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import utc_now
from app.database.base import Base, UTCDateTime


class Role(str, enum.Enum):
    admin = "admin"        # full control, corrections, settings, biometric data
    operator = "operator"  # may run the live scanner and view records
    viewer = "viewer"      # read-only


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False, length=16), default=Role.viewer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)  # bump to revoke tokens
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
