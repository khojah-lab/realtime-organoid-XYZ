"""Train model from Label Studio COCO export
"""
import sys, os, json; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2, numpy as np, joblib
from pipeline import *
from pipeline import FEATURE_NAMES as F
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score
COLS = ["circularity","solidity","convex_perim_ratio","eccentricity","extent","ellipse_iou","radial_cv",
        "contrast_cv","core_rim_ratio","edge_sharpness"]
coco = json.load(open(sys.argv[1])); imgdir = sys.argv[2]
out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "frag_model.joblib")
frag_id = [c["id"] for c in coco["categories"] if c["name"].lower().startswith("frag")][0]
X, y, grp = [], [], []
for im in coco["images"]:
    anns = [a for a in coco["annotations"] if a["image_id"] == im["id"]]
    path = os.path.join(imgdir, os.path.basename(im["file_name"]))
    if not anns or not os.path.exists(path): continue
    pre = preprocess(cv2.imread(path)); lab = segment(pre, 0.16)
    for a in anns:
        gm = polygon_mask(a["segmentation"][0], lab.shape, pre["scale"])
        if pre["valid"][gm].mean() < 0.5: continue
        lbl = int(a["category_id"] == frag_id)
        X.append(object_features(gm, pre)); y.append(lbl); grp.append(im["id"])
        for i in np.unique(lab[gm]):
            if i and ((lab == i) & gm).sum() / ((lab == i) | gm).sum() > 0.5:
                X.append(object_features(lab == i, pre)); y.append(lbl); grp.append(im["id"])
idx = [F.index(c) for c in COLS]; X = np.array(X)[:, idx]; y = np.array(y); grp = np.array(grp)
mk = lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000))
p = np.zeros(len(y))
for g in np.unique(grp):
    if len(np.unique(y[grp != g])) < 2: continue
    p[grp == g] = mk().fit(X[grp != g], y[grp != g]).predict_proba(X[grp == g])[:, 1]
print(f"{len(y)} training objects ({y.sum()} fragment). Leave-one-image-out AUC: {roc_auc_score(y, p):.2f}")
joblib.dump(dict(model=mk().fit(X, y), cols=COLS), out); print("saved", out)
