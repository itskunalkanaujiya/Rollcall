"""Safe image decoding for uploads and camera frames."""
from __future__ import annotations

import cv2
import numpy as np

from app.core.config import get_settings


class ImageError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF")  # JPEG, PNG, WEBP


def decode_image(data: bytes, max_bytes: int | None = None) -> np.ndarray:
    """Decode JPEG/PNG/WEBP bytes to a BGR array, downscaled so the longer side is
    <= MAX_FRAME_SIDE. Raises ImageError for anything else (checks content, not the filename)."""
    s = get_settings()
    limit = max_bytes or s.max_upload_bytes
    if not data:
        raise ImageError("empty_image", "Empty image")
    if len(data) > limit:
        raise ImageError("image_too_large", f"Image exceeds the {limit // 1024} KB limit")
    if not data.startswith(_MAGIC):
        raise ImageError("unsupported_image", "Only JPEG, PNG or WEBP images are accepted")
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None or arr.ndim != 3:
        raise ImageError("corrupt_image", "The image could not be decoded")
    h, w = arr.shape[:2]
    if h < 64 or w < 64:
        raise ImageError("image_too_small", "Image is too small")
    if h * w > 40_000_000:
        raise ImageError("image_too_large", "Image dimensions are too large")
    side = max(h, w)
    if side > s.max_frame_side:
        scale = s.max_frame_side / side
        arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return arr
