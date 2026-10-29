# Architecture

## Overview

```
Browser (React + Vite)                     Backend (FastAPI, one process)                 Storage
┌──────────────────────┐  REST /api/v1   ┌──────────────────────────────────┐   ┌────────────────────┐
│ Pages: Dashboard,    │ ──────────────► │ api/v1  (auth, people, attendance,│   │ SQLite (SQLAlchemy)│
│ Scanner, People,     │  cookie auth    │          recognition, admin)      │──►│ + Alembic migration│
│ Attendance, Reports, │                 │ services (business rules)         │   │ Fernet-encrypted   │
│ Settings             │  WS /recognition│ core (config, security, tz, rate) │   │ embeddings         │
│ getUserMedia camera  │ ◄─────────────► │ middleware (Origin, headers)      │   └────────────────────┘
└──────────────────────┘  JPEG frames    │ FaceEngine (InsightFace buffalo_l │
                                         │  SCRFD + ArcFace, onnxruntime CPU)│
                                         └──────────────────────────────────┘
```

Everything runs on one machine. The camera is opened by the browser; frames go to the local backend only.

## Backend layers

| Layer | Path | Responsibility |
|---|---|---|
| API | `app/api/v1/*` | HTTP/WS handlers: validate input (Pydantic), check role, call services. No business rules. |
| Services | `app/services/*` | Enrollment, recognition pipeline, attendance rules, reporting, settings, audit, liveness. |
| Core | `app/core/*` | Settings from environment, password/JWT, dependencies, error model, timezone helpers, rate limiter. |
| Models / DB | `app/models`, `app/database` | SQLAlchemy models, session factory, migrations in `alembic/`. |
| Middleware | `app/middleware/security.py` | Origin check (HTTP and WebSocket), security headers. |

### Face engine
`FaceEngine` loads the SCRFD detector and ArcFace R50 recogniser **once** at startup (lifespan). A lock serialises
inference because onnxruntime sessions are shared. Embeddings are 512-d, L2-normalised; similarity is cosine
(a dot product). If the model files are missing the app starts but recognition endpoints answer 503 with a clear message.

### Recognition pipeline (`recognition_service.recognize_frame`)
1. Decode and validate the image (magic bytes, size, downscale).
2. Detect faces. None → `no_face`; more than one → `multiple_faces` (never guesses).
3. Quality gate: detection score, minimum face size, head pose. Fail → `poor_quality`.
4. Optional liveness challenge (WebSocket only, experimental, see SECURITY_PRIVACY.md).
5. Embed and compare with the in-memory cache of active people.
6. Decide: best score ≥ threshold **and** lead over the second-best person ≥ margin → match; else `unknown`.
7. Resolve the open session; mark attendance (idempotent); return a typed result.

### Attendance rules
* Time source is the **server** UTC clock; local date/time derive from the configured timezone. The browser clock is never trusted.
* Unique constraint `(person_id, session_id, session_date)`. The insert runs in a SAVEPOINT; an `IntegrityError`
  means someone else won the race, and the existing record is returned as `already_marked`.
* Late = strictly after the session's late cutoff. Absent is computed only after a session has ended, from the active roster,
  and never for dates before the session existed. Manual records and corrections are audit-logged.

### WebSocket protocol (`/api/v1/recognition/ws`)
Client sends binary JPEG frames. The server keeps only the newest frame, processes one at a time in a threadpool, and replies with
JSON results. During a person's cooldown window it answers `cooldown` without running inference. Text control messages: `{"type":"reset"}` (forget liveness/cooldown state) and `{"type":"ping"}`; the server sends `hello`, `result`, `pong`, `error`.

## Frontend
* Vite + React + TypeScript, Tailwind 4 with CSS-variable theme (light/dark), lazy-loaded routes, Recharts.
* `services/api.ts` is the only place that talks to Axios; errors are normalised to `{code, message}`.
* `hooks/useCamera.ts` handles permissions, device choice, auto-retry on disconnect, and always releases tracks on stop/unmount.
* `utils/scanState.ts` maps server results to UI states (single source of truth, unit-tested).

## Data model
`users`, `people`, `face_embeddings` (encrypted), `sessions`, `attendance_records`, `settings`, `audit_logs`.
See `backend/alembic/versions/0001_initial_schema.py`. SQLite is the default; the code uses no SQLite-only features,
but PostgreSQL has **not** been tested.

## Testing layers
* Mocked-engine tests (`FakeEngine`) for rules, API and security: fast and deterministic. They prove the logic, not the model.
* `real_model` tests run the actual InsightFace model on its bundled sample images.
* Frontend: Vitest + Testing Library. Browser E2E: `scripts/e2e_browser.py` (Playwright, fake camera feeding a real face video).
