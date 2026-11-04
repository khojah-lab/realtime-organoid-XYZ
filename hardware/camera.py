"""
hardware/camera.py
────────────────────────────────────────────────────────────────
Manages the Picamera2 hardware stream, background frame buffer
loop, MJPEG HTTP frame generator, and high-resolution still capture.
────────────────────────────────────────────────────────────────
"""

import time
import threading
import cv2
import numpy as np

from config import (
    CAMERA_MAIN_SIZE,
    CAMERA_LORES_SIZE,
    CAMERA_BUFFER_COUNT,
    CAPTURE_INTERVAL_SEC,
    STREAM_INTERVAL_SEC,
    STREAM_JPEG_QUALITY,
)

# ── Camera Hardware Initialization ────────────────────────────
picam2 = None

try:
    from picamera2 import Picamera2

    picam2 = Picamera2()
    camera_config = picam2.create_video_configuration(
        main={"size": CAMERA_MAIN_SIZE},   # high-quality capture stream
        lores={"size": CAMERA_LORES_SIZE}, # smooth web preview stream
        display="lores",
        buffer_count=CAMERA_BUFFER_COUNT,
    )
    picam2.configure(camera_config)
    picam2.start()
    time.sleep(2)
except Exception as e:
    print(f"[WARNING] Camera not available: {e}")
    picam2 = None

# ── Shared Frame Buffer & Locks ───────────────────────────────
_latest_frame: np.ndarray | None = None
_frame_lock  = threading.Lock()
_camera_lock = threading.Lock()
_capture_thread_started = False


def is_camera_connected() -> bool:
    """Return True if Picamera2 initialized successfully."""
    return picam2 is not None


def capture_bgr_frame() -> np.ndarray | None:
    """
    Capture a fresh full-resolution frame directly from Picamera2
    and convert from RGB to OpenCV BGR format.
    """
    if picam2 is None:
        return None

    with _camera_lock:
        request = picam2.capture_request()
        frame = request.make_array("main")
        request.release()

    # In hardware/camera.py -> capture_bgr_frame()
    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)  # or ROTATE_180, ROTATE_90_COUNTERCLOCKWISE
    frame = frame = cv2.flip(frame, 0) 
    return frame


def get_latest_frame() -> np.ndarray | None:
    """Return a thread-safe copy of the most recent frame from the buffer."""
    with _frame_lock:
        if _latest_frame is None:
            return None
        return _latest_frame.copy()


def _capture_loop() -> None:
    """Background daemon loop that continuously updates `_latest_frame`."""
    global _latest_frame
    if picam2 is None:
        return

    while True:
        try:
            frame = capture_bgr_frame()
            if frame is not None:
                with _frame_lock:
                    _latest_frame = frame
        except Exception as e:
            print(f"[CAMERA] Capture error: {e}")

        time.sleep(CAPTURE_INTERVAL_SEC)


def start_camera_capture_thread() -> None:
    """Start the background frame capture thread once."""
    global _capture_thread_started
    if _capture_thread_started:
        return
    _capture_thread_started = True
    threading.Thread(target=_capture_loop, daemon=True, name="CameraCaptureLoop").start()


def generate_mjpeg_frames():
    """
    Generator yielding multipart MJPEG frames for the `/video` route.
    Performs JPEG compression outside the frame lock to avoid blocking capture.
    """
    while True:
        frame_to_encode = get_latest_frame()

        # If the camera hasn't initialized a frame yet, wait slightly and skip
        if frame_to_encode is None:
            time.sleep(0.01)
            continue

        try:
            ret, buffer = cv2.imencode(
                ".jpg",
                frame_to_encode,
                [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY],
            )
            if not ret:
                continue

            frame_bytes = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
        except Exception as e:
            print(f"[CAMERA] Streaming encoding error: {e}")
            time.sleep(0.05)

        time.sleep(STREAM_INTERVAL_SEC)
