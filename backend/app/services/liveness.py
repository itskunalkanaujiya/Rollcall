"""EXPERIMENTAL challenge-response liveness (random head turn).

Kept separate from identity recognition. What it does: asks the person to turn their
head to a randomly chosen side within a time limit, and checks (a) a frontal pose was seen
first, (b) the landmark-based yaw proxy then moved far enough in the requested direction,
(c) every frame belonged to the same face (embedding similarity to the first frame).

What it does NOT do: it is NOT presentation-attack detection. A replayed video of the
person turning, a 3-D mask, or a sufficiently skilled attacker can defeat it, and a tilted
printed photo may sometimes shift the yaw proxy. No dependable, permissively licensed
pretrained anti-spoofing model was integrated. Treat as a deterrent for casual
photo-holding, not as production-grade security.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import numpy as np

FRONTAL_MAX = 0.12      # |yaw proxy| considered frontal
TURN_MIN = 0.28         # |yaw proxy| required in the requested direction
CHALLENGE_SECONDS = 8.0
FRONTAL_FRAMES_REQUIRED = 2
CONSISTENCY_MIN_SIM = 0.35   # same-face check across pose change (looser than identity threshold)
VERIFIED_TTL = 20.0


@dataclass
class LivenessState:
    status: str                 # idle | need_frontal | challenge | passed | failed
    instruction: str | None = None
    challenge: str | None = None
    reason: str | None = None
    reference: np.ndarray | None = field(default=None, repr=False)


class LivenessSession:
    """One per scanner connection. Not shared between people: reset() when the face changes."""

    def __init__(self, rng: random.Random | None = None, clock=time.monotonic) -> None:
        self._rng = rng or random.SystemRandom()
        self._clock = clock
        self.reset()

    def reset(self) -> None:
        self.status = "idle"
        self.challenge: str | None = None
        self._frontal = 0
        self._deadline = 0.0
        self._ref: np.ndarray | None = None
        self._passed_at = 0.0

    @property
    def reference(self) -> np.ndarray | None:
        return self._ref

    def passed_recently(self) -> bool:
        return self.status == "passed" and (self._clock() - self._passed_at) <= VERIFIED_TTL

    def update(self, yaw: float, embedding: np.ndarray) -> LivenessState:
        now = self._clock()
        if self.status == "passed":
            if self.passed_recently():
                return LivenessState("passed", reference=self._ref)
            self.reset()

        if self.status in ("idle", "need_frontal"):
            self.status = "need_frontal"
            if abs(yaw) <= FRONTAL_MAX:
                self._frontal += 1
                if self._frontal == 1:
                    self._ref = embedding
                if self._frontal >= FRONTAL_FRAMES_REQUIRED:
                    self.challenge = self._rng.choice(["left", "right"])
                    self._deadline = now + CHALLENGE_SECONDS
                    self.status = "challenge"
            else:
                self._frontal = 0
            if self.status == "need_frontal":
                return LivenessState("need_frontal", "Look straight at the camera.")

        if self.status == "challenge":
            assert self._ref is not None and self.challenge is not None
            if float(self._ref @ embedding) < CONSISTENCY_MIN_SIM:
                st = LivenessState("failed", reason="face_changed")
                self.reset()
                return st
            if now > self._deadline:
                st = LivenessState("failed", reason="timeout", challenge=self.challenge)
                self.reset()
                return st
            direction_ok = yaw >= TURN_MIN if self.challenge == "left" else yaw <= -TURN_MIN
            if direction_ok:
                self.status = "passed"
                self._passed_at = now
                return LivenessState("passed", reference=self._ref)
            return LivenessState("challenge", f"Slowly turn your head to YOUR {self.challenge.upper()}.",
                                 challenge=self.challenge)
        return LivenessState(self.status)
