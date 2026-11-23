# 2023-only model — results (preliminary)

Produced by [`2023_only_model.py`](../2023_only_model.py): a YOLOv8s instance-segmentation model
trained **only** on the 2023 labeled images, then run on the 2024 unlabeled images.

## Setup

| | |
|---|---|
| Training data | `2023-labeled/` — 18 images (800×600), 99 polygons from Label Studio COCO export |
| Classes | `Fragment`, `Intact` |
| Split | 14 train / 4 val (random, seed 0) |
| Base model | `yolov8s-seg.pt` (COCO-pretrained) |
| Training | 10 epochs, imgsz 800, batch 4, Apple M4 (MPS), ~1 min |
| Preprocessing | 2023 images converted to grayscale (3-channel) to match the 2024 images |
| Augmentation | rotation ±90°, flips, scale 0.6, brightness 0.4, mosaic |
| Inference | `2024-unlabeled/` — 20 images (4056×3040 grayscale), conf ≥ 0.25 |

## Results

**Validation (4 held-out 2023 images, 24 instances)** — best epoch:

| | Precision | Recall | mAP50 | mAP50-95 |
|---|---|---|---|---|
| Box | 0.097 | 0.25 | 0.078 | 0.052 |
| Mask | 0.097 | 0.25 | 0.078 | 0.064 |

**2024 predictions:** 76 detections across 20 images (41 Fragment, 35 Intact) — see
`predictions/per_image_counts.csv`.

⚠️ **These predictions should not be trusted.** Visual inspection of the overlays shows the model
mostly misses the large organoids in the 2024 images and fires on small debris or on huge
image-wide regions. Validation mAP is near zero, so the model has not learned the task yet.

Likely reasons:
1. **Very short training** — 10 epochs on 14 images; loss had not converged.
2. **Domain/scale shift** — 2023 organoids are small blobs at low magnification with striped
   illumination; 2024 images are illumination-corrected, higher magnification, and organoids
   fill a large part of the frame.
3. **Tiny dataset** — 99 annotations total.

Suggested next steps: train longer (`--epochs 100+`), label a handful of 2024 images, or tile /
rescale 2024 images so organoid size matches the 2023 training scale.

## Contents

```
predictions/
  overlays/*_pred.png     predicted masks drawn on each 2024 image (downscaled to 1600px)
  detections.csv          one row per detection: class, confidence, bbox (orig px), mask area
  per_image_counts.csv    Fragment / Intact counts per image
  predictions.json        polygons in original 4056×3040 pixel coordinates
training/                 Ultralytics metrics (results.csv/png), PR curves, confusion matrix, batches
weights/best.pt           trained weights (reuse with `python 2023_only_model.py --skip-train`
                          after copying to 2023_only_model_work/runs/train/weights/)
```

## Reproduce

```bash
python3.12 -m venv .venv && .venv/bin/pip install ultralytics
.venv/bin/python 2023_only_model.py            # defaults: 10 epochs, device mps
```

Note: the pyenv Python 3.11.9 on this machine lacks `_lzma`, which torchvision needs; use a Python
built with xz support (e.g. python.org 3.12).
