"""In-memory gallery of enrolled face templates and the identity decision rule."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.core.security import decrypt_bytes
from app.models import FaceEmbedding, Person, PersonStatus

log = logging.getLogger("app.cache")


@dataclass
class MatchResult:
    person_id: int | None        # None => unknown (never the "closest" person)
    best_similarity: float       # cosine similarity of best candidate (NOT a probability)
    second_similarity: float     # best similarity of a different person (-1 if none)
    reason: str                  # matched | below_threshold | ambiguous | empty_gallery
    active: bool = True


class EmbeddingCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._matrix = np.zeros((0, 512), dtype=np.float32)
        self._starts = np.zeros(0, dtype=np.int64)
        self._people = np.zeros(0, dtype=np.int64)    # one person id per group
        self._active = np.zeros(0, dtype=bool)
        self.version = 0

    def refresh(self, db: Session) -> int:
        """Reload every template from the DB. Call after enrol / delete / status change."""
        rows = (
            db.query(FaceEmbedding.person_id, FaceEmbedding.vector_encrypted, FaceEmbedding.dim, Person.status)
            .join(Person, Person.id == FaceEmbedding.person_id)
            .order_by(FaceEmbedding.person_id, FaceEmbedding.id)
            .all()
        )
        vecs, owners, active = [], [], {}
        for pid, blob, dim, status in rows:
            v = np.frombuffer(decrypt_bytes(blob), dtype=np.float32)
            if v.shape[0] != dim:
                log.error("Skipping corrupt template for person %s (dim %s != %s)", pid, v.shape[0], dim)
                continue
            vecs.append(v)
            owners.append(pid)
            active[pid] = status == PersonStatus.active
        with self._lock:
            if vecs:
                self._matrix = np.vstack(vecs).astype(np.float32)
                owners_arr = np.array(owners, dtype=np.int64)
                change = np.flatnonzero(np.r_[True, owners_arr[1:] != owners_arr[:-1]])
                self._starts = change
                self._people = owners_arr[change]
                self._active = np.array([active[p] for p in self._people], dtype=bool)
            else:
                self._matrix = np.zeros((0, 512), dtype=np.float32)
                self._starts = np.zeros(0, dtype=np.int64)
                self._people = np.zeros(0, dtype=np.int64)
                self._active = np.zeros(0, dtype=bool)
            self.version += 1
        log.info("Embedding cache refreshed: %d templates, %d people", len(vecs), len(self._people))
        return len(vecs)

    @property
    def size(self) -> tuple[int, int]:
        with self._lock:
            return int(self._matrix.shape[0]), int(self._people.shape[0])

    def match(self, emb: np.ndarray, threshold: float, margin: float) -> MatchResult:
        with self._lock:
            if self._matrix.shape[0] == 0:
                return MatchResult(None, -1.0, -1.0, "empty_gallery")
            sims = self._matrix @ emb.astype(np.float32)
            per_person = np.maximum.reduceat(sims, self._starts)  # best template per person
            order = np.argsort(-per_person)
            best_i = int(order[0])
            best = float(per_person[best_i])
            second = float(per_person[order[1]]) if len(order) > 1 else -1.0
            pid = int(self._people[best_i])
            active = bool(self._active[best_i])
        if best < threshold:
            return MatchResult(None, best, second, "below_threshold")
        if second >= 0 and (best - second) < margin:
            # Two different people are almost equally similar: refuse rather than guess.
            return MatchResult(None, best, second, "ambiguous")
        return MatchResult(pid, best, second, "matched", active)

    def nearest(self, emb: np.ndarray, exclude_person: int | None = None) -> tuple[int, float] | None:
        """Closest enrolled person (for duplicate-identity warnings during enrolment only)."""
        with self._lock:
            if self._matrix.shape[0] == 0:
                return None
            per_person = np.maximum.reduceat(self._matrix @ emb.astype(np.float32), self._starts)
            order = np.argsort(-per_person)
            for i in order:
                if exclude_person is None or int(self._people[i]) != exclude_person:
                    return int(self._people[i]), float(per_person[i])
        return None


_cache = EmbeddingCache()


def get_cache() -> EmbeddingCache:
    return _cache
