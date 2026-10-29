"""Time helpers. All instants are stored in UTC; local wall-clock is derived
from the configurable attendance timezone."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {name!r}") from exc


def is_valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def to_local(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_zone(tz_name))


def local_date_time(dt: datetime, tz_name: str) -> tuple[date, time]:
    local = to_local(dt, tz_name)
    return local.date(), local.time().replace(microsecond=0)


def local_to_utc(d: date, t: time, tz_name: str) -> datetime:
    return datetime.combine(d, t, tzinfo=get_zone(tz_name)).astimezone(timezone.utc)
