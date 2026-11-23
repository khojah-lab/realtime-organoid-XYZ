import sys, os, json, csv; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np, joblib
from pipeline import *
from pipeline import FEATURE_NAMES as F
MODEL = os.environ.get("FRAG_MODEL", os.path.join(os.path.dirname(os.path.abspath(__file__)), "frag_model.joblib"))
TH, FOCUS_MIN = 0.16, float(os.environ.get("FOCUS_MIN", 0.035))
COLORS = dict(intact=(80, 200, 0), fragment=(0, 140, 255), partial=(200, 200, 200), out_of_focus=(255, 0, 200))

def focus_score(mask, pre):
    """Mean gradient magnitude on the object boundry relative to the 90th percentile of the surrounding ring."""
    f = cv2.GaussianBlur(pre["flat"], (0, 0), 1.0)
    gm = np.hypot(cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3)) / 8
    m8 = mask.astype(np.uint8)
    ring = cv2.dilate(m8, np.ones((7, 7), np.uint8)).astype(bool) & ~cv2.erode(m8, np.ones((7, 7), np.uint8)).astype(bool)
    return float(np.percentile(gm[ring], 90))

def run(paths, out_dir, names=None):
    mdl = joblib.load(MODEL); idx = [F.index(c) for c in mdl["cols"]]
    os.makedirs(f"{out_dir}/overlays", exist_ok=True)
    rows, coco = [], dict(images=[], annotations=[], categories=[{"id": i, "name": n} for i, n in enumerate(COLORS)])
    for k, p in enumerate(paths):
        name = names[k] if names else os.path.basename(p)
        img = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        H0, W0 = img.shape[:2]
        pre = preprocess(img); lab = segment(pre, TH); s = pre["scale"]
        coco["images"].append(dict(id=k, file_name=name, width=W0, height=H0))
        g = np.clip(pre["gray"], 0, 255).astype(np.uint8)
        vis = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR); vis = cv2.resize(vis, None, fx=1.6, fy=1.6)
        for i in range(1, lab.max() + 1):
            m = lab == i
            f = object_features(m, pre); fo = focus_score(m, pre)
            prob = float(mdl["model"].predict_proba(np.array(f)[idx][None])[0, 1])
            if f[F.index("touches_border")]: status = "partial"
            elif fo < FOCUS_MIN: status = "out_of_focus"
            else: status = "fragment" if prob > 0.5 else "intact"
            cnts, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnt = max(cnts, key=cv2.contourArea)
            poly = (cnt[:, 0, :].astype(np.float64) / s)
            x, y, w, h = cv2.boundingRect((poly).astype(np.int32))
            area_px = float(m.sum() / s ** 2)
            rows.append(dict(image=name, object=i, status=status, p_fragment=round(prob, 3), focus=round(fo, 4),
                             area_px=round(area_px), cx=round(x + w / 2), cy=round(y + h / 2),
                             **{c: round(float(f[F.index(c)]), 4) for c in F}))
            coco["annotations"].append(dict(id=len(coco["annotations"]), image_id=k, category_id=list(COLORS).index(status),
                                            segmentation=[poly.ravel().round(1).tolist()], bbox=[x, y, w, h], area=area_px, iscrowd=0,
                                            score=prob))
            col = COLORS[status]
            cv2.drawContours(vis, [(cnt * 1.6).astype(np.int32)], -1, col, 3)
            lbl = f"{i} {status[:4]} {prob:.2f}" if status in ("intact", "fragment") else f"{i} {status}"
            ty = max(int(cnt[:, 0, 1].min() * 1.6) - 8, 22); tx = int(cnt[:, 0, 0].min() * 1.6)
            cv2.putText(vis, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 5)
            cv2.putText(vis, lbl, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
        cv2.putText(vis, name, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 5)
        cv2.putText(vis, name, (10, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
        cv2.imwrite(f"{out_dir}/overlays/{os.path.splitext(name)[0]}.jpg", vis, [cv2.IMWRITE_JPEG_QUALITY, 85])
    with open(f"{out_dir}/predictions.csv", "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    json.dump(coco, open(f"{out_dir}/predictions_coco.json", "w"))
    return rows

if __name__ == "__main__":
    run(sys.argv[2:], sys.argv[1])
