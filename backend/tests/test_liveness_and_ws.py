"""Liveness challenge (EXPERIMENTAL) and the WebSocket scanner protocol. MOCKED recognition."""
from __future__ import annotations

import random

import numpy as np
import pytest
from sqlalchemy import func, select
from starlette.websockets import WebSocketDisconnect

from app.database.base import SessionLocal
from app.models import AttendanceRecord
from app.services.liveness import CHALLENGE_SECONDS, VERIFIED_TTL, LivenessSession
from tests.conftest import fake_png, make_person, open_session, scan


def unit(seed=1):
    v = np.random.default_rng(seed).normal(size=512).astype(np.float32)
    return v / np.linalg.norm(v)


class Clock:
    def __init__(self): self.t = 100.0
    def __call__(self): return self.t


def started(clock=None, seed=7):
    clock = clock or Clock()
    ls = LivenessSession(rng=random.Random(seed), clock=clock)
    e = unit()
    assert ls.update(0.0, e).status == "need_frontal"
    st = ls.update(0.01, e)
    assert st.status == "challenge" and st.challenge in ("left", "right")
    return ls, st.challenge, e, clock


def test_challenge_passes_when_head_turns_the_requested_way():
    ls, challenge, e, _ = started()
    wrong = -0.4 if challenge == "left" else 0.4
    assert ls.update(wrong, e).status == "challenge"                      # opposite direction does not count
    st = ls.update(0.4 if challenge == "left" else -0.4, e)
    assert st.status == "passed" and np.allclose(st.reference, e)


def test_static_photo_never_passes_and_times_out():
    ls, _, e, clock = started()
    for _ in range(20):                                                    # 6 s of a held-up photo: it never turns
        assert ls.update(0.0, e).status == "challenge"
        clock.t += 0.3
    clock.t += CHALLENGE_SECONDS
    st = ls.update(0.0, e)
    assert st.status == "failed" and st.reason == "timeout"


def test_challenge_fails_if_the_face_changes_mid_challenge():
    ls, challenge, e, _ = started()
    st = ls.update(0.4 if challenge == "left" else -0.4, unit(99))         # someone else turns their head
    assert st.status == "failed" and st.reason == "face_changed"


def test_pass_expires():
    ls, challenge, e, clock = started()
    ls.update(0.4 if challenge == "left" else -0.4, e)
    assert ls.passed_recently()
    clock.t += VERIFIED_TTL + 1
    assert not ls.passed_recently()


def test_challenge_direction_is_random():
    seen = {started(seed=s)[1] for s in range(12)}
    assert seen == {"left", "right"}


# ---- policy through the API ---------------------------------------------------------------------
def set_policy(admin, policy):
    assert admin.put("/api/v1/settings", json={"liveness_policy": policy}).status_code == 200


def test_rest_endpoint_cannot_bypass_an_enabled_liveness_challenge(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    set_policy(admin, "challenge")
    r = scan(admin, 1).json()
    assert r["status"] == "liveness_unsupported"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 0


def test_status_reports_liveness_limitations(admin, fake_engine):
    st = admin.get("/api/v1/recognition/status").json()
    assert st["liveness_policy"] == "off" and "photo or screen could be accepted" in st["liveness_note"]
    set_policy(admin, "challenge")
    assert "NOT presentation-attack detection" in admin.get("/api/v1/recognition/status").json()["liveness_note"]
    assert "not a probability" in st["similarity_note"]


# ---- WebSocket protocol --------------------------------------------------------------------------
def ws_of(client):
    return client.websocket_connect("/api/v1/recognition/ws")


def test_ws_rejects_unauthenticated_and_unprivileged(anon, viewer):
    for c in (anon, viewer):
        with pytest.raises(WebSocketDisconnect) as exc:
            with ws_of(c):
                pass
        assert exc.value.code in (4401, 1008)


def test_ws_rejects_foreign_origin(admin):
    with pytest.raises(WebSocketDisconnect) as exc:
        with admin.websocket_connect("/api/v1/recognition/ws", headers={"origin": "https://evil.example"}):
            pass
    assert exc.value.code == 4403


def test_ws_full_attendance_flow(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    with ws_of(admin) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["model_loaded"] is True and hello["liveness_policy"] == "off"
        ws.send_bytes(fake_png(1, 5, flag=1))
        assert ws.receive_json()["status"] == "no_face"
        ws.send_bytes(fake_png(77, 5))
        assert ws.receive_json()["status"] == "unknown"
        ws.send_bytes(fake_png(1, 5))
        r = ws.receive_json()
        assert r["type"] == "result" and r["status"] == "marked" and r["person"]["full_name"] == "Ann Lee"
        ws.send_bytes(fake_png(1, 6))                       # person is still standing there
        assert ws.receive_json()["status"] == "cooldown"
        ws.send_text('{"type": "reset"}')
        ws.send_bytes(fake_png(1, 6))
        assert ws.receive_json()["status"] == "already_marked"
        ws.send_text('{"type": "ping"}')
        assert ws.receive_json() == {"type": "pong"}
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 1


def test_ws_rejects_oversized_frames(admin, fake_engine):
    with ws_of(admin) as ws:
        ws.receive_json()
        ws.send_bytes(b"\x89PNG" + b"0" * (2 * 1024 * 1024 + 10))
        assert ws.receive_json()["code"] == "frame_too_large"


def test_ws_liveness_challenge_end_to_end(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    set_policy(admin, "challenge")
    with ws_of(admin) as ws:
        assert ws.receive_json()["liveness_policy"] == "challenge"
        ws.send_bytes(fake_png(1, 5))                                   # frontal #1
        assert ws.receive_json()["status"] == "liveness_challenge"
        ws.send_bytes(fake_png(1, 5))                                   # frontal #2 -> challenge issued
        first = ws.receive_json()
        assert first["status"] == "liveness_challenge" and first["challenge"] in ("left", "right")
        ws.send_bytes(fake_png(1, 5))                                   # not turning: still waiting
        assert ws.receive_json()["status"] == "liveness_challenge"
        want_flag = 4 if first["challenge"] == "left" else 5
        ws.send_bytes(fake_png(1, 5, flag=want_flag))                   # turns the requested way
        done = ws.receive_json()
        assert done["status"] == "marked" and done["person"]["person_code"] == "E1"
    with SessionLocal() as db:
        rec = db.scalars(select(AttendanceRecord)).one()
        assert rec.decision_meta["liveness"] == "challenge_passed"


def test_ws_liveness_wrong_person_cannot_complete_someone_elses_challenge(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    set_policy(admin, "challenge")
    with ws_of(admin) as ws:
        ws.receive_json()
        ws.send_bytes(fake_png(1, 5)); ws.receive_json()
        ws.send_bytes(fake_png(1, 5)); first = ws.receive_json()
        want_flag = 4 if first["challenge"] == "left" else 5
        ws.send_bytes(fake_png(2, 5, flag=want_flag))                   # a different face finishes the turn
        assert ws.receive_json()["status"] == "liveness_failed"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 0
