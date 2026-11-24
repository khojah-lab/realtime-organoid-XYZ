"""
hardware/camera.py
────────────────────────────────────────────────────────────────
Single-owner Picamera2 capture loop and read-only frame consumers.
Only `_capture_loop` interacts with `picam2` while the server runs;
MJPEG streaming, organoid detection, and plate scanning read or
wait on `_frame_cond` without contending for the hardware device.
────────────────────────────────────────────────────────────────
"""

import threading
import time
import cv2
import numpy as np

from config import (
    CAMERA_MAIN_SIZE,
    CAMERA_BUFFER_COUNT,
    CAPTURE_INTERVAL_SEC,
    STREAM_INTERVAL_SEC,
    STREAM_JPEG_QUALITY,
    CAMERA_REQUEST_TIMEOUT_SEC,
    CAMERA_STALL_TIMEOUT_SEC,
    CAMERA_MAX_FAILURES_BEFORE_RESTART,
)
from services.telemetry import log_event

# ── Camera Hardware Initialization ────────────────────────────
picam2 = None
_Picamera2_cls = None
_startup_monotonic = time.monotonic()

_latest_frame: np.ndarray | None = None
_latest_jpeg: bytes | None = None
_latest_frame_time: float = 0.0
_latest_frame_seq: int = 0

_frame_lock = threading.RLock()
_frame_cond = threading.Condition(_frame_lock)
_camera_lock = threading.Lock()

_capture_thread_started = False
_consecutive_failures = 0
_recovery_count = 0


def _configure_and_start(cam) -> dict:
    """Configure a single `main` stream (`1024x1024`) and start `cam`."""
    cfg = cam.create_video_configuration(
        main={"size": CAMERA_MAIN_SIZE},
        buffer_count=CAMERA_BUFFER_COUNT,
    )
    cam.configure(cfg)
    cam.start()
    return cfg


def _close_camera(cam) -> None:
    if cam is None:
        return
    for method in ("stop", "close"):
        try:
            getattr(cam, method, lambda: None)()
        except Exception:
            pass


def _reinit_camera_locked() -> bool:
    """Close any wedged Picamera2 instance and recreate it from scratch."""
    global picam2, _recovery_count
    if _Picamera2_cls is None:
        return False

    _recovery_count += 1
    print(f"[CAMERA] Re-initializing camera pipeline (#{_recovery_count})...")
    log_event(f"CAMERA_RECOVERY_ATTEMPT_{_recovery_count}")

    _close_camera(picam2)
    picam2 = None

    new_cam = None
    try:
        time.sleep(0.5)
        new_cam = _Picamera2_cls()
        _configure_and_start(new_cam)
        time.sleep(0.5)
        picam2 = new_cam
        print(f"[CAMERA] ✓ Camera pipeline ready (#{_recovery_count})")
        log_event("CAMERA_RECOVERY_SUCCESS")
        return True
    except Exception as e:
        print(f"[CAMERA] ✗ Camera re-initialization failed: {e}")
        _close_camera(new_cam)
        log_event("CAMERA_RECOVERY_FAILED")
        return False


try:
    from picamera2 import Picamera2 as _Picamera2_cls

    picam2 = _Picamera2_cls()
    _configure_and_start(picam2)
    time.sleep(1.0)
except Exception as e:
    print(f"[WARNING] Camera not available: {e}")
    _close_camera(picam2)
    picam2 = None


# ── Health & Status Queries ───────────────────────────────────
def is_camera_connected() -> bool:
    """Return True if Picamera2 is initialized."""
    return picam2 is not None


def is_camera_streaming() -> bool:
    """Return True if frames are arriving within `CAMERA_STALL_TIMEOUT_SEC`."""
    if picam2 is None:
        return False
    now = time.monotonic()
    with _frame_lock:
        last_time = _latest_frame_time
    if last_time == 0.0:
        return (now - _startup_monotonic) < (CAMERA_STALL_TIMEOUT_SEC + 3.0)
    return (now - last_time) <= CAMERA_STALL_TIMEOUT_SEC


def get_camera_status() -> dict:
    """Return live camera health metrics for `/hardware_status` and UI watchdog."""
    now = time.monotonic()
    with _frame_lock:
        seq = _latest_frame_seq
        last_time = _latest_frame_time
    age = (now - last_time) if last_time > 0.0 else None
    return {
        "connected": is_camera_connected(),
        "streaming": is_camera_streaming(),
        "frame_seq": seq,
        "frame_age_sec": round(age, 2) if age is not None else None,
        "recoveries": _recovery_count,
    }


