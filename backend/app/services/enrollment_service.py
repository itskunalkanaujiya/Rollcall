"""Face enrolment: validate images, create encrypted templates, detect duplicate identities.

Only the 512-d template (Fernet-encrypted) is stored. The submitted photographs are decoded in
memory and discarded - no enrolment image is ever written to disk."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import encrypt_bytes
from app.core.timeutil import utc_now
from app.models import FaceEmbedding, Person, User
from app.services import settings_service
from app.services.embedding_cache import get_cache
from app.services.face_detection import ISSUE_HINTS, ModelUnavailableError, assess_quality
from app.services.face_recognition import EMBEDDING_DIM, FaceEngine, get_engine
from app.services.imaging import ImageError, decode_image

log = logging.getLogger("app.enroll")

SAME_FACE_MIN_SIM = 0.30   # samples of one person must be at least this similar to each other


@dataclass
class Rejection:
    index: int
    code: str
    reason: str


@dataclass
class EnrollOutcome:
    accepted: int = 0
    rejected: list[Rejection] = field(default_factory=list)
    possible_duplicates: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    saved: bool = False


def enrollment_status(n_samples: int) -> str:
    s = get_settings()
    if n_samples == 0:
        return "not_enrolled"
    return "enrolled" if n_samples >= s.min_enroll_images else "partial"


def sample_count(db: Session, person_id: int) -> int:
    return db.scalar(select(func.count(FaceEmbedding.id)).where(FaceEmbedding.person_id == person_id)) or 0


def extract_templates(db: Session, images: list[bytes], engine: FaceEngine | None = None
                      ) -> tuple[list[tuple[int, np.ndarray, float]], list[Rejection]]:
    """Run detection + quality + embedding on each image. Returns (accepted, rejected)."""
    engine = engine or get_engine()
    engine.require()          # fail fast with ModelUnavailableError (clear message) before any work
    cfg = settings_service.get_all(db)
    accepted: list[tuple[int, np.ndarray, float]] = []
    rejected: list[Rejection] = []
    for i, data in enumerate(images):
        try:
            img = decode_image(data)
        except ImageError as exc:
            rejected.append(Rejection(i, exc.code, exc.message))
            continue
        faces = engine.detect(img)
        if not faces:
            rejected.append(Rejection(i, "no_face", "No face detected"))
            continue
        if len(faces) > 1 and faces[1].area > 0.25 * faces[0].area:
            rejected.append(Rejection(i, "multiple_faces", "More than one face in the image"))
            continue
        face = faces[0]
        q = assess_quality(img, face, min_size=cfg["min_face_size_px"], min_score=cfg["min_det_score"],
                           max_abs_yaw=0.55)  # enrolment tolerates more head turn than scanning
        if not q.ok:
            code = q.issues[0]
            rejected.append(Rejection(i, code, ISSUE_HINTS.get(code, "Image quality too low")))
            continue
        accepted.append((i, engine.embed(img, face), face.score))
    return accepted, rejected


def _drop_inconsistent(accepted: list[tuple[int, np.ndarray, float]], rejected: list[Rejection]
                       ) -> list[tuple[int, np.ndarray, float]]:
    """Reject samples that do not look like the rest (e.g. someone else stepped into frame)."""
    if len(accepted) < 3:
        return accepted
    mat = np.stack([a[1] for a in accepted])
    keep: list[tuple[int, np.ndarray, float]] = []
    for k, item in enumerate(accepted):
        others = np.delete(mat, k, axis=0)
        sims = others @ item[1]
        if float(np.median(sims)) < SAME_FACE_MIN_SIM:
            rejected.append(Rejection(item[0], "inconsistent_identity",
                                      "This face does not match the other samples"))
        else:
            keep.append(item)
    return keep


def enroll(db: Session, person: Person, images: list[bytes], source: str, user: User,
           confirm_duplicate: bool = False, engine: FaceEngine | None = None) -> EnrollOutcome:
    s = get_settings()
    out = EnrollOutcome()
    if not images:
        raise ValueError("No images supplied")
    existing = sample_count(db, person.id)
    if existing + len(images) > s.max_enroll_images * 3:
        raise ValueError("Too many images for one request")
    accepted, out.rejected = extract_templates(db, images, engine)
    accepted = _drop_inconsistent(accepted, out.rejected)
    room = max(0, s.max_enroll_images - existing)
    if len(accepted) > room:
        out.warnings.append(f"Only {s.max_enroll_images} samples are kept per person; extra images ignored")
        accepted = accepted[:room]
    if not accepted:
        return out

    # Compare against everyone else's templates: a high similarity means this may be a
    # DIFFERENT registration of the same human being (or a look-alike). It is a warning, not proof.
    cfg = settings_service.get_all(db)
    cache = get_cache()
    seen: dict[int, float] = {}
    for _, emb, _score in accepted:
        near = cache.nearest(emb, exclude_person=person.id)
        if near and near[1] >= cfg["recognition_threshold"]:
            seen[near[0]] = max(seen.get(near[0], -1.0), near[1])
    for pid, sim in seen.items():
        other = db.get(Person, pid)
        if other is not None:
            out.possible_duplicates.append({"person_id": other.id, "person_code": other.person_code,
                                            "full_name": other.full_name, "similarity": round(sim, 3)})
    if out.possible_duplicates and not confirm_duplicate:
        out.warnings.append("Possible duplicate identity. Nothing was saved; review the matches and resubmit "
                            "with confirm_duplicate=true if this really is a different person.")
        return out

    now = utc_now()
    for _, emb, score in accepted:
        db.add(FaceEmbedding(person_id=person.id, vector_encrypted=encrypt_bytes(emb.astype(np.float32).tobytes()),
                             dim=EMBEDDING_DIM, model_name=s.model_name, det_score=round(score, 4),
                             source=source, created_at=now))
    if person.consent_at is None:
        person.consent_at, person.consent_recorded_by = now, user.id
    db.commit()
    get_cache().refresh(db)
    out.accepted, out.saved = len(accepted), True
    return out


def delete_biometrics(db: Session, person: Person) -> int:
    """Remove every stored template for a person (and refresh the live gallery)."""
    n = db.query(FaceEmbedding).filter(FaceEmbedding.person_id == person.id).delete()
    db.commit()
    get_cache().refresh(db)
    return n


__all__ = ["enroll", "delete_biometrics", "enrollment_status", "sample_count", "ModelUnavailableError"]
