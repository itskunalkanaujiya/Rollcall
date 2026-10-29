"""Recognition endpoints.

WebSocket protocol  (GET /api/v1/recognition/ws, authenticated by the session cookie; admin/operator)
  client -> server  BINARY message: one JPEG/PNG/WEBP camera frame (<= MAX_FRAME_BYTES)
                    TEXT   message: {"type": "reset"}   forget liveness/cooldown state
                                    {"type": "ping"}
  server -> client  TEXT JSON:
      {"type": "hello",  "model_loaded": bool, "liveness_policy": "off|challenge", "frame_interval_ms": int}
      {"type": "result", "status": <see below>, "message": str, "person"?: {...}, "attendance"?: {...},
                         "similarity"?: float, "bbox"?: {x,y,w,h}, "timings": {...ms}}
      {"type": "pong"} | {"type": "error", "code": str, "message": str}
  status: no_face | multiple_faces | poor_quality | liveness_challenge | liveness_failed | unknown |
          marked | already_marked | no_active_session | person_disabled | model_unavailable |
          bad_image | cooldown
The server keeps only the NEWEST pending frame (older ones are dropped), processes one frame at a
time per connection, and a "marked"/"already_marked" result starts a server-side cooldown during
which frames are answered with {"status":"cooldown"} without running inference.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.deps import current_user, require_operator, user_from_token, _token_from
from app.core.errors import AppError
from app.database.base import SessionLocal, get_db
from app.models import Role, User
from app.services import settings_service
from app.services.embedding_cache import get_cache
from app.services.face_recognition import get_engine
from app.services.recognition_service import ScannerState, recognize_frame
from sqlalchemy.orm import Session

log = logging.getLogger("app.recognition")
router = APIRouter(tags=["recognition"])

LIVENESS_NOTE = (
    "Experimental random head-turn challenge. It is NOT presentation-attack detection: a video replay, "
    "a 3-D mask or a determined attacker can defeat it. With policy 'off' there is no spoof protection at all; "
    "use only in a supervised environment."
)


def _recognize_in_thread(data: bytes, state: ScannerState | None) -> dict[str, Any]:
    with SessionLocal() as db:       # each call gets its own DB session/transaction
        return recognize_frame(db, data, state)


@router.get("/recognition/status")
def status(_: User = Depends(require_operator), db: Session = Depends(get_db)):
    eng = get_engine()
    cfg = settings_service.get_all(db)
    templates, people = get_cache().size
    return {
        "model_loaded": eng.is_loaded, "model_name": eng.info.model_name, "providers_active": eng.info.providers_active,
        "model_error": eng.info.error, "notes": eng.info.notes, "enrolled_people": people, "templates": templates,
        "recognition_threshold": cfg["recognition_threshold"],
        "similarity_note": "Cosine similarity between face templates. It is a score, not a probability.",
        "liveness_policy": cfg["liveness_policy"],
        "liveness_note": LIVENESS_NOTE if cfg["liveness_policy"] == "challenge" else
        "Liveness check is OFF: a photo or screen could be accepted. Enable the challenge in Settings.",
        "frame_interval_ms": cfg["frame_interval_ms"], "cooldown_seconds": cfg["cooldown_seconds"],
        "camera": {"width": cfg["camera_width"], "height": cfg["camera_height"]},
    }


@router.post("/recognition/recognize")
def recognize(request: Request, file: UploadFile = File(...), user: User = Depends(require_operator)):
    """Single-image recognition + attendance marking (the same service the WebSocket uses).
    Stateless, so the liveness *challenge* policy is not available here (it answers
    `liveness_unsupported` and records nothing)."""
    s = get_settings()
    data = file.file.read(s.max_frame_bytes + 1)
    if len(data) > s.max_frame_bytes:
        raise AppError(413, "frame_too_large", "Image too large")
    result = _recognize_in_thread(data, None)
    if result["status"] == "model_unavailable":
        # Only admin/operator accounts reach this endpoint, so the actionable detail
        # (which file is missing, how to download it) is returned rather than hidden.
        raise AppError(503, "model_unavailable", result.get("detail") or result["message"])
    return result


@router.websocket("/recognition/ws")
async def recognition_ws(ws: WebSocket) -> None:
    s = get_settings()
    origin = ws.headers.get("origin")
    if origin and origin not in s.cors_origin_list:
        await ws.close(code=4403)      # blocks cross-site WebSocket hijacking
        return
    with SessionLocal() as db:
        user = user_from_token(db, _token_from(ws))
        cfg = settings_service.get_all(db)
    if user is None or user.role not in (Role.admin, Role.operator):
        await ws.close(code=4401)
        return
    await ws.accept()
    eng = get_engine()
    await ws.send_json({"type": "hello", "model_loaded": eng.is_loaded, "liveness_policy": cfg["liveness_policy"],
                        "frame_interval_ms": cfg["frame_interval_ms"]})

    state = ScannerState()
    latest: dict[str, bytes | None] = {"frame": None}
    wake = asyncio.Event()
    closed = asyncio.Event()

    async def reader() -> None:
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    if len(msg["bytes"]) > s.max_frame_bytes:
                        await ws.send_json({"type": "error", "code": "frame_too_large", "message": "Frame too large"})
                        continue
                    latest["frame"] = msg["bytes"]      # newest wins; stale frames are dropped
                    wake.set()
                elif msg.get("text"):
                    try:
                        import json
                        data = json.loads(msg["text"])
                    except ValueError:
                        continue
                    if data.get("type") == "reset":
                        state.reset()
                        latest["frame"] = None
                    elif data.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            closed.set()
            wake.set()

    reader_task = asyncio.create_task(reader())
    try:
        while True:
            await wake.wait()
            wake.clear()
            if closed.is_set():
                break
            frame, latest["frame"] = latest["frame"], None
            if frame is None:
                continue
            try:
                # inference + DB work happen in a worker thread so the event loop stays responsive
                result = await run_in_threadpool(_recognize_in_thread, frame, state)
            except Exception:  # noqa: BLE001 - report, never crash the socket loop silently
                log.exception("Recognition failed")
                await ws.send_json({"type": "error", "code": "internal_error", "message": "Recognition failed"})
                continue
            await ws.send_json({"type": "result", **result})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        reader_task.cancel()
        state.reset()