# ── Single-Owner Capture & Frame Consumers ────────────────────
def capture_bgr_frame(timeout: float = CAMERA_REQUEST_TIMEOUT_SEC) -> np.ndarray | None:
    """
    Capture one oriented BGR frame from `picam2`.
    Uses `picam2.capture_array("main")` so Picamera2 releases the underlying
    DMA buffer internally before returning.
    """
    global _consecutive_failures
    if picam2 is None and _Picamera2_cls is None:
        return None

    if not _camera_lock.acquire(timeout=timeout + 1.0):
        return None

    try:
        if picam2 is None and not _reinit_camera_locked():
            return None

        try:
            if hasattr(picam2, "capture_array"):
                raw = picam2.capture_array("main")
            else:
                req = picam2.capture_request()
                try:
                    raw = req.make_array("main")
                finally:
                    req.release()

            if raw is None:
                raise RuntimeError("Camera returned empty frame")

            _consecutive_failures = 0
            color_code = cv2.COLOR_RGBA2BGR if (raw.ndim == 3 and raw.shape[2] == 4) else cv2.COLOR_RGB2BGR
            frame = cv2.cvtColor(raw, color_code)
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            return cv2.flip(frame, 0)

        except Exception as e:
            _consecutive_failures += 1
            print(f"[CAMERA] Capture error ({_consecutive_failures}/{CAMERA_MAX_FAILURES_BEFORE_RESTART}): {e}")
            if _consecutive_failures >= CAMERA_MAX_FAILURES_BEFORE_RESTART:
                _consecutive_failures = 0
                _reinit_camera_locked()
            return None
    finally:
        _camera_lock.release()


def get_latest_frame() -> np.ndarray | None:
    """Return a thread-safe copy of the most recent frame from `_capture_loop`."""
    with _frame_lock:
        return _latest_frame.copy() if _latest_frame is not None else None


def capture_fresh_bgr_frame(
    max_age_sec: float = 0.25,
    wait_timeout_sec: float = CAMERA_STALL_TIMEOUT_SEC,
) -> np.ndarray | None:
    """
    Return a fresh BGR frame for scanning/analysis by waiting on `_frame_cond`
    published by `_capture_loop` (never touching `picam2` directly when the
    capture thread is running).
    """
    if not _capture_thread_started:
        return capture_bgr_frame(timeout=wait_timeout_sec)

    deadline = time.monotonic() + wait_timeout_sec
    with _frame_cond:
        start_seq = _latest_frame_seq
        while True:
            now = time.monotonic()
            if (
                _latest_frame is not None
                and _latest_frame_time > 0.0
                and ((now - _latest_frame_time) <= max_age_sec or _latest_frame_seq > start_seq)
            ):
                return _latest_frame.copy()

            remaining = deadline - now
            if remaining <= 0:
                return _latest_frame.copy() if _latest_frame is not None else None
            _frame_cond.wait(timeout=min(remaining, 0.25))


def _capture_loop() -> None:
    """Single-owner background loop that updates `_latest_frame` and `_latest_jpeg`."""
    global _latest_frame, _latest_jpeg, _latest_frame_time, _latest_frame_seq
    if picam2 is None and _Picamera2_cls is None:
        return

    while True:
        frame = capture_bgr_frame()
        if frame is not None:
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
            jpeg_bytes = buf.tobytes() if ok else None
            with _frame_cond:
                _latest_frame = frame
                if jpeg_bytes is not None:
                    _latest_jpeg = jpeg_bytes
                _latest_frame_time = time.monotonic()
                _latest_frame_seq += 1
                _frame_cond.notify_all()
            time.sleep(CAPTURE_INTERVAL_SEC)
        else:
            time.sleep(0.25)


def start_camera_capture_thread() -> None:
    """Start the background frame capture thread once."""
    global _capture_thread_started
    if _capture_thread_started:
        return
    _capture_thread_started = True
    threading.Thread(target=_capture_loop, daemon=True, name="CameraCaptureLoop").start()


def generate_mjpeg_frames():
    """Yield multipart MJPEG frames whenever `_latest_frame_seq` advances."""
    last_sent_seq = -1
    try:
        while True:
            with _frame_cond:
                if _latest_jpeg is None or _latest_frame_seq == last_sent_seq:
                    _frame_cond.wait(timeout=1.0)
                jpeg_bytes = _latest_jpeg
                current_seq = _latest_frame_seq

            if jpeg_bytes is None or current_seq == last_sent_seq:
                continue

            last_sent_seq = current_seq
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
            time.sleep(STREAM_INTERVAL_SEC)
    except (GeneratorExit, BrokenPipeError, ConnectionResetError):
        return
