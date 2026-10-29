from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.timeutil import utc_now
from app.models import AuditLog, User


def log(db: Session, action: str, user: User | None = None, entity_type: str | None = None,
        entity_id: Any = None, details: dict | None = None, ip: str | None = None,
        commit: bool = True) -> None:
    """Record an administrative action. Never put biometric data or secrets in `details`."""
    db.add(AuditLog(
        user_id=user.id if user else None, username=user.username if user else None,
        action=action, entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details, ip_address=ip,
    ))
    if commit:
        db.commit()


def purge_older_than(db: Session, days: int) -> int:
    cutoff = utc_now() - timedelta(days=days)
    n = db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete()
    db.commit()
    return n
