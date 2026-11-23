# Organoid Segmentation Trained On 2023 Khojah Lab Data

Requires: python3, opencv-python, scikit-image, scikit-learn, scipy, numpy, joblib.

## Prediction on 2024 Khojah Lab Data
Writes `overlays/*.jpg`, `predictions.csv` (one row per object, with p_fragment and all features)
and `predictions_coco.json` (polygons in original pixel coordinates; import into Label Studio to correct).

Classification of object:
- intact/fragment: classifier result (p_fragment > 0.5 = fragment)
- partial: touches the image edge, so shape can't be judged. Also include dish-edge artifacts.
- out_of_focus: boundary too blurry to trust 

## Retrain (e.g. after correcting 2024 predictions in Label Studio)
    python train_from_coco.py result.json /path/to/label-studio/media/upload/2
Overwrites frag_model.joblib and prints leave-one-image-out AUC.

## Pipeline
  1. Preprocessing: grayscale, resize to a common working width, estimate the
     illumination background with objects masked out, flatten, and mask out
     the dark vignette/dish edge.
  2. Segmentation: threshold the flattened contrast map, clean up, split touching
     objects with a distance-transform watershed.
  3. Feature extraction and classification: shape/texture features per object, scored by a
     model trained on the 2023 Label Studio polygons.