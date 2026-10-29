"""Measure genuine vs impostor similarity on YOUR consented photos and suggest a threshold.

Folder layout (folder name = identity, 2+ photos each, ideally taken on different days/lighting):
    DIR/alice/1.jpg 2.jpg 3.jpg
    DIR/bob/1.jpg 2.jpg ...
Run:  backend\\.venv\\Scripts\\python scripts\\calibrate_threshold.py DIR [--target-far 0.001]

Prints, for a range of thresholds, the false-accept rate (different people scoring >= threshold) and the
false-reject rate (same person scoring < threshold). A rate measured on N pairs is only an estimate: with a small
photo set a "0" means "none observed", not "impossible". Pick the lowest threshold that meets your FAR target,
then set it in Settings > Recognition. Photos are read locally and never stored.
"""
import argparse
import itertools
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.face_recognition import FaceEngine  # noqa: E402


def embed_dir(eng: FaceEngine, d: Path) -> dict[str, list[np.ndarray]]:
    out: dict[str, list[np.ndarray]] = {}
    for person in sorted(p for p in d.iterdir() if p.is_dir()):
        for f in sorted(person.iterdir()):
            img = cv2.imread(str(f))
            if img is None:
                continue
            faces = eng.detect(img)
            if len(faces) != 1:
                print(f"  skipped {person.name}/{f.name}: {len(faces)} faces found")
                continue
            out.setdefault(person.name, []).append(eng.embed(img, faces[0]))
    return {k: v for k, v in out.items() if v}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", type=Path)
    ap.add_argument("--target-far", type=float, default=0.001)
    a = ap.parse_args()
    eng = FaceEngine(); eng.load()
    data = embed_dir(eng, a.dir)
    genuine = [float(x @ y) for v in data.values() for x, y in itertools.combinations(v, 2)]
    impostor = [float(x @ y) for (_, va), (_, vb) in itertools.combinations(data.items(), 2) for x in va for y in vb]
    if not genuine or not impostor:
        print("Need at least 2 people and 2 usable photos of at least one person.")
        return 1
    g, i = np.array(genuine), np.array(impostor)
    print(f"\nidentities={len(data)}  genuine pairs={len(g)}  impostor pairs={len(i)}")
    print(f"genuine  : min {g.min():.3f}  median {np.median(g):.3f}")
    print(f"impostor : max {i.max():.3f}  99th pct {np.percentile(i, 99):.3f}")
    print("\nthreshold   FAR(impostor accepted)   FRR(genuine rejected)")
    ts = np.round(np.arange(0.20, 0.71, 0.05), 2)
    for t in ts:
        print(f"  {t:.2f}      {np.mean(i >= t):>8.4%}              {np.mean(g < t):>8.4%}")
    ok = [t for t in np.arange(0.20, 0.90, 0.01) if np.mean(i >= t) <= a.target_far]
    print(f"\nLowest threshold with FAR <= {a.target_far:.3%} on this data: {ok[0]:.2f}" if ok else "\nNo threshold met the FAR target on this data.")
    print("Keep a margin above the impostor maximum and re-check with more people before relying on it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
