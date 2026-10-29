"""Filters, CSV export, dashboard and reports (spec cases 15, 16, 17). MOCKED recognition; real DB."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timezone

from sqlalchemy import func, select

from app.database.base import SessionLocal
from app.models import AttendanceRecord, AttendanceStatus, Person
from tests.conftest import make_person, open_session, scan
from tests.test_attendance_logic import _person, _session


def manual(client, person, session, day, status="present", note="entered by supervisor"):
    r = client.post("/api/v1/attendance/manual", json={"person_id": person["id"], "session_id": session["id"],
                                                       "session_date": day, "status": status, "note": note})
    assert r.status_code == 201, r.text
    return r.json()


def seeded(admin, fake_engine):
    s1, s2 = open_session(admin, "Morning"), open_session(admin, "Evening")
    ann = make_person(admin, "E1", "Ann Lee", identity=1, department="Engineering")
    bob = make_person(admin, "E2", "Bob Roy", identity=2, department="Engineering")
    cy = make_person(admin, "F1", "Cy Dunn", identity=3, department="Finance")
    manual(admin, ann, s1, "2026-01-05", "present")
    manual(admin, ann, s1, "2026-01-06", "late")
    manual(admin, bob, s1, "2026-01-05", "corrected")
    manual(admin, cy, s2, "2026-01-05", "present")
    manual(admin, cy, s2, "2026-01-12", "present")
    return s1, s2, ann, bob, cy


def listing(client, **params):
    q = {"date_from": "2026-01-01", "date_to": "2026-01-31", **params}
    r = client.get("/api/v1/attendance", params=q)
    assert r.status_code == 200, r.text
    return r.json()


def test_attendance_filters_return_the_right_rows(admin, fake_engine):
    s1, s2, ann, bob, cy = seeded(admin, fake_engine)
    assert listing(admin)["total"] == 5
    assert listing(admin, q="ann")["total"] == 2
    assert {i["person_code"] for i in listing(admin, q="F1")["items"]} == {"F1"}
    assert listing(admin, department="Finance")["total"] == 2
    assert listing(admin, department="Nowhere")["total"] == 0
    assert listing(admin, session_id=s1["id"])["total"] == 3
    assert [i["status"] for i in listing(admin, status="late")["items"]] == ["late"]
    assert listing(admin, status="corrected")["items"][0]["person_name"] == "Bob Roy"
    assert listing(admin, date_from="2026-01-06")["total"] == 2
    assert listing(admin, date_to="2026-01-05")["total"] == 3
    only = listing(admin, q="ann", status="late", session_id=s1["id"], department="Engineering",
                   date_from="2026-01-06", date_to="2026-01-06")
    assert only["total"] == 1 and only["items"][0]["session_date"] == "2026-01-06"


def test_sorting_and_pagination(admin, fake_engine):
    seeded(admin, fake_engine)
    by_name = listing(admin, sort="name", order="asc")["items"]
    assert [i["person_name"] for i in by_name] == ["Ann Lee", "Ann Lee", "Bob Roy", "Cy Dunn", "Cy Dunn"]
    newest = listing(admin, sort="date", order="desc")["items"][0]
    assert newest["session_date"] == "2026-01-12"
    p3 = listing(admin, page_size=2, page=3)
    assert p3["total"] == 5 and p3["pages"] == 3 and len(p3["items"]) == 1
    ids = [i["id"] for pg in (1, 2, 3) for i in listing(admin, page_size=2, page=pg)["items"]]
    assert len(ids) == len(set(ids)) == 5                                  # pages do not overlap


def test_invalid_ranges_are_rejected(admin, fake_engine):
    assert admin.get("/api/v1/attendance?date_from=2026-02-01&date_to=2026-01-01").status_code == 422
    assert admin.get("/api/v1/attendance?date_from=2025-01-01&date_to=2026-01-01").status_code == 422
    assert admin.get("/api/v1/attendance?status=banana").status_code == 422
    assert admin.get("/api/v1/attendance?page=0").status_code == 422


def test_computed_absences_appear_in_listing_and_person_history(admin):
    with SessionLocal() as db:
        s = _session(db, "Day", (9, 0), (17, 0), (9, 15))
        a, b = _person(db, "A", "Alice"), _person(db, "B", "Bob")
        db.add(AttendanceRecord(person_id=a.id, session_id=s.id, session_date=date(2026, 3, 2),
                                marked_at=datetime(2026, 3, 2, 9, 5, tzinfo=timezone.utc),
                                status=AttendanceStatus.present, method="manual"))
        db.commit()
        bob_id = b.id
    r = admin.get("/api/v1/attendance", params={"date_from": "2026-03-02", "date_to": "2026-03-02", "status": "absent"}).json()
    assert r["total"] == 1 and r["items"][0]["person_name"] == "Bob" and r["items"][0]["is_computed"] is True
    assert r["items"][0]["id"] is None and r["items"][0]["marked_at"] is None
    hist = admin.get(f"/api/v1/attendance/person/{bob_id}", params={"date_from": "2026-03-02", "date_to": "2026-03-02"}).json()
    assert hist["summary"]["absent"] == 1 and hist["attendance_percentage"] == 0.0


def test_csv_export_respects_filters_and_permissions(admin, operator, viewer, fake_engine):
    seeded(admin, fake_engine)
    r = admin.get("/api/v1/reports/export", params={"date_from": "2026-01-01", "date_to": "2026-01-31",
                                                    "department": "Finance"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:4] == ["Date", "Time", "Person ID", "Name"] and len(rows) == 3         # header + 2 Finance rows
    assert {row[3] for row in rows[1:]} == {"Cy Dunn"} and {row[7] for row in rows[1:]} == {"manual"}
    full = admin.get("/api/v1/reports/export", params={"date_from": "2026-01-01", "date_to": "2026-01-31"})
    assert len(list(csv.reader(io.StringIO(full.text)))) == 6
    late = admin.get("/api/v1/reports/export", params={"date_from": "2026-01-01", "date_to": "2026-01-31", "status": "late"})
    assert len(list(csv.reader(io.StringIO(late.text)))) == 2
    assert operator.get("/api/v1/reports/export").status_code == 200
    assert viewer.get("/api/v1/reports/export").status_code == 403
    assert "attendance_export" in [i["action"] for i in admin.get("/api/v1/audit-logs").json()["items"]]


def test_csv_neutralises_formula_injection(admin, fake_engine):
    s = open_session(admin)
    evil = make_person(admin, "EV1", "=HYPERLINK(\"http://evil\",\"x\")", identity=4)
    manual(admin, evil, s, "2026-01-05")
    text = admin.get("/api/v1/reports/export", params={"date_from": "2026-01-01", "date_to": "2026-01-31"}).text
    row = list(csv.reader(io.StringIO(text)))[1]
    assert row[3].startswith("'=")


def test_dashboard_summary_matches_the_database(admin, fake_engine):
    s = open_session(admin, "All day", late_cutoff="23:59:59")
    ann = make_person(admin, "E1", "Ann Lee", identity=1, department="Engineering")
    bob = make_person(admin, "E2", "Bob Roy", identity=2, department="Engineering")
    make_person(admin, "F1", "Cy Dunn", identity=3, department="Finance")
    make_person(admin, "F2", "Di Fox", identity=4, department="Finance")
    assert scan(admin, 1).json()["status"] == "marked"
    today = date.today().isoformat()
    manual(admin, bob, s, today, "late", "arrived after cut-off")
    d = admin.get("/api/v1/dashboard/summary").json()
    with SessionLocal() as db:
        n_people = db.scalar(select(func.count(Person.id)))
        n_present = db.scalar(select(func.count(AttendanceRecord.id)).where(AttendanceRecord.status == AttendanceStatus.present))
        n_late = db.scalar(select(func.count(AttendanceRecord.id)).where(AttendanceRecord.status == AttendanceStatus.late))
    assert d["total_people"] == n_people == 4
    assert d["present"] == n_present == 1 and d["late"] == n_late == 1
    assert d["expected"] == 4 and d["attended"] == 2
    assert d["absent"] == 0 and d["pending"] == 2                     # nobody is "absent" before the session ends
    assert d["attendance_percentage"] == 50.0
    eng = next(x for x in d["departments"] if x["department"] == "Engineering")
    assert (eng["present"], eng["late"], eng["absent"]) == (1, 1, 0)
    assert {r["person_name"] for r in d["recent"]} == {"Ann Lee", "Bob Roy"}
    assert d["recent"][0]["marked_at"] >= d["recent"][1]["marked_at"]


def test_dashboard_is_empty_not_fake_without_data(admin):
    d = admin.get("/api/v1/dashboard/summary").json()
    assert d["total_people"] == 0 and d["present"] == d["late"] == d["absent"] == 0
    assert d["attendance_percentage"] is None and d["recent"] == []
    t = admin.get("/api/v1/dashboard/trends?days=5").json()
    assert len(t) == 5 and all(x["expected"] == 0 and x["attendance_percentage"] is None for x in t)


def test_trends_reflect_todays_records(admin, fake_engine):
    open_session(admin)
    make_person(admin, "E1", "Ann Lee", identity=1)
    scan(admin, 1)
    t = admin.get("/api/v1/dashboard/trends?days=3").json()
    assert len(t) == 3 and t[-1]["date"] == date.today().isoformat() and t[-1]["present"] == 1
    assert admin.get("/api/v1/dashboard/trends?days=1").status_code == 422


def test_reports_group_by_period(admin, fake_engine):
    seeded(admin, fake_engine)
    q = {"date_from": "2026-01-01", "date_to": "2026-01-31"}
    month = admin.get("/api/v1/reports/attendance", params={**q, "group_by": "month"}).json()
    assert [s["period"] for s in month["series"]] == ["2026-01"]
    assert (month["totals"]["present"], month["totals"]["late"]) == (4, 1)
    week = admin.get("/api/v1/reports/attendance", params={**q, "group_by": "week"}).json()
    assert [s["period"] for s in week["series"]] == ["2025-12-29", "2026-01-12"] or \
           [s["period"] for s in week["series"]] == ["2026-01-05", "2026-01-12"]
    day = admin.get("/api/v1/reports/attendance", params={**q, "group_by": "day"}).json()
    assert [s["period"] for s in day["series"]] == ["2026-01-05", "2026-01-06", "2026-01-12"]
    assert day["series"][0]["present"] == 3                                                # Ann, Bob(corrected), Cy
    names = {p["full_name"]: p for p in day["people"]}
    assert names["Ann Lee"]["attendance_percentage"] == 100.0 and names["Ann Lee"]["late"] == 1
    assert {d["department"] for d in day["departments"]} == {"Engineering", "Finance"}
    assert admin.get("/api/v1/reports/attendance", params={**q, "group_by": "year"}).status_code == 422


def test_reports_with_no_data_return_empty_series(admin):
    r = admin.get("/api/v1/reports/attendance", params={"date_from": "2026-01-01", "date_to": "2026-01-31"}).json()
    assert r["series"] == [] and r["people"] == [] and r["totals"]["attendance_percentage"] is None
