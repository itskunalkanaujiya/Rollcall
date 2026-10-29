"""People, enrolment and biometric deletion (spec cases 3, 4, 5, 19). Uses the MOCKED engine."""
from __future__ import annotations

from sqlalchemy import func, select

from app.core.security import decrypt_bytes
from app.database.base import SessionLocal
from app.models import AttendanceRecord, FaceEmbedding, Person
from tests.conftest import enroll_fake, fake_png, identity_vector, make_person, open_session, scan


def test_administrator_can_register_a_person(admin):
    r = admin.post("/api/v1/people", json={"person_code": "S-100", "full_name": "  Rahul   Sharma ",
                                           "email": "rahul@example.com", "department": "CS-A", "role": "student"})
    assert r.status_code == 201
    p = r.json()
    assert p["full_name"] == "Rahul Sharma" and p["department"] == "CS-A" and p["status"] == "active"
    assert p["enrollment_status"] == "not_enrolled" and p["registered_at"]
    assert not {"embedding", "embeddings", "vector", "image"} & set(p)        # no biometric fields in responses
    assert admin.get(f"/api/v1/people/{p['id']}").json()["person_code"] == "S-100"


def test_duplicate_person_ids_are_rejected(admin):
    make_person(admin, "E-1", "First Person", enroll=False)
    r = admin.post("/api/v1/people", json={"person_code": "e-1", "full_name": "Second Person"})   # case-insensitive
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_person_id"
    r = admin.post("/api/v1/people", json={"person_code": "E-2", "full_name": "X Y", "email": "a@b.co"})
    assert r.status_code == 201
    r = admin.post("/api/v1/people", json={"person_code": "E-3", "full_name": "Z Z", "email": "A@B.co"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate_email"


def test_registration_validates_input(admin):
    bad = [{"person_code": "", "full_name": "Ok Name"}, {"person_code": "bad id!", "full_name": "Ok Name"},
           {"person_code": "A1", "full_name": "x"}, {"person_code": "A2", "full_name": "Ok Name", "email": "nope"},
           {"person_code": "A3", "full_name": "Ok Name", "role": "wizard"}]
    for body in bad:
        r = admin.post("/api/v1/people", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", body


def test_enrolment_requires_consent(admin, fake_engine):
    p = make_person(admin, "C1", "No Consent", enroll=False)
    files = [("files", ("a.png", fake_png(1, 0), "image/png"))] * 3
    r = admin.post(f"/api/v1/people/{p['id']}/enroll", files=files, data={"consent": "false"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "consent_required"


def test_enrolment_rejects_unusable_images(admin, fake_engine):
    p = make_person(admin, "U1", "Unusable", enroll=False)
    files = [("files", ("none.png", fake_png(1, 0, flag=1), "image/png")),       # no face
             ("files", ("two.png", fake_png(1, 1, flag=2), "image/png")),        # two people
             ("files", ("flat.png", fake_png(1, 2, flag=3), "image/png")),       # blurry / featureless
             ("files", ("note.txt", b"this is not an image", "image/png")),      # wrong content
             ("files", ("empty.png", b"", "image/png"))]
    r = admin.post(f"/api/v1/people/{p['id']}/enroll", files=files, data={"consent": "true"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "no_usable_images"
    codes = sorted(x["code"] for x in err["details"]["rejected"])
    assert codes == ["empty_image", "multiple_faces", "no_face", "too_blurry", "unsupported_image"]
    assert admin.get(f"/api/v1/people/{p['id']}").json()["enrolled_samples"] == 0


def test_partial_batch_keeps_good_images_and_reports_bad_ones(admin, fake_engine):
    p = make_person(admin, "P1", "Partial", enroll=False)
    files = [("files", (f"{i}.png", fake_png(5, i), "image/png")) for i in range(3)]
    files.append(("files", ("none.png", fake_png(5, 7, flag=1), "image/png")))
    r = admin.post(f"/api/v1/people/{p['id']}/enroll", files=files, data={"consent": "true"})
    assert r.status_code == 200
    body = r.json()
    assert body["accepted"] == 3 and len(body["rejected"]) == 1 and body["enrollment_status"] == "enrolled"
    assert body["rejected"][0] == {"index": 3, "reason": "No face detected", "code": "no_face"}


def test_enrolment_status_progression(admin, fake_engine):
    p = make_person(admin, "S1", "Steps", enroll=False)
    assert admin.get(f"/api/v1/people/{p['id']}/enrollment-status").json()["status"] == "not_enrolled"
    assert enroll_fake(admin, p["id"], 3, n=1).json()["enrollment_status"] == "partial"
    st = admin.get(f"/api/v1/people/{p['id']}/enrollment-status").json()
    assert st["samples"] == 1 and st["required"] == 3
    assert enroll_fake(admin, p["id"], 3, n=2).json()["enrollment_status"] == "enrolled"
    assert admin.post(f"/api/v1/people/{p['id']}/enroll-images",       # upload alternative, same pipeline
                      files=[("files", ("u.png", fake_png(3, 5), "image/png"))],
                      data={"consent": "true"}).json()["total_samples"] == 4


def test_samples_of_a_different_face_in_one_batch_are_rejected(admin, fake_engine):
    p = make_person(admin, "I1", "Mixed Batch", enroll=False)
    files = [("files", (f"{i}.png", fake_png(ident, i), "image/png")) for i, ident in enumerate((4, 4, 4, 9))]
    body = admin.post(f"/api/v1/people/{p['id']}/enroll", files=files, data={"consent": "true"}).json()
    assert body["accepted"] == 3
    assert [r["code"] for r in body["rejected"]] == ["inconsistent_identity"]


def test_possible_duplicate_identity_needs_explicit_confirmation(admin, fake_engine):
    a = make_person(admin, "D1", "Original", identity=2)
    b = make_person(admin, "D2", "Same Face Again", enroll=False)
    r = enroll_fake(admin, b["id"], 2)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "possible_duplicate"
    assert err["details"]["possible_duplicates"][0]["person_code"] == "D1"
    assert admin.get(f"/api/v1/people/{b['id']}").json()["enrolled_samples"] == 0       # nothing saved
    ok = enroll_fake(admin, b["id"], 2, confirm_duplicate="true")
    assert ok.status_code == 200 and ok.json()["total_samples"] == 3
    assert a["id"] != b["id"]


def test_templates_are_encrypted_at_rest_and_never_returned(admin, fake_engine):
    p = make_person(admin, "T1", "Template", identity=6)
    raw = identity_vector(6).tobytes()
    with SessionLocal() as db:
        rows = db.scalars(select(FaceEmbedding).where(FaceEmbedding.person_id == p["id"])).all()
        assert len(rows) == 3
        for row in rows:
            assert row.vector_encrypted != raw and raw not in row.vector_encrypted
            assert len(decrypt_bytes(row.vector_encrypted)) == 512 * 4
    dump = str(admin.get(f"/api/v1/people/{p['id']}").json()) + str(admin.get("/api/v1/people").json())
    assert "vector" not in dump and "embedding" not in dump.replace("enrollment", "")


def test_disabled_person_is_never_marked(admin, fake_engine):
    open_session(admin)
    p = make_person(admin, "X1", "Disabled Dan", identity=7)
    assert admin.put(f"/api/v1/people/{p['id']}", json={"status": "disabled"}).status_code == 200
    r = scan(admin, 7).json()
    assert r["status"] == "person_disabled"
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 0


def test_biometric_deletion_anonymises_and_removes_templates(admin, fake_engine):
    open_session(admin)
    p = make_person(admin, "B1", "Delete Me", identity=8, department="Ops")
    assert scan(admin, 8).json()["status"] == "marked"
    r = admin.delete(f"/api/v1/people/{p['id']}")
    assert r.status_code == 200 and r.json() == {"deleted_templates": 3, "mode": "anonymised"}
    with SessionLocal() as db:
        assert db.scalar(select(func.count(FaceEmbedding.id))) == 0                  # biometric data gone
        person = db.get(Person, p["id"])
        assert person.anonymized and person.full_name.startswith("Deleted person") and person.email is None
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 1                # history kept, no identity
    assert scan(admin, 8).json()["status"] == "unknown"                              # cache refreshed
    assert admin.get("/api/v1/people").json()["total"] == 0                          # hidden from the roster
    log = admin.get("/api/v1/audit-logs?action=person_delete").json()["items"][0]
    assert log["details"]["templates_deleted"] == 3 and "Delete Me" not in str(log)


def test_full_purge_removes_person_and_attendance(admin, fake_engine):
    open_session(admin)
    p = make_person(admin, "B2", "Purge Me", identity=8)
    scan(admin, 8)
    assert admin.delete(f"/api/v1/people/{p['id']}?purge_attendance=true").json()["mode"] == "purged"
    with SessionLocal() as db:
        assert db.get(Person, p["id"]) is None
        assert db.scalar(select(func.count(AttendanceRecord.id))) == 0
        assert db.scalar(select(func.count(FaceEmbedding.id))) == 0


def test_delete_only_biometrics_keeps_account(admin, fake_engine):
    p = make_person(admin, "B3", "Keep Account", identity=8)
    assert admin.delete(f"/api/v1/people/{p['id']}/biometrics").json() == {"deleted_templates": 3}
    got = admin.get(f"/api/v1/people/{p['id']}").json()
    assert got["enrollment_status"] == "not_enrolled" and got["consent_at"] is None and got["status"] == "active"


def test_people_search_filter_and_pagination(admin, fake_engine):
    for i in range(5):
        make_person(admin, f"Z{i}", f"Person {i}", identity=20 + i, department="A" if i < 3 else "B")
    make_person(admin, "N1", "Not Enrolled", enroll=False, department="A")
    assert admin.get("/api/v1/people?q=person 3").json()["total"] == 1
    assert admin.get("/api/v1/people?q=z4").json()["items"][0]["person_code"] == "Z4"
    assert admin.get("/api/v1/people?department=A").json()["total"] == 4
    assert admin.get("/api/v1/people?enrollment=not_enrolled").json()["total"] == 1
    page = admin.get("/api/v1/people?page_size=2&page=3").json()
    assert page["total"] == 6 and page["pages"] == 3 and len(page["items"]) == 2
