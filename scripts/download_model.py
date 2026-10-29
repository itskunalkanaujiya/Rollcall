"""Download and unpack the InsightFace model pack into backend/data/insightface/<name>/.

    python scripts/download_model.py            # buffalo_l (default)
    python scripts/download_model.py --from-zip C:\\path\\buffalo_l.zip   # offline install

LICENCE: InsightFace *code* is MIT, but the pretrained model packs are released for
NON-COMMERCIAL RESEARCH use only. Read https://github.com/deepinsight/insightface before any
commercial deployment. This script only fetches the files you ask for; by running it you
accept responsibility for complying with those terms.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/{name}.zip"
# The two files this app actually loads from each pack (see app/services/face_detection.py
# MODEL_PACK_FILES - keep these in sync). buffalo_s is ~13x smaller for memory-constrained hosts.
PACK_REQUIRED = {
    "buffalo_l": ["det_10g.onnx", "w600k_r50.onnx"],
    "buffalo_s": ["det_500m.onnx", "w600k_mbf.onnx"],
}
# SHA-256 of each {name}.zip release asset, as downloaded on the date noted.
KNOWN_SHA256 = {
    "buffalo_l": "80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f",  # 2026-10-27
    "buffalo_s": "d85a87f503f691807cd8bb97128bdf7a0660326cd9cd02657127fa978bab8b5e",  # 2026-10-29
}
ROOT = Path(__file__).resolve().parents[1] / "backend" / "data" / "insightface"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for m in zf.namelist():
        target = (dest / m).resolve()
        if dest not in target.parents and target != dest:
            raise SystemExit(f"Refusing unsafe path in archive: {m}")
    zf.extractall(dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="buffalo_l")
    ap.add_argument("--from-zip", type=Path, help="use an already downloaded zip")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    required = PACK_REQUIRED.get(a.name, PACK_REQUIRED["buffalo_l"])

    dest = ROOT / a.name
    if all((dest / f).exists() for f in required) and not a.force:
        print(f"Model already installed at {dest}")
        return 0
    dest.mkdir(parents=True, exist_ok=True)
    zpath = a.from_zip
    if zpath is None:
        zpath = ROOT / f"{a.name}.zip"
        url = URL.format(name=a.name)
        print(f"Downloading {url} ...")
        try:
            urllib.request.urlretrieve(url, zpath)
        except Exception as exc:  # noqa: BLE001
            print(f"Download failed: {exc}\nDownload it manually and rerun with --from-zip <file>.", file=sys.stderr)
            return 1
    digest = sha256(zpath)
    expected = KNOWN_SHA256.get(a.name)
    if expected and digest != expected:
        print(f"WARNING: SHA-256 mismatch.\n  expected {expected}\n  got      {digest}\n"
              "The upstream asset may have changed, or the download is corrupt/tampered.", file=sys.stderr)
        if input("Continue anyway? [y/N] ").strip().lower() != "y":
            return 2
    with zipfile.ZipFile(zpath) as zf:
        safe_extract(zf, dest)
    missing = [f for f in required if not (dest / f).exists()]
    if missing:
        print(f"Archive did not contain required files: {missing}", file=sys.stderr)
        return 3
    print(f"Installed to {dest}\nSHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
