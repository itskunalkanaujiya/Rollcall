# Security and privacy notes

This document describes what the software does. It is **not** a legal opinion and the project makes **no claim** of
compliance with GDPR, India's DPDP Act, BIPA, ISO standards or any other law or standard. Biometric data is regulated
in many places; the operator is responsible for the legal basis, notices and retention in their jurisdiction.

## What is stored
| Data | Stored? | Notes |
|---|---|---|
| Enrollment photos | **No** | Decoded in memory, turned into embeddings, discarded. |
| Scanner camera frames | **No** | Processed in memory only. |
| Face embeddings (512 floats) | Yes | Encrypted with Fernet using `EMBEDDING_ENCRYPTION_KEY`. They are biometric templates; treat the DB as sensitive. |
| Person details | Yes | ID, name, department, consent timestamp and who recorded it. |
| Attendance | Yes | Person, session, UTC time, local date/time, method, similarity score. |
| Audit log | Yes | Logins, enrollments, deletions, manual edits, setting changes. |

## Consent
Enrollment requires an explicit consent checkbox ("the person has been told how their face data is used and agreed").
The API rejects enrollment without `consent=true`; the consent time and recording admin are stored. The software cannot verify
the consent was real, so the operator must tell people what is collected, why, how long it is kept, and how to withdraw.
Suggested notice: purpose (attendance only), data (mathematical face template, no photo), retention, who can access it, how to request deletion.

## Deletion and retention
* Deleting a person's biometrics (`DELETE /people/{id}/biometrics`) removes all embeddings and refreshes the cache immediately.
* Deleting a person can optionally purge their attendance history.
* Settings: audit retention (default 365 days) and attendance retention (default: keep). `POST /maintenance/retention` applies them.
* Backups (`scripts/backup_db.py`) copy the encrypted DB; old backups are the operator's to delete.

## Access control and hardening
* Passwords: bcrypt with SHA-256 pre-hash (no 72-byte truncation). Minimum length (default 10) enforced for new passwords.
* Sessions: JWT in an `httpOnly`, `SameSite` cookie; `token_version` allows revocation (password change, logout everywhere).
* Roles: `admin` (everything), `operator` (scanner, view, manual attendance), `viewer` (read-only).
* Login rate limit per IP+username (in-process, resets on restart; not suitable for multi-process deployments).
* Origin check on state-changing requests and WebSocket upgrades; security headers; `Cache-Control: no-store` on `/api`.
* Upload limits: magic-byte and size validation, downscaling. CSV export neutralises spreadsheet formula injection.
* Secrets come from environment variables; `.env` is git-ignored; the app refuses to start with short secrets.

## Liveness: experimental, with real limits
When enabled (`liveness_policy = challenge`) the scanner asks for a random head turn and checks the pose changes. This is **not**
certified presentation-attack detection. It raises the effort for a held-up photo but can be defeated by video replay, masks,
or a deliberate face turn on a screen. Do not rely on it for high-security decisions. Default is off.

## Recognition limits and fairness
Face recognition error rates vary by lighting, camera, pose, age, and demographic group. The default threshold (0.45) and margin (0.04)
are starting points; calibrate on your own consented data (`scripts/calibrate_threshold.py`) and keep a manual-correction path.
A wrong or missed recognition must never be the only basis for a consequential decision about a person.

## Model licence
Code in this repo is the project's own. The InsightFace `buffalo_l` pretrained weights are released for **non-commercial research use only**.
Commercial use needs a different model or a licence from the InsightFace authors.

## Deployment notes
Designed for localhost / trusted LAN. Before exposing it: serve over HTTPS and set `cookie_secure` (env `COOKIE_SECURE=true`), restrict `CORS`/allowed origins, put it behind a
reverse proxy, use a process-shared rate limiter, and move to a server database.
