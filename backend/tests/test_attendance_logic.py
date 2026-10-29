"""Attendance rules (spec cases 7-13, 18). Recognition is MOCKED (FakeEngine); the database,
transactions, constraints and threads are real."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.database.base import SessionLocal
from app.main import app
from app.models import (
    AttendanceRecord, AttendanceSession, AttendanceStatus, Department, Method, Person, PersonStatus,
)
from app.services import attendance_service as att
from app.services.face_detection import ModelUnavailableError
from app.services.face_recognition import EngineInfo, set_engine
from app.services.recognition_service import ScannerState, recognize_frame
from tests.conftest import ADMIN, fake_png, make_person, open_session, scan


def count_records() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count(AttendanceRecord.id))) or 0


# ---- recognition -> attendance ---------------------------------------------------------------
def test_successful_recognition_creates_one_record(admin, fake_engine):
    open_session(admin, "Morning")
    p = make_person(admin, "E1", "Rahul Sharma", identity=1)
    r = scan(admin, 1).json()
    assert r["status"] == "marked"
    assert r["person"]["full_name"] == "Rahul Sharma" and r["person"]["person_code"] == "E1"
    assert r["message"].startswith("Welcome, Rahul Sharma. Attendance recorded at ")
    assert r["attendance"]["session"] == "Morning" and r["attendance"]["method"] == "face"
    assert r["similarity"] > 0.9 and "timings" in r
    with SessionLocal() as db:
        rec = db.scalars(select(AttendanceRecord)).one()
        assert rec.person_id == p["id"] and rec.method == Method.face and rec.status == AttendanceStatus.present
        assert rec.marked_at.tzinfo is not None and rec.decision_meta["liveness"] == "off"
        assert rec.decision_meta["model"] == "fake-test-model"


def test_repeated_recognition_does_not_duplicate(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    assert scan(admin, 1, variant=1).json()["status"] == "marked"
    again = scan(admin, 1, variant=2).json()
    assert again["status"] == "already_marked" and again["message"] == "Your attendance has already been recorded."
    assert again["attendance"]["marked_at"]                                      # shows the original timestamp
    assert count_records() == 1


def test_unknown_face_is_rejected_and_never_assigned_to_closest_person(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    make_person(admin, "E2", "Bob Roy", identity=2)
    r = scan(admin, 99).json()
    assert r["status"] == "unknown" and "person" not in r and r["message"].startswith("Person not recognized")
    assert count_records() == 0


def test_ambiguous_match_between_two_people_is_refused(admin, fake_engine):
    open_session(admin)
    make_person(admin, "A1", "Twin One", identity=3)
    b = make_person(admin, "A2", "Twin Two", enroll=False)
    from tests.conftest import enroll_fake
    assert enroll_fake(admin, b["id"], 3, confirm_duplicate="true").status_code == 200
    r = scan(admin, 3).json()
    assert r["status"] == "unknown" and r["reason"] == "ambiguous"
    assert count_records() == 0


@pytest.mark.parametrize("flag,status", [(1, "no_face"), (2, "multiple_faces"), (3, "poor_quality")])
def test_unusable_frames_never_create_attendance(admin, fake_engine, flag, status):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    assert scan(admin, 1, flag=flag).json()["status"] == status
    assert count_records() == 0


def test_corrupt_frame_is_reported_not_crashing(admin, fake_engine):
    r = admin.post("/api/v1/recognition/recognize", files={"file": ("f.png", b"garbage", "image/png")})
    assert r.status_code == 200 and r.json()["status"] == "bad_image"
    big = admin.post("/api/v1/recognition/recognize", files={"file": ("f.png", b"\x89PNG" + b"0" * 3_000_000, "image/png")})
    assert big.status_code == 413


def test_no_open_session_means_no_attendance(admin, fake_engine):
    make_person(admin, "E1", "Ann Lee", identity=1)
    assert scan(admin, 1).json()["status"] == "no_active_session"        # no sessions configured at all
    open_session(admin, "Weekend only", days_of_week=[(date.today().weekday() + 1) % 7])
    assert scan(admin, 1).json()["status"] == "no_active_session"        # not today
    open_session(admin, "Other dept", department="Finance")
    assert scan(admin, 1).json()["status"] == "no_active_session"        # restricted to another department
    assert count_records() == 0


def test_department_restricted_session_applies_to_that_department(admin, fake_engine):
    open_session(admin, "Eng only", department="Engineering")
    make_person(admin, "E1", "Ann Lee", identity=1, department="Engineering")
    make_person(admin, "F1", "Bob Roy", identity=2, department="Finance")
    assert scan(admin, 1).json()["status"] == "marked"
    assert scan(admin, 2).json()["status"] == "no_active_session"


def test_model_failure_gives_clear_error(admin):
    class Broken:
        is_loaded = False
        info = EngineInfo(False, "buffalo_l", [], [], 0, "Model directory not found: X")
        def require(self):
            raise ModelUnavailableError("Model directory not found: X. Download the model pack ...")
        detect = embed = require
    set_engine(Broken())     # type: ignore[arg-type]
    try:
        r = scan(admin, 1)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "model_unavailable" and "Model directory not found" in r.json()["error"]["message"]
        st = admin.get("/api/v1/recognition/status").json()
        assert st["model_loaded"] is False and "Model directory" in st["model_error"]
        person = make_person(admin, "BR1", "Broken Model", enroll=False)
        r = admin.post(f"/api/v1/people/{person['id']}/enroll-images",
                       files=[("files", ("a.png", fake_png(1), "image/png"))], data={"consent": "true"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"
        assert "Traceback" not in r.text                         # no stack trace leaked to clients
    finally:
        set_engine(None)


def test_scanner_cooldown_stops_reprocessing_after_a_result(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    calls = {"n": 0}
    real_detect = fake_engine.detect
    fake_engine.detect = lambda img: (calls.__setitem__("n", calls["n"] + 1), real_detect(img))[1]
    state = ScannerState()
    with SessionLocal() as db:
        assert recognize_frame(db, fake_png(1, 3), state)["status"] == "marked"
        assert calls["n"] == 1
        for _ in range(5):                                       # the person is still standing there
            assert recognize_frame(db, fake_png(1, 3), state)["status"] == "cooldown"
        assert calls["n"] == 1                                   # no inference was run
        state.reset()
        assert recognize_frame(db, fake_png(1, 3), state)["status"] == "already_marked"
    assert count_records() == 1


# ---- race safety -------------------------------------------------------------------------------
def test_database_enforces_one_record_per_person_session_date(admin, fake_engine):
    s = open_session(admin)
    p = make_person(admin, "E1", "Ann Lee", identity=1)
    with SessionLocal() as db:
        for _ in range(2):
            db.add(AttendanceRecord(person_id=p["id"], session_id=s["id"], session_date=date(2030, 1, 1),
                                    status=AttendanceStatus.present, method=Method.manual))
            if _ == 0:
                db.commit()
        with pytest.raises(IntegrityError):
            db.commit()


def test_simultaneous_service_calls_create_exactly_one_record(admin, fake_engine):
    s = open_session(admin)
    p = make_person(admin, "E1", "Ann Lee", identity=1)
    n = 8      # stays below the connection pool size (5 + 10 overflow): each worker holds a connection
    barrier = threading.Barrier(n, timeout=30)

    def worker(_: int) -> bool:
        with SessionLocal() as db:
            person = db.get(Person, p["id"])
            session = db.get(AttendanceSession, s["id"])
            barrier.wait()
            return att.mark_face_attendance(db, person, session, date.today(), "UTC", 0.9, None).created

    with ThreadPoolExecutor(n) as pool:
        created = list(pool.map(worker, range(n)))
    assert created.count(True) == 1 and created.count(False) == n - 1
    assert count_records() == 1


def test_simultaneous_api_requests_create_exactly_one_record(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    n = 6
    clients = []
    for _ in range(n):
        c = TestClient(app)
        assert c.post("/api/v1/auth/login", json={"username": ADMIN[0], "password": ADMIN[1]}).status_code == 200
        clients.append(c)
    barrier = threading.Barrier(n, timeout=30)

    def worker(i: int) -> str:
        barrier.wait()
        return scan(clients[i], 1, variant=i + 1).json()["status"]

    with ThreadPoolExecutor(n) as pool:
        statuses = list(pool.map(worker, range(n)))
    assert statuses.count("marked") == 1 and statuses.count("already_marked") == n - 1
    assert count_records() == 1


# ---- sessions, timezone, late ---------------------------------------------------------------------
def _session(db, name="S", start=(9, 0), end=(12, 0), late=(9, 15), days="0,1,2,3,4", early=15, dept=None,
             created=datetime(2026, 1, 1, tzinfo=timezone.utc)) -> AttendanceSession:
    s = AttendanceSession(name=name, start_time=time(*start), end_time=time(*end), late_cutoff=time(*late) if late else None,
                          days_of_week=days, early_checkin_minutes=early, department_id=dept, created_at=created)
    db.add(s)
    db.commit()
    return s


def _person(db, code="P1", name="Pat", dept=None, registered=datetime(2026, 1, 1, tzinfo=timezone.utc),
            status=PersonStatus.active) -> Person:
    p = Person(person_code=code, full_name=name, department_id=dept, registered_at=registered, status=status)
    db.add(p)
    db.commit()
    return p


MON = date(2026, 3, 2)   # a Monday


def utc(h, m=0, d=2, month=3):
    return datetime(2026, month, d, h, m, tzinfo=timezone.utc)


def test_attendance_is_scoped_to_the_session_occurrence(admin):
    with SessionLocal() as db:
        morning = _session(db, "Morning", (9, 0), (12, 0), (9, 15))
        evening = _session(db, "Evening", (14, 0), (17, 0), (14, 15))
        p = _person(db)
        r1 = att.resolve_open_session(db, p, "UTC", utc(10))
        assert r1 and r1[0].id == morning.id and r1[1] == MON
        assert att.resolve_open_session(db, p, "UTC", utc(13)) is None                    # between sessions
        r2 = att.resolve_open_session(db, p, "UTC", utc(15))
        assert r2 and r2[0].id == evening.id
        assert att.resolve_open_session(db, p, "UTC", utc(10, d=7)) is None               # Saturday
        a = att.mark_face_attendance(db, p, morning, MON, "UTC", .9, None, utc(10))
        b = att.mark_face_attendance(db, p, evening, MON, "UTC", .9, None, utc(15))       # different session: allowed
        c = att.mark_face_attendance(db, p, morning, MON, "UTC", .9, None, utc(11))       # same session: not
        nxt = att.mark_face_attendance(db, p, morning, date(2026, 3, 3), "UTC", .9, None, utc(10, d=3))
        assert (a.created, b.created, c.created, nxt.created) == (True, True, False, True)
        assert c.record.id == a.record.id


def test_early_checkin_window_and_timezone(admin):
    with SessionLocal() as db:
        s = _session(db, "IST morning", (9, 0), (17, 0), (9, 30), early=15)
        p = _person(db)
        # 09:00 IST == 03:30 UTC
        assert att.resolve_open_session(db, p, "Asia/Kolkata", utc(3, 10)) is None          # 08:40 IST: too early
        assert att.resolve_open_session(db, p, "Asia/Kolkata", utc(3, 20)) is not None      # 08:50 IST: within 15 min
        assert att.resolve_open_session(db, p, "Asia/Kolkata", utc(11, 29)) is not None     # 16:59 IST
        assert att.resolve_open_session(db, p, "Asia/Kolkata", utc(11, 31)) is None         # 17:01 IST: closed
        # the SAME instant is "today" in IST but still the previous weekday in a far-west zone
        assert att.resolve_open_session(db, p, "UTC", utc(3, 40)) is None                   # 03:40 UTC: before 09:00 UTC


def test_late_arrival_rules(admin):
    with SessionLocal() as db:
        s = _session(db, "Late rule", (9, 0), (12, 0), (9, 15))
        assert att.status_for_time(s, time(9, 0)) == AttendanceStatus.present
        assert att.status_for_time(s, time(9, 15)) == AttendanceStatus.present               # cut-off itself is on time
        assert att.status_for_time(s, time(9, 15, 1)) == AttendanceStatus.late
        assert att.status_for_time(s, time(11, 59)) == AttendanceStatus.late
        s.late_cutoff = None
        assert att.status_for_time(s, time(11, 59)) == AttendanceStatus.present              # no cut-off => never late
        p = _person(db)
        s.late_cutoff = time(9, 15)
        on_time = att.mark_face_attendance(db, p, s, MON, "UTC", .9, None, utc(9, 10)).record
        p2 = _person(db, "P2", "Quinn")
        late = att.mark_face_attendance(db, p2, s, MON, "UTC", .9, None, utc(9, 20)).record
        assert on_time.status == AttendanceStatus.present and late.status == AttendanceStatus.late


def test_late_status_via_api(admin, fake_engine):
    open_session(admin, "Always late", late_cutoff="00:00:00")
    make_person(admin, "E1", "Ann Lee", identity=1)
    assert scan(admin, 1).json()["attendance"]["status"] == "late"


def test_server_clock_is_authoritative(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    before = datetime.now(timezone.utc)
    scan(admin, 1)
    with SessionLocal() as db:
        rec = db.scalars(select(AttendanceRecord)).one()
        assert before <= rec.marked_at <= datetime.now(timezone.utc)


# ---- absences ------------------------------------------------------------------------------------
def test_absent_is_computed_only_after_the_session_has_ended(admin):
    with SessionLocal() as db:
        s = _session(db, "Day", (9, 0), (17, 0), (9, 15))
        a, b = _person(db, "A", "Alice"), _person(db, "B", "Bob")
        _person(db, "C", "Carol", status=PersonStatus.disabled)                          # inactive: not expected
        _person(db, "D", "Dave", registered=datetime(2026, 3, 2, 18, 0, tzinfo=timezone.utc))  # joined after it ended
        att.mark_face_attendance(db, a, s, MON, "UTC", .9, None, utc(9, 5))
        during = att.build_rows(db, MON, MON, "UTC", now=utc(12))
        assert [r.status for r in during] == [AttendanceStatus.present]                   # nobody absent yet
        after = att.build_rows(db, MON, MON, "UTC", now=utc(17, 1))
        by = {r.person.full_name: r.status for r in after}
        assert by == {"Alice": AttendanceStatus.present, "Bob": AttendanceStatus.absent}
        assert [r for r in after if r.status == AttendanceStatus.absent][0].record is None
        weekend = att.build_rows(db, date(2026, 3, 7), date(2026, 3, 8), "UTC", now=utc(23, d=9))
        assert weekend == []                                                              # session does not run
        before_created = att.build_rows(db, date(2025, 12, 1), date(2025, 12, 1), "UTC", now=utc(23, d=9))
        assert before_created == []                                                       # before the session existed


# ---- manual entries and corrections ---------------------------------------------------------------
def test_manual_entry_is_labelled_and_duplicates_rejected(admin, fake_engine):
    s = open_session(admin)
    p = make_person(admin, "M1", "Manual Mia", identity=1)
    body = {"person_id": p["id"], "session_id": s["id"], "session_date": "2026-01-05", "status": "present",
            "note": "Forgot badge, verified by supervisor"}
    r = admin.post("/api/v1/attendance/manual", json=body)
    assert r.status_code == 201 and r.json()["method"] == "manual" and r.json()["similarity"] is None
    assert admin.post("/api/v1/attendance/manual", json=body).status_code == 409
    assert admin.post("/api/v1/attendance/manual", json={**body, "note": "x"}).status_code == 422     # reason required
    assert admin.post("/api/v1/attendance/manual", json={**body, "status": "absent", "session_date": "2026-01-06"}
                      ).status_code == 400
    assert admin.post("/api/v1/attendance/manual", json={**body, "session_date": "2999-01-01"}).status_code == 400


def test_correction_keeps_audit_trail(admin, fake_engine):
    open_session(admin, late_cutoff="00:00:00")
    make_person(admin, "E1", "Ann Lee", identity=1)
    rec = scan(admin, 1).json()["attendance"]
    r = admin.put(f"/api/v1/attendance/{rec['id']}", json={"status": "corrected", "note": "Bus was delayed"})
    assert r.status_code == 200 and r.json()["status"] == "corrected" and r.json()["corrected"] is True
    assert admin.put(f"/api/v1/attendance/{rec['id']}", json={"status": "absent", "note": "nope nope"}).status_code == 400
    assert admin.put(f"/api/v1/attendance/{rec['id']}", json={"status": "present", "note": ""}).status_code == 422
    with SessionLocal() as db:
        row = db.scalars(select(AttendanceRecord)).one()
        assert row.original_status == "late" and row.corrected_by and row.corrected_at and row.method == Method.face
    actions = [i["action"] for i in admin.get("/api/v1/audit-logs").json()["items"]]
    assert "attendance_correct" in actions
