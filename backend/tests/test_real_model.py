"""REAL computer-vision tests: InsightFace buffalo_l (SCRFD detector + ArcFace R50), no mocks.

Images: the sample photographs that ship inside the installed `insightface` package
(`insightface/data/images/t1.jpg` shows six different people; `Tom_Hanks_54745.png` one more).
They are read from site-packages at test time and are not copied into this repository.
"Same person" variants are made from the same photo (flip / darker / smaller), so these tests prove
the pipeline separates six different identities and tolerates photometric changes - they are NOT a
benchmark of cross-photo accuracy (that needs a consented multi-photo dataset; see docs/EVALUATION.md).

Skipped automatically when the model files are not installed.
"""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.database.base import SessionLocal
from app.models import AttendanceRecord
from app.services.face_recognition import FaceEngine, set_engine
from tests.conftest import make_person, open_session

pytestmark = pytest.mark.real_model

MODEL_DIR = Path(get_settings().model_root) / get_settings().model_name


def _sample(name: str):
    try:
        from insightface.data import get_image
        return get_image(name)
    except Exception:                                    # noqa: BLE001
        return None


if not (MODEL_DIR / "w600k_r50.onnx").exists() or _sample("t1") is None:
    pytest.skip("InsightFace model or sample images not available", allow_module_level=True)


@pytest.fixture(scope="module")
def engine():
    eng = FaceEngine()
    t = time.perf_counter()
    eng.load()
    print(f"\n[real] model load: {time.perf_counter() - t:.1f}s providers={eng.info.providers_active}")
    return eng


@pytest.fixture(scope="module")
def faces(engine):
    """Six face crops (with context) cut from the group photo t1.jpg."""
    img = _sample("t1")
    det = engine.detect(img)
    assert len(det) == 6, f"expected 6 faces in the sample photo, found {len(det)}"
    det.sort(key=lambda f: f.bbox[0])                                   # stable left-to-right order
    crops = []
    for f in det:
        x1, y1, x2, y2 = (int(v) for v in f.bbox)
        pad = int(0.7 * (x2 - x1))
        crop = img[max(0, y1 - pad): y2 + pad, max(0, x1 - pad): x2 + pad]
        scale = 1.6                                                    # larger crop => larger face => passes size rule
        crops.append(cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC))
    return crops


def png(img) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def jpg(img, q=88) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    assert ok
    return buf.tobytes()


def variants(img):
    """Three genuinely different pixel renderings of one face."""
    return [img, cv2.flip(img, 1), cv2.convertScaleAbs(img, alpha=0.75, beta=-5)]


def embed_one(engine, img):
    det = engine.detect(img)
    assert det, "no face found"
    return engine.embed(img, det[0])


@pytest.fixture
def real_engine(engine):
    set_engine(engine)
    yield engine
    set_engine(None)


def scan_real(client, img):
    return client.post("/api/v1/recognition/recognize", files={"file": ("f.jpg", jpg(img), "image/jpeg")}).json()


# ---- pipeline-level facts -----------------------------------------------------------------------
def test_embeddings_are_512d_unit_vectors(engine, faces):
    e = embed_one(engine, faces[0])
    assert e.shape == (512,) and abs(float(np.linalg.norm(e)) - 1.0) < 1e-4


def test_different_people_score_far_below_the_threshold_and_same_person_far_above(engine, faces):
    thr = get_settings().default_recognition_threshold
    embs = np.stack([embed_one(engine, f) for f in faces])
    sims = embs @ embs.T
    off_diag = sims[~np.eye(6, dtype=bool)]
    print(f"\n[real] 6 different people: max cross-identity cosine = {off_diag.max():.3f}  (threshold {thr})")
    assert off_diag.max() < thr - 0.15
    same = []
    for i, f in enumerate(faces):
        for v in variants(f)[1:]:
            same.append(float(embs[i] @ embed_one(engine, v)))
    print(f"[real] same face, flip/darker: min cosine = {min(same):.3f}")
    assert min(same) > thr + 0.25


def test_blank_and_faceless_images_yield_no_detection(engine):
    assert engine.detect(np.full((480, 640, 3), 127, np.uint8)) == []
    noise = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    assert engine.detect(noise) == []


def test_performance_is_measured_not_promised(engine, faces):
    frame = faces[0]
    engine.detect(frame)                                                # warm-up
    t = time.perf_counter()
    n = 5
    for _ in range(n):
        det = engine.detect(frame)
        engine.embed(frame, det[0])
    per = (time.perf_counter() - t) / n * 1000
    print(f"\n[real] detect+embed on {frame.shape[1]}x{frame.shape[0]} frame: {per:.0f} ms/frame (CPU, {engine.info.providers_active})")
    assert per < 5000                                                   # sanity bound only


