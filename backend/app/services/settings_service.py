"""Runtime, admin-editable settings stored in the DB (seeded from env defaults)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import is_valid_timezone
from app.models import AppSetting


class SettingsValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    default: Callable[[], Any]
    validate: Callable[[Any], Any]
    description: str
    sensitive: bool = False  # recognition/security settings: admin only (all writes are admin only anyway)


def _num(lo: float, hi: float, typ: type):
    def v(x: Any):
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise SettingsValidationError(f"must be a number between {lo} and {hi}")
        x = typ(x)
        if not lo <= x <= hi:
            raise SettingsValidationError(f"must be between {lo} and {hi}")
        return x
    return v


def _choice(*opts: str):
    def v(x: Any):
        if x not in opts:
            raise SettingsValidationError(f"must be one of {list(opts)}")
        return x
    return v


def _tz(x: Any):
    if not isinstance(x, str) or not is_valid_timezone(x):
        raise SettingsValidationError("must be a valid IANA timezone, e.g. 'Asia/Kolkata'")
    return x


_s = get_settings
SPECS: dict[str, Spec] = {
    "timezone": Spec(lambda: _s().default_timezone, _tz, "Attendance timezone (IANA name)"),
    "recognition_threshold": Spec(
        lambda: _s().default_recognition_threshold, _num(0.2, 0.9, float),
        "Minimum cosine similarity to accept an identity (not a probability)", True),
    "recognition_margin": Spec(
        lambda: _s().default_recognition_margin, _num(0.0, 0.3, float),
        "Required similarity gap between the best and second-best person", True),
    "liveness_policy": Spec(lambda: "off", _choice("off", "challenge"),
        "off = no spoof protection (demo only); challenge = experimental head-turn challenge", True),
    "frame_interval_ms": Spec(lambda: 700, _num(200, 5000, int), "Browser frame send interval"),
    "cooldown_seconds": Spec(lambda: 10, _num(3, 300, int), "Scanner lock after a result"),
    "camera_width": Spec(lambda: 1280, _num(320, 1920, int), "Requested camera width"),
    "camera_height": Spec(lambda: 720, _num(240, 1080, int), "Requested camera height"),
    "min_face_size_px": Spec(lambda: 80, _num(40, 400, int), "Smallest accepted face (pixels, shorter side)", True),
    "min_det_score": Spec(lambda: 0.6, _num(0.3, 0.99, float), "Minimum detector confidence", True),
    "retention_audit_days": Spec(lambda: 365, _num(30, 3650, int), "Days to keep audit logs"),
    "retention_attendance_days": Spec(lambda: 0, _num(0, 3650, int), "Days to keep attendance (0 = forever)"),
}


def get_all(db: Session) -> dict[str, Any]:
    stored = {r.key: r.value for r in db.query(AppSetting).all()}
    return {k: stored.get(k, spec.default()) for k, spec in SPECS.items()}


def get_value(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    return row.value if row is not None else SPECS[key].default()


def update(db: Session, patch: dict[str, Any], user_id: int | None) -> dict[str, Any]:
    errors: dict[str, str] = {}
    clean: dict[str, Any] = {}
    for key, raw in patch.items():
        spec = SPECS.get(key)
        if spec is None:
            errors[key] = "unknown setting"
            continue
        try:
            clean[key] = spec.validate(raw)
        except SettingsValidationError as exc:
            errors[key] = str(exc)
    if errors:
        raise SettingsValidationError(errors)  # type: ignore[arg-type]
    for key, value in clean.items():
        row = db.get(AppSetting, key)
        if row is None:
            db.add(AppSetting(key=key, value=value, updated_by=user_id))
        else:
            row.value, row.updated_by = value, user_id
    db.commit()
    return get_all(db)
