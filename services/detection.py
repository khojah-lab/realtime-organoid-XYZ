"""
services/detection.py
────────────────────────────────────────────────────────────────
Organoid detection service.
Attempts inference with a TensorFlow 2 SavedModel if present in
`my_model/saved_model`, and falls back to OpenCV contour-based
organoid segmentation (`simple_organoid_detection`).
────────────────────────────────────────────────────────────────
"""

import base64
import os
import threading
import traceback
import cv2
import numpy as np

from config import SAVED_MODEL_DIR, LABEL_MAP_PATH
from hardware.camera import get_latest_frame
from services.telemetry import emit_socket_event

_detect_fn = None
_category_index = None
_model_loader_started = False


def _load_detection_model() -> None:
    """Attempt to load the TensorFlow SavedModel and label map in the background."""
    global _detect_fn, _category_index
    try:
        if not os.path.exists(SAVED_MODEL_DIR):
            print(f"[DETECTION] {SAVED_MODEL_DIR} not found — using OpenCV fallback.")
            return

        import tensorflow as tf
        from object_detection.utils import label_map_util

        os.environ["TF_CPP_MIN_LOG_LEVEL"] = "2"
        print("[DETECTION] Loading TensorFlow model...")
        _detect_fn = tf.saved_model.load(str(SAVED_MODEL_DIR))
        _category_index = label_map_util.create_category_index_from_labelmap(
            str(LABEL_MAP_PATH), use_display_name=True
        )
        print("[DETECTION] TensorFlow model ready.")
    except Exception as e:
        print(f"[DETECTION] Could not load TensorFlow model ({e}) — using OpenCV fallback.")


def start_detection_model_loader() -> None:
    """Start background thread to load the TensorFlow SavedModel once."""
    global _model_loader_started
    if _model_loader_started:
        return
    _model_loader_started = True
    threading.Thread(
        target=_load_detection_model, daemon=True, name="TFModelLoader"
    ).start()


def simple_organoid_detection(
    frame: np.ndarray,
    min_area: float = 100.0,
    max_area: float = 50000.0,
) -> tuple[np.ndarray, int]:
    """
    Lightweight OpenCV contour-based organoid detection fallback.
    Finds circular/elliptical organoid candidates via Gaussian blur,
    adaptive thresholding, and contour area filtering.

    Returns (annotated_bgr_frame, count).
    """
    annotated = frame.copy()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (7, 7), 0)

    thresh = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        4,
    )

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    count = 0
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if min_area <= area <= max_area:
            count += 1
            x, y, w, h = cv2.boundingRect(cnt)
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(
                annotated,
                f"#{count}",
                (x, max(15, y - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )

    return annotated, count


def run_detection() -> None:
    """
    Run organoid detection on the latest camera frame and emit
    `detection_result` (plus legacy `response3` alias) over Socket.IO.
    """
    try:
        frame = get_latest_frame()
        if frame is None:
            print("[DETECTION] No frame available")
            payload = {"data": None, "error": "No frame available"}
            emit_socket_event("detection_result", payload)
            emit_socket_event("response3", payload)
            return

        result_frame = None
        count = 0

        # 1. Try TensorFlow detection if model is loaded
        if _detect_fn is not None:
            try:
                import tensorflow as tf
                from object_detection.utils import visualization_utils as viz_utils

                print("[DETECTION] Using TensorFlow model...")
                input_tensor = tf.convert_to_tensor(frame)[tf.newaxis, ...]
                detections = _detect_fn(input_tensor)

                num_det = int(detections.pop("num_detections"))
                detections = {
                    k: v[0, :num_det].numpy() for k, v in detections.items()
                }
                detections["num_detections"] = num_det
                detections["detection_classes"] = detections[
                    "detection_classes"
                ].astype(np.int64)

                result_frame = frame.copy()
                viz_utils.visualize_boxes_and_labels_on_image_array(
                    result_frame,
                    detections["detection_boxes"],
                    detections["detection_classes"],
                    detections["detection_scores"],
                    _category_index,
                    use_normalized_coordinates=True,
                    max_boxes_to_draw=200,
                    min_score_thresh=0.3,
                    agnostic_mode=False,
                )

                count = int( np.sum(detections["detection_scores"] >= 0.3) )
                print(f"[DETECTION] TensorFlow found {count} organoids")
            except Exception as e:
                print(f"[DETECTION] TensorFlow error: {e}")
                print("[DETECTION] Falling back to OpenCV detection...")

        # 2. Fallback to OpenCV contour detection
        if result_frame is None:
            print("[DETECTION] Using simple OpenCV detection...")
            result_frame, count = simple_organoid_detection(frame)

        if result_frame is not None:
            _, buf = cv2.imencode(".jpg", result_frame)
            b64 = base64.b64encode(buf).decode("utf-8")
            payload = {"data": b64, "count": count}
            emit_socket_event("detection_result", payload)
            emit_socket_event("response3", payload)
            print(f"[DETECTION] Detection complete. Found {count} objects")
        else:
            payload = {"data": None, "error": "Detection failed"}
            emit_socket_event("detection_result", payload)
            emit_socket_event("response3", payload)

    except Exception as e:
        print(f"[DETECTION] Error: {e}")
        traceback.print_exc()
        payload = {"data": None, "error": str(e)}
        emit_socket_event("detection_result", payload)
        emit_socket_event("response3", payload)
