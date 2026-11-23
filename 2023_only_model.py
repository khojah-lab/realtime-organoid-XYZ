"""
2023-only organoid segmentation model.

Trains a YOLOv8 instance-segmentation model on the Label Studio COCO export in
`2023-labeled/` (classes: Fragment, Intact), then predicts on the images in
`2024-unlabeled/` and writes everything to `2023_only_model_results/`.

Usage:
    python 2023_only_model.py                 # prepare data, train, predict
    python 2023_only_model.py --skip-train    # predict with existing weights
    python 2023_only_model.py --epochs 50 --device cpu

Requires: pip install ultralytics
"""

import argparse
import csv
import json
import random
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
LABELED_DIR = ROOT / "2023-labeled"
COCO_JSON = LABELED_DIR / "result.json"
LABELED_IMAGES = LABELED_DIR / "images"
UNLABELED_DIR = ROOT / "2024-unlabeled"
WORK_DIR = ROOT / "2023_only_model_work"          # intermediate dataset + training runs (gitignored)
RESULTS_DIR = ROOT / "2023_only_model_results"    # final outputs (committed)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}


def to_gray_rgb(img: Image.Image) -> Image.Image:
    """2024 images are grayscale; train/predict on grayscale replicated to 3 channels."""
    return img.convert("L").convert("RGB")


