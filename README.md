# Rollcall - AI-powered face recognition attendance

A working attendance system: register people, enroll their faces, and anyone who steps up to a webcam is
recognized by a real face-recognition model and recorded - exactly once per session - in a database.

- **Frontend:** React 19, Vite, TypeScript, Tailwind CSS 4, Lucide, Axios, React Router, Recharts
- **Backend:** Python, FastAPI, Uvicorn, Pydantic, SQLAlchemy 2, Alembic, OpenCV, NumPy, ONNX Runtime
- **Recognition:** InsightFace `buffalo_l` (SCRFD detector + ArcFace ResNet-50, 512-d embeddings), CPU by default
- **Database:** SQLite for local use; the schema is PostgreSQL-compatible

> **Read first:** face recognition is probabilistic, the liveness check is experimental, and the pretrained model
> is licensed for **non-commercial research**. See [Known limitations](#known-limitations) and
> [docs/SECURITY_PRIVACY.md](docs/SECURITY_PRIVACY.md) before using this with real people.

## Contents
[Features](#features) · [Architecture](#architecture) · [Quick start (Windows)](#quick-start-windows) · [Manual setup](#manual-setup) ·
[Configuration](#configuration) · [Face model setup and licence](#face-recognition-model-setup-and-licence) ·
[Using the app](#using-the-app) · [API](#api-documentation) · [Testing](#testing) · [Backup and restore](#backup-and-restore) ·
[Troubleshooting](#troubleshooting) · [Security](#security-considerations) · [Known limitations](#known-limitations) · [Future work](#future-improvements)

## Features

| Area | What is implemented |
|---|---|
| Registration | Name, unique ID, email, department/class, role, status. Duplicate IDs/emails rejected. Webcam capture **or** photo upload, quality checks, consent recorded, duplicate-identity warning that needs explicit confirmation. |
| Recognition | Browser sends throttled JPEG frames over a WebSocket; the server detects, quality-checks, aligns, embeds and matches. Unknown faces are never assigned to the "closest" person; ambiguous matches (two people almost equally similar) are refused. |
| Attendance | One record per person per session occurrence, enforced by a **database unique constraint** and safe under concurrent requests. Server clock, configurable timezone, late cut-off, absent computed only after a session ends, manual entries clearly labelled, audited corrections. |
| Liveness | Optional experimental random head-turn challenge (kept separate from identity). **Not** strong anti-spoofing - see limitations. |
| Dashboard / reports | Today's counts, 14-day trend, department breakdown, recent check-ins; daily/weekly/monthly reports, per-person %, department comparison, late and absence trends. All numbers come from the database. |
| Admin | Sessions, validated settings, users and roles (admin / operator / viewer), audit log, retention, CSV export (formula-injection safe), biometric deletion. |
| Security | bcrypt passwords, httpOnly cookie sessions, role-based access, login rate limiting, origin checks, encrypted face templates, no stored photos, security headers. |

## Architecture

```
 Browser (React)                                   FastAPI (one process)
 ┌──────────────────┐   REST /api/v1 (cookie)   ┌──────────────────────────────────────────┐
 │ Pages, Recharts  │ ────────────────────────▶ │ routers → services → SQLAlchemy → SQLite  │
 │                  │                           │                                          │
 │ Scanner:         │   WebSocket /recognition  │ recognition_service (worker thread)      │
 │  getUserMedia →  │ ── JPEG frame (≤1 in      │  decode → SCRFD detect → quality gate →  │
 │  canvas → JPEG   │    flight, ~0.7 s) ─────▶ │  align → ArcFace embed → [liveness] →    │
 │                  │ ◀── JSON result ───────── │  match (in-memory gallery) → session →   │
 └──────────────────┘                           │  attendance_service (INSERT, unique key) │
                                                └──────────────────────────────────────────┘
```
Details, data model and sequence: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Why InsightFace buffalo_l?** Best accuracy-for-effort among the options evaluated: SCRFD + ArcFace R50 are
state-of-the-art-class models, run on CPU through ONNX Runtime with only `onnxruntime`, `opencv` and `numpy` needed at run
time, install from prebuilt wheels on Windows (no compiler), and are small enough for a laptop (~280 MB on disk).
Alternatives considered: FaceNet (`facenet-pytorch`) needs PyTorch (~2 GB) and has lower accuracy; `dlib`/`face_recognition` needs a C++
toolchain on Windows and a 128-d model that is less accurate. **Licence caveat:** see below.

## Quick start (Windows)

Prerequisites: Windows 10/11, **Python 3.10-3.13** (tick "Add python.exe to PATH"), **Node.js 20+**, a webcam, ~1.5 GB free disk.
All backend dependencies have prebuilt Windows wheels, so no C++ build tools are needed.

```powershell
git clone <your-repo-url> face-attendance-system      # or unzip the project
cd face-attendance-system
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1        # venv, packages, .env + secrets, database, model, npm
powershell -ExecutionPolicy Bypass -File .\scripts\create-admin.ps1 # first administrator (prompts for a password)
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1          # starts backend + frontend and opens the browser
```
Open <http://localhost:5173>, sign in, then follow [Using the app](#using-the-app).
Use `localhost` (not a LAN IP) - browsers only allow camera access on `localhost` or HTTPS.

> The PowerShell scripts were written for Windows but **were not executed on Windows** in development (the project was built and
> tested on Linux). They are thin wrappers around the manual commands below; if one fails, run the equivalent manual step.

## Manual setup

Backend (PowerShell, from the project root):
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env            # then put two random 32+ character secrets into .env (see below)
.\.venv\Scripts\python.exe -m alembic upgrade head            # create the database
.\.venv\Scripts\python.exe ..\scripts\download_model.py       # face model (once)
.\.venv\Scripts\python.exe -m app.cli create-admin            # first administrator
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```
Generate a secret: `python -c "import secrets; print(secrets.token_urlsafe(48))"` (run it twice: `SECRET_KEY`, `EMBEDDING_ENCRYPTION_KEY`).

Frontend (second terminal):
```powershell
cd frontend
npm install
npm run dev          # http://localhost:5173  (proxies /api and the WebSocket to :8000)
```
Linux/macOS: replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

## Configuration

Everything is an environment variable in `backend/.env` ([`.env.example`](backend/.env.example) documents each). The app **refuses to start without
`SECRET_KEY` and `EMBEDDING_ENCRYPTION_KEY`** - there are no default secrets. Runtime-editable values (threshold, liveness, timezone, camera, retention) live in
the database and are changed in *Sessions & settings*; the env values only seed them.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | SQLite in `backend/data/` | PostgreSQL: `postgresql+psycopg://user:pass@host/db` (install `psycopg[binary]`, run `alembic upgrade head`) |
| `EMBEDDING_ENCRYPTION_KEY` | - | Encrypts face templates. **Lose it and every enrolment is unreadable.** Back it up separately from the DB. |
| `COOKIE_SECURE` | `false` | Set `true` when serving over HTTPS |
| `CORS_ORIGINS` | localhost:5173 | Also the allow-list for state-changing requests and WebSocket origins |
| `ONNX_PROVIDERS` | `CPUExecutionProvider` | GPU: install `onnxruntime-gpu` instead of `onnxruntime`, set `CUDAExecutionProvider,CPUExecutionProvider`. Falls back to CPU with a warning if unavailable. |
| `DETECTION_SIZE` | 640 | Lower (320) is faster but finds smaller faces less reliably |

## Face recognition model setup and licence

`scripts/download_model.py` downloads the InsightFace **`buffalo_l`** pack (~280 MB zip) from the official InsightFace GitHub release into
`backend/data/insightface/buffalo_l/` and verifies its SHA-256 against the value recorded when this project was built.
Files used: `det_10g.onnx` (SCRFD face detector) and `w600k_r50.onnx` (ArcFace R50 recognizer).

- **Offline / blocked download:** download `buffalo_l.zip` elsewhere, then `python scripts\download_model.py --from-zip C:\path\buffalo_l.zip`.
- **If the model is missing** the API still starts, `/health` reports `model_loaded: false`, the scanner shows the exact error, enrollment returns HTTP 503. Nothing is mocked or silently replaced.
- **Licence:** the InsightFace *code* is MIT, but the **pretrained models are published for non-commercial research use only**. Read the terms at
  <https://github.com/deepinsight/insightface> before any commercial or institutional production use; you may need a commercial licence or a different model.
  This README is not legal advice.

## Using the app

1. **Create sessions** (*Sessions & settings → Sessions → New session*), e.g. "Morning 09:00-17:00, late after 09:15, Mon-Fri". **Nobody can be marked present until a session is open.**
   Check-in opens `early check-in` minutes before the start. Sessions cannot cross midnight.
2. **Register a person** (*People → Register person*). The ID must be unique.
3. **Enroll the face** (camera icon on the row): capture 3-8 photos with different head angles and expressions (or upload photos), tick the consent box, *Save*.
   Poor photos (no face, blurry, dark, two people, a different person mixed in) are rejected with the reason. If the face closely matches someone already enrolled, nothing is saved until you
   confirm it is a different person. *A match is a warning, not proof of identity.*
4. **Scan** (*Live scanner → Start scanning*). Allow the camera. When the server confirms the record, the screen shows the name, ID, time and status. While the person stays
   in view, the scanner holds the result and pauses submissions for the cooldown (default 10 s); a repeat scan says "Already marked" and writes nothing.
   *Pause* keeps the camera on; *Stop and release camera* turns it off. A disconnected camera is retried automatically; a lost server connection is reconnected.
5. **Review** on *Dashboard*, *Attendance* (filters, sorting, details, admin corrections, manual entries, **Export CSV** that respects the current filters) and *Reports*.

**Webcam permissions:** if the browser blocked the camera, click the camera icon in the address bar → *Allow*, then press Start again. Close other apps that use the camera (Teams, Zoom).

**Create the first administrator** only with `app.cli create-admin` / `scripts\create-admin.ps1` (prompts for the password). Further users are added in *Settings → Users*. Roles: **admin** (everything), **operator** (scanner, read, export), **viewer** (read-only).

**Deleting a person** (trash icon): face data is always permanently deleted. Choose to *anonymize* (history stays, identity removed), *delete everything*, or *delete face data only*.

## API documentation

Interactive Swagger UI: <http://127.0.0.1:8000/docs> (disabled when `ENVIRONMENT=production`). Base path `/api/v1`; errors always look like
`{"error": {"code", "message", "details"}}`. Authentication is an httpOnly cookie set by `POST /auth/login` (a `Bearer` token header also works for API clients).

| Group | Endpoints |
|---|---|
| Auth | `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `GET/POST /users`, `PUT /users/{id}` (admin) |
| People | `GET/POST /people` · `GET/PUT/DELETE /people/{id}` · `DELETE /people/{id}/biometrics` · `GET /departments` |
| Enrollment | `POST /people/{id}/enroll` (webcam frames) · `POST /people/{id}/enroll-images` (uploads) · `GET /people/{id}/enrollment-status` |
| Recognition | `POST /recognition/recognize` (single image, same service) · `GET /recognition/status` · `WS /recognition/ws` |
| Attendance | `GET /attendance` · `POST /attendance/manual` · `GET/PUT /attendance/{id}` · `GET /attendance/today` · `GET /attendance/person/{id}` |
| Sessions | `GET/POST /sessions` · `PUT/DELETE /sessions/{id}` |
| Dashboard / reports | `GET /dashboard/summary` · `GET /dashboard/trends` · `GET /reports/attendance` · `GET /reports/export` (CSV) |
| Admin | `GET/PUT /settings` · `GET /audit-logs` · `POST /maintenance/retention` |

**WebSocket protocol** (`/api/v1/recognition/ws`, cookie-authenticated, admin/operator, foreign origins refused): the client sends one **binary** JPEG frame at a time (≤ 2 MB) or text
`{"type":"reset"}` / `{"type":"ping"}`; the server answers JSON `{"type":"hello"}` on connect and `{"type":"result","status":…,"message":…,"person"?,"attendance"?,"similarity"?,"bbox"?,"timings"}` per frame.
Statuses: `no_face · multiple_faces · poor_quality · liveness_challenge · liveness_failed · unknown · marked · already_marked · no_active_session · person_disabled · model_unavailable · bad_image · cooldown`.
The server keeps only the newest pending frame, processes one frame at a time per connection in a worker thread, and answers `cooldown` without running inference after a result.
**The client never says who it is:** the server decides the identity and writes the record.

## Testing

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test.ps1       # everything below
cd backend;  .\.venv\Scripts\python.exe -m pytest -v               # 79 backend tests
cd backend;  .\.venv\Scripts\python.exe -m pytest -m real_model -s # only the real-model tests (prints measurements)
cd frontend; npm run typecheck; npm test; npm run build
```
Results recorded when this version was built (Linux, Python 3.13, 2 vCPU):

| Suite | Result | What it covers |
|---|---|---|
| Backend, **mocked recognition** (`FakeEngine`, real DB/threads/HTTP) | 71 passed | auth, roles, registration, duplicates, enrollment rules, unknown/ambiguous/no-face, sessions, timezone, late rules, computed absences, corrections, filters, CSV, dashboard, reports, WebSocket protocol, liveness state machine, model-failure errors, biometric deletion |
| Backend, **real model** (`-m real_model`) | 8 passed | real SCRFD+ArcFace on InsightFace's sample photos: separation of 6 different people, tolerance to flip/darkening, enroll → recognize → already-marked → unknown rejected, group photo refused, duplicate registration blocked |
| Concurrency | included above | 8 threads and 6 simultaneous HTTP requests for the same person → exactly 1 record |
| Frontend (Vitest) | 17 passed | scanner state wording/tones, success shown only for a server-confirmed record, error/empty states, login validation and errors |
| Type-check, production build | clean / OK | |
| **Browser end-to-end** (`scripts/e2e_browser.py`, headless Chromium + fake camera playing a real face) | 19 / 19 checks | login → register → webcam enrollment → live scan marks once → no duplicates after cooldown → pause/stop → dashboard → filters → CSV → unknown face rejected → blocked camera handled |

The mocked and real suites are separate: mocked tests never claim anything about recognition accuracy. The real-model tests are skipped automatically when the model is absent.
The browser script needs both servers running and the fake-camera files (`scripts/make_fake_camera.py`); see its docstring.
**Not tested:** the PowerShell scripts, Windows itself, a physical webcam, other browsers than Chromium, PostgreSQL, GPU.

## Backup and restore

Back up **both** the database and `backend\.env` (the encryption key). The database holds *encrypted* face templates, so a backup is useless without the key - and the key must not sit next to it.
```powershell
backend\.venv\Scripts\python.exe scripts\backup_db.py --keep 14      # consistent online backup to backups\ (SQLite backup API)
```
Restore: stop the backend, copy the chosen `backups\attendance-….db` over `backend\data\attendance.db`, delete `attendance.db-wal` / `-shm` if present, start the backend, check `/health`.
PostgreSQL: use `pg_dump` / `pg_restore`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Scanner says *Face model not loaded* | Run `scripts\download_model.py`; check `backend\data\insightface\buffalo_l\w600k_r50.onnx` exists; restart the backend. |
| *Camera access is blocked* | Allow the camera in the browser; use `http://localhost:5173`, not an IP; close apps using the camera. |
| *Server not connected* in the scanner | Backend not running on :8000, or you are signed out. The scanner reconnects automatically. |
| Everyone is "Person not recognized" | No one enrolled (see the yellow notice), face too small/dark, or the threshold is too high. Move closer, add front light, re-enroll with better photos. |
| "No open session" | Create a session that covers the current time and weekday (in the configured timezone). |
| Backend exits immediately with a validation error | `SECRET_KEY` / `EMBEDDING_ENCRYPTION_KEY` missing or shorter than 32 characters in `backend\.env`. |
| *Cannot decrypt stored face template* | `EMBEDDING_ENCRYPTION_KEY` differs from the one used at enrollment. Restore the original key, or delete biometrics and re-enroll. |
| Slow recognition | Lower `DETECTION_SIZE`, raise the frame interval in Settings, or use a GPU (see Configuration). |
| `pip install` fails | Use Python 3.10-3.13 (64-bit). Newer/older versions may lack prebuilt wheels. |
| Port already in use | Change `--port` for uvicorn and set `VITE_BACKEND_URL` for the frontend. |

## Security considerations

Summary (full detail in [docs/SECURITY_PRIVACY.md](docs/SECURITY_PRIVACY.md)): passwords hashed with bcrypt; sessions in httpOnly SameSite cookies with server-side revocation; role checks on every private route; login rate limiting;
Origin check on state-changing requests and WebSockets; input and upload validation with size limits; face templates encrypted at rest and never returned by the API; **enrollment photos are never stored**;
no video recording; audit log of administrative actions; stack traces never sent to clients. **Obtain consent, give notice, and check the law that applies to biometric data where you operate** - this project does not claim compliance with any law or standard.

## Known limitations

- **Spoofing:** the head-turn challenge is experimental. A video replay, a 3-D mask or a determined attacker can defeat it, and with liveness *off* a printed photo or a phone screen can be accepted. Do not rely on it for security-critical use; supervise the camera.
- **Accuracy is not guaranteed.** Look-alikes, twins, heavy occlusion, extreme lighting or angles can cause false rejects or (rarely) false accepts. The default threshold 0.45 (cosine similarity) is conservative but was **not validated on a large, diverse dataset** - run `scripts\calibrate_threshold.py` on your own consented photos ([docs/EVALUATION.md](docs/EVALUATION.md)). Scores are similarities, not probabilities.
- **Speed:** measured ≈ 0.46 s per recognized frame (detect ≈ 0.2 s + embed ≈ 0.24 s) on a 2-vCPU Linux CPU. Your laptop will differ; measure it with the real-model tests.
- **Licence:** the pretrained model is non-commercial research only (see above).
- One face at a time (several faces → "one person at a time"). Sessions cannot cross midnight. Absences use *today's* roster, not historical membership.
- Single-process design: the in-memory face gallery, rate limiter and WebSocket state are per process - run **one** Uvicorn worker (or move the limiter/gallery to shared storage first).
- SQLite is for local/small deployments; the app has not been run against PostgreSQL.
- Local development serves HTTP; for any real deployment put it behind HTTPS (`COOKIE_SECURE=true`).

## Future improvements

Cross-photo evaluation tooling with a public benchmark, a licensed/commercial model option, a dependable pretrained presentation-attack-detection model, multi-face scanning, Redis-backed rate limiting and gallery for multi-worker deployments,
PostgreSQL CI, email/SMS notifications, kiosk mode, historical roster tracking, scheduled retention, Docker packaging.
