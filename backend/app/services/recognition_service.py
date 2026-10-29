"""The live recognition pipeline: frame -> detect -> quality -> embed -> (liveness) -> match ->
session check -> attendance record.

`recognize_frame` is blocking (ONNX inference + a DB transaction) and must be called from a
worker thread (`asyncio.to_thread` / a sync FastAPI route), never directly on the event loop.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.timeutil import local_date_time, utc_now
from app.models import Person
from app.services import attendance_service as att
from app.services import settings_service
from app.services.embedding_cache import get_cache
from app.services.face_detection import ModelUnavailableError, assess_quality
from app.services.face_recognition import FaceEngine, Timings, get_engine
from app.services.imaging import ImageError, decode_image
from app.services.liveness import LivenessSession

log = logging.getLogger("app.recognition")
perf = logging.getLogger("app.perf")

MESSAGES = {
    "no_face": "Please look at the camera.",
    "multiple_faces": "More than one face in view. One person at a time, please.",
    "unknown": "Person not recognized. No attendance recorded.",
    "already_marked": "Your attendance has already been recorded.",
    "no_active_session": "No attendance session is open right now. No attendance recorded.",
    "person_disabled": "This account is disabled. No attendance recorded.",
    "liveness_failed": "Verification failed. Please try again.",
    "liveness_unsupported": "Liveness challenge needs the live scanner connection; attendance was not recorded.",
    "model_unavailable": "The face recognition model is not available. Contact an administrator.",
    "bad_image": "The camera frame could not be read.",
    "cooldown": "Please wait a moment before the next scan.",
}


@dataclass
class ScannerState:
    """Per scanner-connection state (one person at a time)."""
    liveness: LivenessSession = field(default_factory=LivenessSession)
    cooldown_until: float = 0.0   # monotonic seconds
    busy: bool = False

    def reset(self) -> None:
        self.liveness.reset()
        self.cooldown_until = 0.0


def _result(status: str, *, message: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"status": status, "message": message or MESSAGES.get(status, ""), **extra}


def _person_payload(p: Person) -> dict[str, Any]:
    return {"id": p.id, "person_code": p.person_code, "full_name": p.full_name,
            "department": p.department.name if p.department else None}


def recognize_frame(db: Session, data: bytes, state: ScannerState | None = None,
                    engine: FaceEngine | None = None) -> dict[str, Any]:
    t_start = time.perf_counter()
    tm = Timings()
    engine = engine or get_engine()
    now_mono = time.monotonic()

    if state is not None and now_mono < state.cooldown_until:
        return _result("cooldown", retry_after=round(state.cooldown_until - now_mono, 1))

    try:
        engine.require()
    except ModelUnavailableError as exc:
        log.error("Model unavailable: %s", exc)
        return _result("model_unavailable", detail=str(exc))

    cfg = settings_service.get_all(db)
    try:
        t = time.perf_counter()
        img = decode_image(data, max_bytes=2 * 1024 * 1024)
        tm.decode_ms = (time.perf_counter() - t) * 1000
    except ImageError as exc:
        return _result("bad_image", message=exc.message, code=exc.code)

    t = time.perf_counter()
    faces = engine.detect(img)
    tm.detect_ms = (time.perf_counter() - t) * 1000
    if not faces:
        if state:
            state.liveness.reset()
        return _result("no_face", timings=tm.as_dict())
    if len(faces) > 1 and faces[1].area > 0.35 * faces[0].area:
        if state:
            state.liveness.reset()
        return _result("multiple_faces", timings=tm.as_dict())
    face = faces[0]
    h, w = img.shape[:2]
    bbox = {"x": float(face.bbox[0]) / w, "y": float(face.bbox[1]) / h,
            "w": face.width / w, "h": face.height / h}   # normalised to the frame

    q = assess_quality(img, face, min_size=cfg["min_face_size_px"], min_score=cfg["min_det_score"])
    if not q.ok:
        return _result("poor_quality", message=q.hint, issues=q.issues, bbox=bbox, timings=tm.as_dict())

    t = time.perf_counter()
    emb = engine.embed(img, face)
    tm.embed_ms = (time.perf_counter() - t) * 1000

    # ---- liveness (separate from identity) --------------------------------
    policy = cfg["liveness_policy"]
    liveness_meta = "off"
    if policy == "challenge":
        if state is None:
            return _result("liveness_unsupported", bbox=bbox)
        ls = state.liveness.update(q.yaw, emb)
        if ls.status in ("need_frontal", "challenge"):
            return _result("liveness_challenge", message=ls.instruction, challenge=ls.challenge, bbox=bbox,
                           timings=tm.as_dict())
        if ls.status == "failed":
            return _result("liveness_failed", reason=ls.reason, bbox=bbox)
        if ls.status != "passed":
            return _result("liveness_challenge", message="Look at the camera.", bbox=bbox)
        if ls.reference is not None:
            emb = ls.reference   # identify from the frontal frame captured before the head turn
        liveness_meta = "challenge_passed"

    t = time.perf_counter()
    m = get_cache().match(emb, cfg["recognition_threshold"], cfg["recognition_margin"])
    tm.match_ms = (time.perf_counter() - t) * 1000

    def finish(res: dict[str, Any], lock: bool) -> dict[str, Any]:
        tm.total_ms = (time.perf_counter() - t_start) * 1000
        res["timings"] = tm.as_dict()
        if state is not None:
            state.liveness.reset()
            if lock:
                state.cooldown_until = time.monotonic() + cfg["cooldown_seconds"]
        perf.info("recognition status=%s detect=%.0fms embed=%.0fms match=%.1fms total=%.0fms",
                  res["status"], tm.detect_ms, tm.embed_ms, tm.match_ms, tm.total_ms)
        return res

    if m.person_id is None:
        # Never fall back to the "closest" person.
        return finish(_result("unknown", reason=m.reason, bbox=bbox), lock=False)
    person = db.get(Person, m.person_id)
    if person is None:
        return finish(_result("unknown", reason="stale_gallery", bbox=bbox), lock=False)
    if not m.active or person.status.value != "active":
        return finish(_result("person_disabled", bbox=bbox, person=_person_payload(person)), lock=True)

    tz = cfg["timezone"]
    now = utc_now()
    resolved = att.resolve_open_session(db, person, tz, now)
    if resolved is None:
        return finish(_result("no_active_session", bbox=bbox, person=_person_payload(person)), lock=True)
    session, session_date = resolved
    meta = {"threshold": cfg["recognition_threshold"], "margin": cfg["recognition_margin"],
            "second_best": round(m.second_similarity, 4), "liveness": liveness_meta,
            "model": engine.settings.model_name}
    outcome = att.mark_face_attendance(db, person, session, session_date, tz, m.best_similarity, meta, now)
    rec = outcome.record
    _, local_t = local_date_time(rec.marked_at, tz)
    payload = {
        "bbox": bbox, "person": _person_payload(person),
        "attendance": {"id": rec.id, "session": session.name, "session_date": session_date.isoformat(),
                       "marked_at": rec.marked_at.isoformat(), "local_time": local_t.strftime("%H:%M:%S"),
                       "status": rec.status.value, "method": rec.method.value},
        # cosine similarity between face templates - a score, NOT a probability of identity
        "similarity": round(m.best_similarity, 3),
    }
    if outcome.created:
        msg = f"Welcome, {person.full_name}. Attendance recorded at {local_t.strftime('%I:%M %p').lstrip('0')}."
        return finish(_result("marked", message=msg, **payload), lock=True)
    return finish(_result("already_marked", **payload), lock=True)
