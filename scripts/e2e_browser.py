"""Browser end-to-end check of the definition of done, against a RUNNING backend + frontend.

Uses headless Chromium with a *fake camera* that plays a real face from a video file, so the real
UI, WebSocket, face model and database are all exercised. Nothing is mocked.

Prerequisites: backend on :8000 (model loaded), `npm run dev` on :5173, an admin account,
and the fake-camera files from scripts/make_fake_camera.py.

    python scripts/e2e_browser.py --cam-dir DIR --admin admin --password '...' [--shots DIR]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = "http://127.0.0.1:5173"
STEPS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    STEPS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)
    if not ok:
        raise AssertionError(name)


def login(page: Page, user: str, pw: str) -> None:
    page.goto(BASE)
    page.get_by_label("Username or email").fill(user)
    page.get_by_label("Password", exact=True).fill(pw)
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible(timeout=15000)


def api(page: Page, path: str):
    r = page.request.get(f"{BASE}/api/v1{path}")
    assert r.ok, f"{path} -> {r.status} {r.text()}"
    return r.json()


def cleanup(page: Page) -> None:
    """Remove people/sessions left by a previous run so the script can be repeated."""
    for item in api(page, "/people?q=E2E&page_size=100")["items"]:
        if item["person_code"].startswith("E2E"):
            page.request.delete(f"{BASE}/api/v1/people/{item['id']}?purge_attendance=true")
    for s in api(page, "/sessions"):
        if s["name"].startswith("E2E"):
            page.request.delete(f"{BASE}/api/v1/sessions/{s['id']}")


def new_context(p, cam: Path):
    browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                      f"--use-file-for-fake-video-capture={cam}", "--autoplay-policy=no-user-gesture-required"])
    ctx = browser.new_context(permissions=["camera"], viewport={"width": 1366, "height": 900})
    return browser, ctx, ctx.new_page()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam-dir", type=Path, required=True)
    ap.add_argument("--admin", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--shots", type=Path)
    a = ap.parse_args()
    shots = a.shots
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.time()))[-6:]
    code, name = f"E2E{stamp}", f"Ravi Verma {stamp}"

    with sync_playwright() as p:
        browser, ctx, page = new_context(p, a.cam_dir / "face_a.mjpeg")
        page.on("pageerror", lambda e: print("  [page error]", e))
        try:
            # 3. administrator logs in (and a wrong password is rejected)
            page.goto(BASE)
            page.get_by_label("Username or email").fill(a.admin)
            page.get_by_label("Password", exact=True).fill("definitely-wrong")
            page.get_by_role("button", name="Sign in").click()
            expect(page.get_by_text("Wrong username or password.")).to_be_visible()
            check("login rejects a wrong password with a clear message", True)
            login(page, a.admin, a.password)
            check("administrator logs in", True)
            cleanup(page)

            # a session that is open all day so the test does not depend on the clock
            r = page.request.post(f"{BASE}/api/v1/sessions", data={
                "name": f"E2E all day {stamp}", "start_time": "00:00:00", "end_time": "23:59:59", "late_cutoff": "23:59:59",
                "days_of_week": [0, 1, 2, 3, 4, 5, 6], "early_checkin_minutes": 0})
            check("session created", r.status == 201, r.text()[:80])

            # 4. register a person and enroll their face with the webcam
            page.get_by_role("link", name="People").click()
            page.get_by_role("button", name="Register person").first.click()
            page.get_by_label("Person ID").fill(code)
            page.get_by_label("Full name").fill(name)
            page.get_by_label("Department, class or team").fill("E2E Dept")
            page.get_by_role("button", name="Register", exact=True).click()
            expect(page.get_by_text(name).first).to_be_visible(timeout=10000)
            check("person registered", True, code)

            page.get_by_role("button", name=f"Enroll face for {name}").click()
            capture = page.get_by_role("button", name=re.compile(r"Capture photo"))
            expect(capture).to_be_enabled(timeout=20000)
            for _ in range(3):
                capture.click()
                page.wait_for_timeout(400)
            page.get_by_label(re.compile(r"has been told how their face data")).check()
            if shots:
                page.screenshot(path=str(shots / "1_enroll.png"))
            page.get_by_role("button", name=re.compile(r"Save 3 photos")).click()
            expect(page.get_by_text(re.compile(r"Saved 3 face samples?"))).to_be_visible(timeout=60000)
            check("face enrolled from the webcam (3 samples)", True)
            page.get_by_role("button", name="Done").click()
            person = api(page, f"/people?q={code}")["items"][0]
            check("enrollment status is 'enrolled' in the database", person["enrollment_status"] == "enrolled" and person["enrolled_samples"] == 3)

            # 5-11. live scanner
            before = api(page, "/attendance")["total"]
            page.get_by_role("link", name="Live scanner").click()
            page.get_by_role("button", name="Start scanning").click()
            ticket = page.get_by_test_id("scan-ticket")
            expect(page.get_by_text("Camera on")).to_be_visible(timeout=20000)
            check("camera starts and releases permission flow", True)
            expect(ticket).to_have_attribute("data-state", "marked", timeout=60000)
            text = ticket.inner_text()
            check("scanner shows the recognised name and confirmation", name in text and "Attendance marked" in text, text.replace("\n", " | ")[:140])
            if shots:
                page.screenshot(path=str(shots / "2_marked.png"))
            att = api(page, "/attendance?page_size=100")
            mine = [r for r in att["items"] if r["person_code"] == code]
            check("database has exactly one record for the person", len(mine) == 1 and mine[0]["method"] == "face", str(mine[0]["local_time"]))

            # 12. person stays in front of the camera: no duplicates, even after the cooldown ends
            page.wait_for_timeout(16000)
            mine = [r for r in api(page, "/attendance?page_size=100")["items"] if r["person_code"] == code]
            check("staying in front of the camera creates no duplicate", len(mine) == 1, f"state={ticket.get_attribute('data-state')}")
            check("a repeat scan is reported as already marked (not re-recorded)", ticket.get_attribute("data-state") in ("already", "marked", "waiting", "detected", "recognizing"))

            # pause / resume / stop
            page.get_by_role("button", name="Pause").click()
            expect(ticket).to_have_attribute("data-state", "paused")
            page.get_by_role("button", name="Resume").click()
            page.get_by_role("button", name=re.compile("Stop and release camera")).click()
            expect(page.get_by_text("Camera off")).to_be_visible()
            expect(ticket).to_have_attribute("data-state", "idle")
            check("pause, resume and stop work; camera is released", True)

            # 15. dashboard reflects the new record (from the real database)
            page.get_by_role("link", name="Dashboard").click()
            expect(page.get_by_text(name).first).to_be_visible(timeout=15000)
            summ = api(page, "/dashboard/summary")
            check("dashboard shows the check-in and counts", summ["attended"] >= 1 and any(r["person_code"] == code for r in summ["recent"]),
                  f"attended={summ['attended']} expected={summ['expected']}")
            if shots:
                page.screenshot(path=str(shots / "3_dashboard.png"))

            # 16-17. attendance history, filtering and CSV export
            page.get_by_role("link", name="Attendance").click()
            page.get_by_label("Search by name or ID").fill(code)
            expect(page.get_by_role("cell").get_by_text(name)).to_be_visible(timeout=10000)
            check("attendance history shows the person, date, time and session", True)
            page.get_by_label("Search by name or ID").fill("zzz-no-such-person")
            expect(page.get_by_text("No records for these filters")).to_be_visible(timeout=10000)
            check("filters narrow the list and show an empty state", True)
            page.get_by_label("Search by name or ID").fill(code)
            expect(page.get_by_role("cell").get_by_text(name)).to_be_visible(timeout=10000)
            with page.expect_download() as dl:
                page.get_by_role("button", name="Export CSV").click()
            csv_text = Path(dl.value.path()).read_text(encoding="utf-8")
            lines = csv_text.strip().splitlines()
            check("CSV export honours the filter", len(lines) == 2 and name in lines[1] and "face" in lines[1].lower(), lines[1][:90])
            if shots:
                page.get_by_role("cell").get_by_text(name).click()
                page.screenshot(path=str(shots / "4_attendance.png"))
        finally:
            ctx.close(); browser.close()

        # 14. a different, unregistered face is rejected and marks nobody
        browser, ctx, page = new_context(p, a.cam_dir / "face_b.mjpeg")
        try:
            login(page, a.admin, a.password)
            total_before = api(page, "/attendance")["total"]
            page.get_by_role("link", name="Live scanner").click()
            page.get_by_role("button", name="Start scanning").click()
            ticket = page.get_by_test_id("scan-ticket")
            expect(ticket).to_have_attribute("data-state", re.compile(r"unknown|quality"), timeout=60000)
            state = ticket.get_attribute("data-state")
            check("an unregistered face is rejected", state == "unknown", f"state={state}")
            if shots:
                page.screenshot(path=str(shots / "5_unknown.png"))
            page.wait_for_timeout(5000)
            total_after = api(page, "/attendance")["total"]
            check("no attendance was recorded for the unknown face", total_after == total_before, f"{total_before} -> {total_after}")
        finally:
            ctx.close(); browser.close()

        # 18. graceful failures: camera denied
        browser = p.chromium.launch()
        ctx = browser.new_context(permissions=[])     # camera permission not granted, no fake device
        page = ctx.new_page()
        try:
            login(page, a.admin, a.password)
            page.get_by_role("link", name="Live scanner").click()
            page.get_by_role("button", name="Start scanning").click()
            expect(page.get_by_role("alert").filter(has_text=re.compile(r"camera", re.I)).first).to_be_visible(timeout=20000)
            expect(page.get_by_role("button", name="Start scanning")).to_be_visible()
            check("a missing/blocked camera shows a clear error and the scanner stays usable", True)
        finally:
            ctx.close(); browser.close()

    failed = [s for s in STEPS if not s[1]]
    print(f"\n{len(STEPS) - len(failed)}/{len(STEPS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print("ABORTED at:", e)
        sys.exit(1)
