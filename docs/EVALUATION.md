# Evaluation: what was measured and what it does not show

## Method
* `scripts/calibrate_threshold.py DIR` embeds every photo in `DIR/<identity>/*.jpg`, forms all **genuine** pairs (same identity) and
  **impostor** pairs (different identities), and reports false-accept rate (FAR) and false-reject rate (FRR) at a range of thresholds.
* `backend/tests/test_real_model.py` runs the real model on InsightFace's bundled sample images (six people in `t1.jpg`, plus one more).
* `scripts/e2e_browser.py` drives the real UI with a fake camera streaming a face video.

## Measured results (CPU only, 2 vCPU Linux sandbox)
| Item | Result |
|---|---|
| Max cosine between 6 different people | 0.207 (threshold 0.45) |
| Same face, flipped / darker / resized | ≥ 0.93 |
| Calibration script on the sample set | genuine min 0.919, impostor max 0.250 |
| Latency per recognition | ≈ 460 ms (detect ≈ 205 ms, embed ≈ 239 ms) |
| Browser E2E | 19 of 19 checks passed (Chromium, fake camera) |

## Limits: read before trusting the numbers
1. "Same person" samples are re-renderings of **one photo**, so genuine scores are optimistic. Real cross-day, cross-camera, cross-pose
   genuine scores are lower and the real false-reject rate is higher than shown.
2. Only ~7 identities were available. A rate of 0 on so few pairs means "none observed", not "impossible".
3. No demographic breakdown was possible; none is claimed.
4. Latency is for this CPU. A laptop will differ; measure with `pytest -m real_model -s`.
5. Not tested: Windows, a physical webcam, browsers other than Chromium, PostgreSQL, GPU, large rosters (embedding cache is a brute-force dot product; fine for thousands, untested beyond).

## How to calibrate for your site
1. With consent, collect 3+ photos per person on different days and lighting (20+ people is a sensible minimum).
2. Run the calibration script, choose the lowest threshold meeting your FAR target, and set it in Settings > Recognition.
3. Re-check after changing camera or room. Keep reviewing the audit log and the "unknown" rate.
