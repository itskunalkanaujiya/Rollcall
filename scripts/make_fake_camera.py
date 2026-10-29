"""Create MJPEG files for Chromium's fake camera (--use-file-for-fake-video-capture) from the sample
photographs bundled with the insightface package. Used only by scripts/e2e_browser.py.

    backend/.venv/bin/python scripts/make_fake_camera.py OUT_DIR
Writes face_a.mjpeg (person A, frontal) and face_b.mjpeg (a different person)."""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from insightface.data import get_image  # noqa: E402

from app.services.face_recognition import FaceEngine  # noqa: E402


def frame_for(crop: np.ndarray, w=640, h=480) -> np.ndarray:
    scale = min(w / crop.shape[1], h / crop.shape[0])
    r = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    canvas = np.full((h, w, 3), 90, np.uint8)
    y, x = (h - r.shape[0]) // 2, (w - r.shape[1]) // 2
    canvas[y:y + r.shape[0], x:x + r.shape[1]] = r
    return canvas


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    eng = FaceEngine(); eng.load()
    img = get_image("t1")
    faces = sorted(eng.detect(img), key=lambda f: f.bbox[0])
    for name, idx in (("face_a", 0), ("face_b", 2)):
        x1, y1, x2, y2 = (int(v) for v in faces[idx].bbox)
        pad = int(1.2 * (x2 - x1))                       # generous context, like a real webcam frame
        crop = img[max(0, y1 - pad): y2 + pad, max(0, x1 - pad): x2 + pad]
        fr = frame_for(crop)
        ok, buf = cv2.imencode(".jpg", fr, [cv2.IMWRITE_JPEG_QUALITY, 92])
        (out / f"{name}.mjpeg").write_bytes(buf.tobytes() * 60)      # MJPEG = concatenated JPEGs
        cv2.imwrite(str(out / f"{name}.jpg"), fr)
        print("wrote", out / f"{name}.mjpeg")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
