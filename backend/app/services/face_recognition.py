"""Embedding generation (ArcFace R50 / w600k_r50 from buffalo_l) and the engine that
owns the loaded models. Models are loaded exactly once per process."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.core.config import Settings, get_settings
from app.services.face_detection import DetectedFace, FaceDetector, ModelUnavailableError

log = logging.getLogger("app.face")

RECOGNIZER_FILE = "w600k_r50.onnx"
EMBEDDING_DIM = 512
DOWNLOAD_HELP = (
    "Download the model pack with:  python scripts/download_model.py  "
    "(or see README > 'Face recognition model setup')."
)


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32).ravel()
    n = float(np.linalg.norm(v))
    if n < 1e-8:
        raise ValueError("Zero-norm embedding")
    return v / n


class FaceEmbedder:
    def __init__(self, model_dir: Path, providers: list[str]) -> None:
        path = model_dir / RECOGNIZER_FILE
        if not path.exists():
            raise ModelUnavailableError(f"Recognition model not found: {path}")
        try:
            from insightface.model_zoo import get_model
            self._model = get_model(str(path), providers=providers)
        except Exception as exc:  # noqa: BLE001
            raise ModelUnavailableError(f"Failed to load recognition model {path}: {exc}") from exc
        if getattr(self._model, "taskname", None) != "recognition":
            raise ModelUnavailableError(f"{path} is not a recognition model")
        self.input_size = self._model.input_size

    def embed(self, img_bgr: np.ndarray, face: DetectedFace) -> np.ndarray:
        """Align with the 5-point ArcFace template, then embed. Returns a unit vector."""
        from insightface.utils import face_align
        aligned = face_align.norm_crop(img_bgr, landmark=face.kps, image_size=self.input_size[0])
        return l2_normalize(self._model.get_feat(aligned))


@dataclass
class Timings:
    decode_ms: float = 0.0
    detect_ms: float = 0.0
    embed_ms: float = 0.0
    match_ms: float = 0.0
    total_ms: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {k: round(v, 1) for k, v in self.__dict__.items()}


@dataclass
class EngineInfo:
    loaded: bool
    model_name: str
    providers_requested: list[str]
    providers_active: list[str]
    det_size: int
    error: str | None = None
    notes: list[str] = field(default_factory=list)


class FaceEngine:
    """Owns detector + embedder. `lock` serialises inference so the shared ONNX sessions
    and the detector's internal caches are never used concurrently."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.model_dir = Path(self.settings.model_root) / self.settings.model_name
        self.detector: FaceDetector | None = None
        self.embedder: FaceEmbedder | None = None
        self.lock = threading.Lock()
        self.info = EngineInfo(False, self.settings.model_name, self.settings.providers, [],
                               self.settings.detection_size)

    # -- lifecycle ----------------------------------------------------------
    def load(self) -> None:
        """Load models once. Raises ModelUnavailableError with actionable text."""
        if self.is_loaded:
            return
        import onnxruntime as ort

        requested = self.settings.providers
        available = ort.get_available_providers()
        usable = [p for p in requested if p in available]
        notes: list[str] = []
        if usable != requested:
            missing = [p for p in requested if p not in available]
            notes.append(f"Requested ONNX provider(s) {missing} unavailable; using CPUExecutionProvider. "
                         f"Available: {available}")
            log.warning(notes[-1])
        providers = usable or ["CPUExecutionProvider"]
        if not self.model_dir.is_dir():
            msg = f"Model directory not found: {self.model_dir}. {DOWNLOAD_HELP}"
            self.info = EngineInfo(False, self.settings.model_name, requested, [], self.settings.detection_size, msg, notes)
            raise ModelUnavailableError(msg)
        t0 = time.perf_counter()
        try:
            self.detector = FaceDetector(self.model_dir, self.settings.detection_size, providers)
            self.embedder = FaceEmbedder(self.model_dir, providers)
        except ModelUnavailableError as exc:
            self.detector = self.embedder = None
            msg = f"{exc}. {DOWNLOAD_HELP}"
            self.info = EngineInfo(False, self.settings.model_name, requested, [], self.settings.detection_size, msg, notes)
            raise ModelUnavailableError(msg) from exc
        self.info = EngineInfo(True, self.settings.model_name, requested, providers, self.settings.detection_size, None, notes)
        log.info("Face model '%s' loaded in %.2fs (providers=%s)", self.settings.model_name,
                 time.perf_counter() - t0, providers)

    @property
    def is_loaded(self) -> bool:
        return self.detector is not None and self.embedder is not None

    def require(self) -> tuple[FaceDetector, FaceEmbedder]:
        if not self.is_loaded:
            self.load()  # raises ModelUnavailableError if files are missing
        assert self.detector and self.embedder
        return self.detector, self.embedder

    # -- inference (blocking; call from a worker thread) ---------------------
    def detect(self, img: np.ndarray) -> list[DetectedFace]:
        det, _ = self.require()
        with self.lock:
            return det.detect(img)

    def embed(self, img: np.ndarray, face: DetectedFace) -> np.ndarray:
        _, emb = self.require()
        with self.lock:
            return emb.embed(img, face)


_engine: FaceEngine | None = None


def get_engine() -> FaceEngine:
    global _engine
    if _engine is None:
        _engine = FaceEngine()
    return _engine


def set_engine(engine: FaceEngine | None) -> None:
    """Test hook: swap the process-wide engine."""
    global _engine
    _engine = engine
