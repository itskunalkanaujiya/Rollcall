"""Authentication and authorization (spec cases 1, 2, 14)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from tests.conftest import ADMIN, OPERATOR, VIEWER, make_person, open_session


def test_admin_login_succeeds(anon):
    r = anon.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "admin" and body["role"] == "admin"
    assert "password_hash" not in body and "access_token" not in body      # no secrets in the body
    assert "httponly" in r.headers["set-cookie"].lower()
    assert anon.get("/api/v1/auth/me").json()["username"] == "admin"


def test_login_fails_with_invalid_credentials(anon):
    wrong_pw = anon.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": "nope"})
    no_user = anon.post("/api/v1/auth/login", json={"username": "ghost", "password": "nope"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.json()["error"]["message"] == no_user.json()["error"]["message"]   # no user enumeration
    assert anon.get("/api/v1/auth/me").status_code == 401


def test_login_is_rate_limited(anon, monkeypatch):
    monkeypatch.setattr(get_settings(), "login_rate_limit", 3)
    codes = [anon.post("/api/v1/auth/login", json={"username": "admin", "password": "x"}).status_code
             for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_private_endpoints_require_authentication(anon):
    for path in ("/api/v1/people", "/api/v1/attendance", "/api/v1/dashboard/summary", "/api/v1/sessions",
                 "/api/v1/settings", "/api/v1/reports/export"):
        assert anon.get(path).status_code == 401, path


def test_logout_revokes_the_token(admin):
    token = admin.cookies.get("access_token")
    assert admin.post("/api/v1/auth/logout").status_code == 204
    fresh = TestClient(app)
    assert fresh.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_cross_origin_state_change_is_blocked(admin):
    r = admin.post("/api/v1/people", headers={"Origin": "https://evil.example"},
                   json={"person_code": "X1", "full_name": "Eve Attacker"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "bad_origin"


def test_unauthorized_users_cannot_modify_attendance(admin, anon, operator, viewer, fake_engine):
    s = open_session(admin)
    p = make_person(admin, "E1", "Ann Lee", identity=1)
    rec = admin.post("/api/v1/attendance/manual", json={
        "person_id": p["id"], "session_id": s["id"], "session_date": "2020-01-06", "status": "present",
        "note": "badge reader down"}).json()
    body = {"status": "late", "note": "tampering"}
    assert anon.put(f"/api/v1/attendance/{rec['id']}", json=body).status_code == 401
    for client in (viewer, operator):
        assert client.put(f"/api/v1/attendance/{rec['id']}", json=body).status_code == 403
        assert client.post("/api/v1/attendance/manual", json={
            "person_id": p["id"], "session_id": s["id"], "session_date": "2020-01-07", "status": "present",
            "note": "tampering"}).status_code == 403
    assert admin.get(f"/api/v1/attendance/{rec['id']}").json()["status"] == "present"   # unchanged


def test_role_boundaries(admin, operator, viewer):
    payload = {"person_code": "R1", "full_name": "Role Test"}
    assert viewer.post("/api/v1/people", json=payload).status_code == 403
    assert operator.post("/api/v1/people", json=payload).status_code == 403
    assert viewer.get("/api/v1/people").status_code == 200
    assert viewer.get("/api/v1/settings").status_code == 403           # settings readable by operator+
    assert operator.get("/api/v1/settings").status_code == 200
    assert operator.put("/api/v1/settings", json={"recognition_threshold": 0.2}).status_code == 403
    assert viewer.get("/api/v1/audit-logs").status_code == 403
    assert viewer.post("/api/v1/recognition/recognize", files={"file": ("a.png", b"x", "image/png")}).status_code == 403


def test_cannot_demote_or_disable_last_admin(admin):
    me = admin.get("/api/v1/auth/me").json()
    assert admin.put(f"/api/v1/users/{me['id']}", json={"is_active": False}).status_code == 400
    assert admin.put(f"/api/v1/users/{me['id']}", json={"role": "viewer"}).status_code == 400
