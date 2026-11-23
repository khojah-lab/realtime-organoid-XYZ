"""Organoid pipeline for preprocessing, segmentation, and feature extraction.

Stages:
  1. Preprocessing: grayscale, resize to a common working width, estimate the
     illumination background with objects masked out, flatten, and mask out
     the dark vignette/dish edge.
  2. Segmentation: threshold the flattened contrast map, clean up, split touching
     objects with a distance-transform watershed.
  3. Feature extraction and classification: shape/texture features per object, scored by a
     model trained on the 2023 Label Studio polygons.
"""
import cv2
import numpy as np
from scipy import ndimage as ndi
from skimage import measure, segmentation, morphology, feature

WORK_W = 1000          # all images resized to this width
MIN_AREA = 250         # pixels at WORK_W; removes tiny debris
VIGNETTE_FRAC = 0.55   # background darker than this * median background is treated as outside the field


def to_gray(img):
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img.astype(np.float32)


def _masked_blur(img, mask, sigma):
    w = mask.astype(np.float32)
    num = cv2.GaussianBlur(img * w, (0, 0), sigma)
    den = cv2.GaussianBlur(w, (0, 0), sigma)
    return num / np.maximum(den, 1e-3)


def estimate_background(gray):
    """Illumination field, estimated at 1/4 scale with dark objects masked out."""
    h, w = gray.shape
    small = cv2.resize(gray, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), 1.5)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)) 
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, k)
    bg = cv2.GaussianBlur(bg, (0, 0), 6)
    return cv2.resize(bg, (w, h), interpolation=cv2.INTER_CUBIC)


def preprocess(img):
    """Returns dictionary with resized gray, background, flattened image, contrast map, valid mask, scale."""
    gray = to_gray(img)
    scale = WORK_W / gray.shape[1]
    gray = cv2.resize(gray, (WORK_W, int(round(gray.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    bg = estimate_background(gray)
    flat = gray / np.maximum(bg, 1)
    valid = bg > VIGNETTE_FRAC * np.median(bg)
    flat = flat / np.median(flat[valid])
    contrast = cv2.GaussianBlur(1.0 - flat, (0, 0), 2.0)
    valid = cv2.erode(valid.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    return dict(gray=gray, bg=bg, flat=flat, contrast=contrast, valid=valid, scale=scale)


def segment(pre, thresh=0.12, split=True):
    c, valid = pre["contrast"], pre["valid"]
    fg = (c > thresh)
    fg = ndi.binary_fill_holes(fg)
    fg = ndi.binary_opening(fg, structure=morphology.disk(3))
    fg = morphology.remove_small_objects(fg, max_size=MIN_AREA)
    fg = ndi.binary_fill_holes(fg)
    if split:
        dist = ndi.distance_transform_edt(fg)
        hmax = morphology.h_maxima(cv2.GaussianBlur(dist, (0, 0), 2), 6)
        markers = measure.label(hmax)
        labels = segmentation.watershed(-dist, markers, mask=fg)
        labels = morphology.remove_small_objects(labels, max_size=MIN_AREA)
    else:
        labels = measure.label(fg)
    # drop objects where majority lies outside of valid field
    out = np.zeros_like(labels)
    k = 1
    for r in measure.regionprops(labels):
        sl = labels[r.slice] == r.label
        # drop thin slivers (dish-edge artifacts, fibres, hairs)
        if r.axis_minor_length < 14 or (r.solidity < 0.5 and r.area > 4000):
            continue
        if valid[r.slice][sl].mean() > 0.5:
            out[r.slice][sl] = k
            k += 1
    return out


FEATURE_NAMES = [
    "log_area_frac", "circularity", "solidity", "convex_perim_ratio", "eccentricity",
    "extent", "ellipse_iou", "radial_cv", "mean_contrast", "contrast_cv",
    "core_rim_ratio", "edge_sharpness", "touches_border",
]


def object_features(mask, pre):
    """mask: bool array at working resolution for a single object."""
    c, flat = pre["contrast"], pre["flat"]
    H, W = mask.shape
    props = measure.regionprops(mask.astype(np.uint8))[0]
    area = props.area
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cnt = max(cnts, key=cv2.contourArea)
    # smooth contour so perimeter isn't dominated by pixel staircase
    cnt_s = cv2.approxPolyDP(cnt, 1.5, True)
    perim = max(cv2.arcLength(cnt_s, True), 1)
    hull = cv2.convexHull(cnt)
    hull_area = max(cv2.contourArea(hull), 1)
    hull_perim = max(cv2.arcLength(hull, True), 1)
    circ = 4 * np.pi * area / perim ** 2
    # ellipse fit agreement
    ell_iou = 0.0
    if len(cnt) >= 5:
        ell = cv2.fitEllipse(cnt)
        em = np.zeros_like(mask, np.uint8)
        cv2.ellipse(em, ell, 1, -1)
        em = em.astype(bool)
        ell_iou = (em & mask).sum() / max((em | mask).sum(), 1)
    # radial irregularity
    pts = cnt[:, 0, :].astype(np.float32)
    cy, cx = props.centroid
    rad = np.hypot(pts[:, 0] - cx, pts[:, 1] - cy)
    radial_cv = rad.std() / max(rad.mean(), 1)
    vals = c[mask]
    mean_c = vals.mean()
    contrast_cv = vals.std() / max(abs(mean_c), 1e-3)
    dist = ndi.distance_transform_edt(mask)
    dmax = dist.max()
    core = mask & (dist > 0.5 * dmax)
    rim = mask & (dist <= 0.25 * dmax)
    core_rim = (c[core].mean() + 1e-3) / (c[rim].mean() + 1e-3) if core.any() and rim.any() else 1.0
    gx = cv2.Sobel(flat, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(flat, cv2.CV_32F, 0, 1, ksize=3)
    gm = np.hypot(gx, gy)
    ring = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & ~cv2.erode(
        mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    edge = gm[ring].mean() / max(abs(mean_c), 1e-3)
    r0, c0, r1, c1 = props.bbox
    touches = float(r0 <= 1 or c0 <= 1 or r1 >= H - 1 or c1 >= W - 1)
    return [
        np.log(area / (H * W)), circ, area / hull_area, hull_perim / perim, props.eccentricity,
        props.extent, ell_iou, radial_cv, mean_c, contrast_cv, core_rim, edge, touches,
    ]


def polygon_mask(seg, shape, scale):
    m = np.zeros(shape, np.uint8)
    pts = (np.array(seg).reshape(-1, 2) * scale).round().astype(np.int32)
    cv2.fillPoly(m, [pts], 1)
    return m.astype(bool)
