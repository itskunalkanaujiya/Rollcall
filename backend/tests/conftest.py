"""Test harness.

MOCKED tests use `FakeEngine`, a deterministic stand-in for the neural network, so business logic
(sessions, duplicates, races, permissions, reports) is tested quickly and without model files.
Tests that exercise the REAL ArcFace pipeline live in test_real_model.py and carry the
`real_model` marker; they are skipped automatically when the model or sample images are absent.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="attendance-tests-"))
os.environ.update({
    "ENVIRONMENT": "test",
    "SECRET_KEY": "test-secret-key-test-secret-key-0123456789",
    "EMBEDDING_ENCRYPTION_KEY": "test-embedding-key-test-embedding-key-01",
    "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "LOAD_MODEL_ON_STARTUP": "false",
    "DEFAULT_TIMEZONE": "UTC",
    "LOGIN_RATE_LIMIT": "1000",
    "MIN_ENROLL_IMAGES": "3",
})

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.rate_limit import limiter  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database.base import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.services.embedding_cache import get_cache  # noqa: E402
from app.services.face_detection import DetectedFace  # noqa: E402
from app.services.face_recognition import EngineInfo, set_engine  # noqa: E402

ADMIN = ("admin", "correct-horse-battery")
OPERATOR = ("operator", "operator-password-1")
VIEWER = ("viewer", "viewer-password-12")


# ---------------------------------------------------------------------------------------------
# synthetic "faces" for the MOCKED engine.  Identity lives in pixel (0,0): B = identity id,
# G = flag (0 normal, 1 no face, 2 two faces, 3 low quality, 4/5 head turned), R = sample variant (tiny noise).
# PNG is lossless so the marker survives encoding.
# ---------------------------------------------------------------------------------------------
def fake_png(identity: int, variant: int = 0, flag: int = 0) -> bytes:
    rng = np.random.default_rng(identity * 1000 + variant)
    img = rng.integers(70, 190, size=(160, 160, 3), dtype=np.uint8)
    if flag == 3:
        img[:] = 128                                  # flat -> Laplacian variance 0 -> "too_blurry"
    img[0, 0] = (identity, flag, variant)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def identity_vector(identity: int) -> np.ndarray:
    v = np.random.default_rng(identity + 12345).normal(size=512).astype(np.float32)
    return v / np.linalg.norm(v)


class _FakeSettings:
    model_name = "fake-test-model"


class FakeEngine:
    """Implements the slice of FaceEngine the services use. NOT a recognition model."""
    is_loaded = True
    settings = _FakeSettings()
    info = EngineInfo(True, "fake-test-model", ["fake"], ["fake"], 0)

    def require(self):
        return None

    def detect(self, img):
        flag = int(img[0, 0, 1])
        h, w = img.shape[:2]
        if flag == 1:
            return []
        nose_x = {4: 100, 5: 60}.get(flag, 80)          # flag 4/5: head turned (yaw proxy +/-0.33)
        kps = np.array([[50, 60], [110, 60], [nose_x, 90], [58, 120], [102, 120]], dtype=np.float32)
        faces = [DetectedFace(np.array([8, 8, w - 8, h - 8], dtype=np.float32), kps, 0.99)]
        if flag == 2:
            faces.append(DetectedFace(np.array([8, 8, w - 9, h - 9], dtype=np.float32), kps, 0.98))
        return faces

    def embed(self, img, face):
        ident, variant = int(img[0, 0, 0]), int(img[0, 0, 2])
        v = identity_vector(ident)
        if variant:
            n = np.random.default_rng(variant).normal(size=512).astype(np.float32)
            v = v + 0.02 * n / np.linalg.norm(n)
            v /= np.linalg.norm(v)
        return v


@pytest.fixture(autouse=True)
def _clean_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    limiter.reset()
    with SessionLocal() as db:
        db.add_all([
            User(username=ADMIN[0], password_hash=hash_password(ADMIN[1]), role=Role.admin),
            User(username=OPERATOR[0], password_hash=hash_password(OPERATOR[1]), role=Role.operator),
            User(username=VIEWER[0], password_hash=hash_password(VIEWER[1]), role=Role.viewer),
        ])
        db.commit()
        get_cache().refresh(db)
    yield


@pytest.fixture
def fake_engine():
    eng = FakeEngine()
    set_engine(eng)  # type: ignore[arg-type]
    yield eng
    set_engine(None)


@pytest.fixture
def anon() -> TestClient:
    return TestClient(app)


def _login(creds: tuple[str, str]) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"username": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def admin() -> TestClient:
    return _login(ADMIN)


@pytest.fixture
def operator() -> TestClient:
    return _login(OPERATOR)


@pytest.fixture
def viewer() -> TestClient:
    return _login(VIEWER)


# ---- helpers -----------------------------------------------------------------------------------
def open_session(client: TestClient, name: str = "All day", late_cutoff: str | None = "23:59:59", **kw) -> dict:
    """A session that is open every day, all day (UTC) so tests do not depend on the wall clock."""
    body = {"name": name, "start_time": "00:00:00", "end_time": "23:59:59", "late_cutoff": late_cutoff,
            "days_of_week": [0, 1, 2, 3, 4, 5, 6], "early_checkin_minutes": 0, **kw}
    r = client.post("/api/v1/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def make_person(client: TestClient, code: str, name: str, identity: int | None = None,
                department: str | None = "Engineering", enroll: bool = True) -> dict:
    r = client.post("/api/v1/people", json={"person_code": code, "full_name": name, "department": department,
                                            "role": "employee"})
    assert r.status_code == 201, r.text
    person = r.json()
    if enroll and identity is not None:
        r = enroll_fake(client, person["id"], identity)
        assert r.status_code == 200, r.text
    return person


def enroll_fake(client: TestClient, person_id: int, identity: int, n: int = 3, **form):
    files = [("files", (f"s{i}.png", fake_png(identity, i), "image/png")) for i in range(n)]
    return client.post(f"/api/v1/people/{person_id}/enroll", files=files, data={"consent": "true", **form})


def scan(client: TestClient, identity: int, variant: int = 9, flag: int = 0):
    return client.post("/api/v1/recognition/recognize",
                       files={"file": ("f.png", fake_png(identity, variant, flag), "image/png")})