# --------------------------------------------------------------------------- #
# 1. COCO (Label Studio) -> YOLO segmentation dataset
# --------------------------------------------------------------------------- #
def prepare_dataset(val_fraction: float, seed: int) -> tuple[Path, list[str]]:
    coco = json.loads(COCO_JSON.read_text())
    class_names = [c["name"] for c in sorted(coco["categories"], key=lambda c: c["id"])]
    cat_to_idx = {c["id"]: i for i, c in enumerate(sorted(coco["categories"], key=lambda c: c["id"]))}

    anns_by_image: dict[int, list] = {}
    for a in coco["annotations"]:
        anns_by_image.setdefault(a["image_id"], []).append(a)

    images = []
    for im in coco["images"]:
        # Label Studio stores an absolute upload path; match by basename.
        fname = Path(im["file_name"]).name
        path = LABELED_IMAGES / fname
        if not path.exists():
            print(f"  [warn] missing image {fname}, skipping")
            continue
        images.append((im["id"], path))

    rng = random.Random(seed)
    rng.shuffle(images)
    n_val = max(1, round(len(images) * val_fraction))
    splits = {"val": images[:n_val], "train": images[n_val:]}

    ds = WORK_DIR / "dataset"
    if ds.exists():
        shutil.rmtree(ds)

    for split, items in splits.items():
        (ds / "images" / split).mkdir(parents=True)
        (ds / "labels" / split).mkdir(parents=True)
        for img_id, path in items:
            img = Image.open(path)
            w, h = img.size  # COCO export has null sizes for some images; trust the file
            to_gray_rgb(img).save(ds / "images" / split / path.name)
            lines = []
            for a in anns_by_image.get(img_id, []):
                for poly in a.get("segmentation") or []:
                    if len(poly) < 6:
                        continue
                    xy = np.array(poly, dtype=float).reshape(-1, 2)
                    xy[:, 0] = np.clip(xy[:, 0] / w, 0, 1)
                    xy[:, 1] = np.clip(xy[:, 1] / h, 0, 1)
                    coords = " ".join(f"{v:.6f}" for v in xy.flatten())
                    lines.append(f"{cat_to_idx[a['category_id']]} {coords}")
            (ds / "labels" / split / f"{path.stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))

    yaml_path = ds / "data.yaml"
    yaml_path.write_text(
        f"path: {ds}\ntrain: images/train\nval: images/val\n"
        f"names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(class_names))
    )
    print(f"Dataset: {len(splits['train'])} train / {len(splits['val'])} val images, "
          f"{len(coco['annotations'])} annotations, classes={class_names}")
    return yaml_path, class_names


# --------------------------------------------------------------------------- #
# 2. Train
# --------------------------------------------------------------------------- #
def train(data_yaml: Path, args) -> Path:
    from ultralytics import YOLO

    model = YOLO(args.base_model)
    model.train(
        data=str(data_yaml),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        project=str(WORK_DIR / "runs"),
        name="train",
        exist_ok=True,
        patience=args.patience,
        seed=args.seed,
        workers=0,
        # Organoids are rotation/flip invariant; 2024 images are at a different
        # magnification and grayscale, so lean on geometric + intensity augmentation.
        degrees=90,
        flipud=0.5,
        fliplr=0.5,
        scale=0.6,
        hsv_h=0.0,
        hsv_s=0.0,
        hsv_v=0.4,
        mosaic=1.0,
        plots=True,
        verbose=False,
    )
    best = WORK_DIR / "runs" / "train" / "weights" / "best.pt"
    print(f"Best weights: {best}")
    return best


# --------------------------------------------------------------------------- #
# 3. Predict on 2024-unlabeled
# --------------------------------------------------------------------------- #
def predict(weights: Path, args) -> None:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    names = model.names
    pred_dir = RESULTS_DIR / "predictions"
    overlay_dir = pred_dir / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(p for p in UNLABELED_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    detections, per_image, coco_preds = [], [], []

    for p in image_paths:
        img = to_gray_rgb(Image.open(p))
        r = model.predict(img, imgsz=args.imgsz, conf=args.conf, device=args.device,
                          retina_masks=True, verbose=False)[0]
        counts = {n: 0 for n in names.values()}
        if r.boxes is not None and len(r.boxes):
            polys = r.masks.xy if r.masks is not None else [None] * len(r.boxes)
            mask_areas = (r.masks.data.sum(dim=(1, 2)).cpu().numpy()
                          if r.masks is not None else [0] * len(r.boxes))
            for i, (box, cls, conf) in enumerate(zip(r.boxes.xyxy.cpu().numpy(),
                                                     r.boxes.cls.cpu().numpy().astype(int),
                                                     r.boxes.conf.cpu().numpy())):
                label = names[cls]
                counts[label] += 1
                x1, y1, x2, y2 = box.tolist()
                detections.append({
                    "image": p.name, "detection_id": i, "class": label,
                    "confidence": round(float(conf), 4),
                    "x1": round(x1, 1), "y1": round(y1, 1), "x2": round(x2, 1), "y2": round(y2, 1),
                    "mask_area_px": int(mask_areas[i]),
                })
                poly = polys[i]
                coco_preds.append({
                    "image": p.name, "class": label, "confidence": float(conf),
                    "bbox_xyxy": [x1, y1, x2, y2],
                    "segmentation": [] if poly is None else [np.round(poly, 1).flatten().tolist()],
                })
        per_image.append({"image": p.name, "total": sum(counts.values()), **counts})

        # Downscaled overlay for viewing (originals are 4056x3040)
        plotted = Image.fromarray(r.plot(line_width=6, font_size=40)[..., ::-1])
        plotted.thumbnail((1600, 1600))
        plotted.save(overlay_dir / f"{p.stem}_pred.png")
        print(f"  {p.name}: {counts}")

    def write_csv(path, rows):
        if not rows:
            path.write_text("")
            return
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    write_csv(pred_dir / "detections.csv", detections)
    write_csv(pred_dir / "per_image_counts.csv", per_image)
    (pred_dir / "predictions.json").write_text(json.dumps(coco_preds))
    print(f"Predicted {len(image_paths)} images, {len(detections)} detections -> {pred_dir}")


def collect_training_artifacts(weights: Path) -> None:
    """Copy weights, metrics, and plots from the training run into the results folder."""
    run = weights.parent.parent
    out = RESULTS_DIR / "training"
    out.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "weights").mkdir(exist_ok=True)
    shutil.copy2(weights, RESULTS_DIR / "weights" / "best.pt")
    for f in run.iterdir():
        if f.suffix in {".csv", ".png", ".jpg", ".yaml"}:
            shutil.copy2(f, out / f.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-model", default="yolov8s-seg.pt")
    ap.add_argument("--epochs", type=int, default=10)  # preliminary model
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--imgsz", type=int, default=800)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--val-fraction", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="mps", help="mps, cpu, or cuda index")
    ap.add_argument("--skip-train", action="store_true")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    weights = WORK_DIR / "runs" / "train" / "weights" / "best.pt"
    if not args.skip_train:
        data_yaml, _ = prepare_dataset(args.val_fraction, args.seed)
        weights = train(data_yaml, args)
        collect_training_artifacts(weights)
    predict(weights, args)


if __name__ == "__main__":
    main()
