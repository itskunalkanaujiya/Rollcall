"""Face detection (SCRFD from the InsightFace buffalo_l pack), quality checks and
a landmark-based head-pose proxy. No identity logic lives here."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("app.face")

DETECTOR_FILE = "det_10g.onnx"


class ModelUnavailableError(RuntimeError):
    """Raised when the face model files are missing or cannot be loaded."""


def low_memory_session_options():
    """Single-threaded, no memory arena - keeps ONNX Runtime's footprint small enough
    for a 512MB host (e.g. Render's free tier). Costs a little latency, not accuracy."""
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.intra_op_num_threads = 1
    so.inter_op_num_threads = 1
    so.enable_cpu_mem_arena = False
    so.enable_mem_pattern = False
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return so


@dataclass
class DetectedFace:
    bbox: np.ndarray            # [x1, y1, x2, y2] in the (possibly downscaled) frame
    kps: np.ndarray             # 5x2 landmarks: eye(image-left), eye(image-right), nose, mouth L, mouth R
    score: float                # detector confidence (not an identity probability)

    @property
    def width(self) -> float:
        return float(self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return float(self.bbox[3] - self.bbox[1])

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)


@dataclass
class QualityReport:
    ok: bool
    issues: list[str] = field(default_factory=list)   # machine codes
    hint: str | None = None                            # human message for the first issue
    blur: float = 0.0
    brightness: float = 0.0
    yaw: float = 0.0
    face_size: float = 0.0


ISSUE_HINTS = {
    "too_small": "Move closer to the camera.",
    "low_confidence": "Face not clear - face the camera directly.",
    "too_blurry": "Image is blurry - hold still and check the lens.",
    "too_dark": "Too dark - add light in front of your face.",
    "too_bright": "Too bright - avoid strong backlight.",
    "not_frontal": "Look straight at the camera.",
    "partially_outside": "Keep your whole face inside the frame.",
}


def yaw_proxy(kps: np.ndarray) -> float:
    """Horizontal nose offset relative to the eye midpoint, normalised by eye distance.

    ~0 when frontal; positive when the nose moves toward image-right (subject turning
    toward THEIR left in an unmirrored frame). This is a coarse proxy, not a calibrated
    angle - roughly +-0.5 corresponds to a strong turn.
    """
    eye_l, eye_r, nose = kps[0], kps[1], kps[2]
    eye_dist = float(np.linalg.norm(eye_r - eye_l))
    if eye_dist < 1e-3:
        return 0.0
    return float((nose[0] - (eye_l[0] + eye_r[0]) / 2.0) / eye_dist)


def assess_quality(img: np.ndarray, face: DetectedFace, *, min_size: int, min_score: float,
                   max_abs_yaw: float | None = 0.40) -> QualityReport:
    issues: list[str] = []
    h, w = img.shape[:2]
    x1, y1, x2, y2 = face.bbox
    size = min(face.width, face.height)
    if size < min_size:
        issues.append("too_small")
    if face.score < min_score:
        issues.append("low_confidence")
    margin = 0.02
    if x1 < -margin * w or y1 < -margin * h or x2 > (1 + margin) * w or y2 > (1 + margin) * h:
        issues.append("partially_outside")

    xi1, yi1 = max(0, int(x1)), max(0, int(y1))
    xi2, yi2 = min(w, int(x2)), min(h, int(y2))
    blur = brightness = 0.0
    if xi2 - xi1 > 8 and yi2 - yi1 > 8:
        crop = cv2.cvtColor(img[yi1:yi2, xi1:xi2], cv2.COLOR_BGR2GRAY)
        crop = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)
        blur = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        brightness = float(crop.mean())
        if blur < 15.0:
            issues.append("too_blurry")
        if brightness < 45:
            issues.append("too_dark")
        elif brightness > 215:
            issues.append("too_bright")
    yaw = yaw_proxy(face.kps)
    if max_abs_yaw is not None and abs(yaw) > max_abs_yaw:
        issues.append("not_frontal")
    return QualityReport(ok=not issues, issues=issues,
                         hint=ISSUE_HINTS[issues[0]] if issues else None,
                         blur=blur, brightness=brightness, yaw=yaw, face_size=size)


class FaceDetector:
    """Wraps the SCRFD ONNX detector. Loaded once; call from a single inference thread."""

    def __init__(self, model_dir: Path, det_size: int, providers: list[str]) -> None:
        path = model_dir / DETECTOR_FILE
        if not path.exists():
            raise ModelUnavailableError(f"Detector model not found: {path}")
        try:
            from insightface.model_zoo import get_model
            self._model = get_model(str(path), providers=providers, sess_options=low_memory_session_options())
            self._model.prepare(ctx_id=-1 if providers == ["CPUExecutionProvider"] else 0,
                                input_size=(det_size, det_size), det_thresh=0.4)
        except Exception as exc:  # noqa: BLE001 - surface any loader failure clearly
            raise ModelUnavailableError(f"Failed to load detector {path}: {exc}") from exc
        self.det_size = (det_size, det_size)

    def detect(self, img_bgr: np.ndarray) -> list[DetectedFace]:
        bboxes, kpss = self._model.detect(img_bgr, input_size=self.det_size, max_num=0, metric="default")
        faces: list[DetectedFace] = []
        if bboxes is None or len(bboxes) == 0 or kpss is None:
            return faces
        for b, k in zip(bboxes, kpss):
            faces.append(DetectedFace(bbox=b[:4].astype(np.float32), kps=k.astype(np.float32), score=float(b[4])))
        faces.sort(key=lambda f: f.area, reverse=True)
        return faces