# ---- end to end through the API: enrol -> scan -> attendance --------------------------------------
def test_end_to_end_enrol_recognise_and_reject_unknown(admin, real_engine, faces):
    open_session(admin, "Real session")
    people = {}
    for idx, (code, name) in enumerate([("R1", "Real One"), ("R2", "Real Two")]):
        p = make_person(admin, code, name, enroll=False)
        files = [("files", (f"{i}.jpg", jpg(v), "image/jpeg")) for i, v in enumerate(variants(faces[idx]))]
        r = admin.post(f"/api/v1/people/{p['id']}/enroll", files=files, data={"consent": "true"})
        assert r.status_code == 200, r.text
        assert r.json()["accepted"] == 3 and r.json()["enrollment_status"] == "enrolled"
        people[code] = p

    # registered people are recognised from a *differently rendered* image (re-encoded JPEG, smaller)
    probe0 = cv2.resize(faces[0], None, fx=0.85, fy=0.85, interpolation=cv2.INTER_AREA)
    r = scan_real(admin, probe0)
    assert r["status"] == "marked", r
    assert r["person"]["person_code"] == "R1" and r["similarity"] > 0.6
    print(f"\n[real] R1 recognised: similarity={r['similarity']} timings={r['timings']}")
    r2 = scan_real(admin, faces[1])
    assert r2["status"] == "marked" and r2["person"]["person_code"] == "R2"

    # same person again: no duplicate
    again = scan_real(admin, cv2.flip(faces[0], 1))
    assert again["status"] == "already_marked" and again["person"]["person_code"] == "R1"

    # four people who were never enrolled must be rejected, not matched to the nearest enrolled person
    outcomes = {i: scan_real(admin, faces[i]) for i in (2, 3, 4, 5)}
    for i, u in outcomes.items():
        # a head-turned photo is refused by the quality gate (poor_quality) before matching; either way no attendance
        assert u["status"] in ("unknown", "poor_quality"), f"face {i}: {u}"
    assert sum(u["status"] == "unknown" for u in outcomes.values()) >= 3     # most really reached the matcher
    tom = _sample("Tom_Hanks_54745")          # 112x112 pre-aligned crop: add the context a camera frame has
    tom = cv2.copyMakeBorder(tom, 56, 56, 56, 56, cv2.BORDER_REPLICATE)
    assert scan_real(admin, tom)["status"] in ("unknown", "poor_quality")

    with SessionLocal() as db:
        recs = db.scalars(select(AttendanceRecord)).all()
        assert len(recs) == 2 and {r.person_id for r in recs} == {p["id"] for p in people.values()}
        assert all(r.similarity > 0.6 and r.method.value == "face" for r in recs)


def test_group_photo_is_refused_as_multiple_faces(admin, real_engine):
    open_session(admin)
    r = scan_real(admin, _sample("t1"))
    assert r["status"] == "multiple_faces"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 0


def test_enrolment_rejects_real_faceless_and_group_images(admin, real_engine, faces):
    p = make_person(admin, "RJ", "Rejects", enroll=False)
    files = [("files", ("blank.png", png(np.full((300, 300, 3), 120, np.uint8)), "image/png")),
             ("files", ("group.jpg", jpg(_sample("t1")), "image/jpeg"))]
    r = admin.post(f"/api/v1/people/{p['id']}/enroll", files=files, data={"consent": "true"})
    assert r.status_code == 422
    assert sorted(x["code"] for x in r.json()["error"]["details"]["rejected"]) == ["multiple_faces", "no_face"]


def test_the_same_human_cannot_be_silently_registered_twice(admin, real_engine, faces):
    a = make_person(admin, "DU1", "First Registration", enroll=False)
    b = make_person(admin, "DU2", "Second Registration", enroll=False)
    files = [("files", (f"{i}.jpg", jpg(v), "image/jpeg")) for i, v in enumerate(variants(faces[3]))]
    assert admin.post(f"/api/v1/people/{a['id']}/enroll", files=files, data={"consent": "true"}).status_code == 200
    r = admin.post(f"/api/v1/people/{b['id']}/enroll", files=files, data={"consent": "true"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "possible_duplicate"
    assert r.json()["error"]["details"]["possible_duplicates"][0]["person_code"] == "DU1"
