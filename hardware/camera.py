"""
hardware/camera.py
────────────────────────────────────────────────────────────────
Manages the Picamera2 hardware stream, background frame buffer
loop with bounded request timeouts and automatic pipeline
recovery, MJPEG HTTP frame generator, and high-resolution still capture.
────────────────────────────────────────────────────────────────
"""

import threading
import time
import cv2
import numpy as np

from config import (
    CAMERA_MAIN_SIZE,
    CAMERA_LORES_SIZE,
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
_camera_config = None
_startup_monotonic = time.monotonic()


def _configure_and_start(cam) -> dict:
    """Create the dual-stream video configuration, configure `cam`, and start it."""
    cfg = cam.create_video_configuration(
        main={"size": CAMERA_MAIN_SIZE},   # high-quality capture stream
        lores={"size": CAMERA_LORES_SIZE}, # smooth web preview stream
        display="lores",
        buffer_count=CAMERA_BUFFER_COUNT,
    )
    cam.configure(cfg)
    cam.start()
    return cfg


try:
    from picamera2 import Picamera2 as _Picamera2_cls

    picam2 = _Picamera2_cls()
    _camera_config = _configure_and_start(picam2)
    time.sleep(2)
except Exception as e:
    print(f"[WARNING] Camera not available: {e}")
    picam2 = None

# ── Shared Frame Buffer, Watchdog State & Locks ───────────────
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


def is_camera_connected() -> bool:
    """Return True if Picamera2 initialized successfully."""
    return picam2 is not None


def is_camera_streaming() -> bool:
    """
    Return True if Picamera2 is initialized and frames are actively arriving
    within `CAMERA_STALL_TIMEOUT_SEC` (allowing a startup grace window).
    """
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
        "connected": picam2 is not None,
        "streaming": is_camera_streaming(),
        "frame_seq": seq,
        "frame_age_sec": round(age, 2) if age is not None else None,
        "recoveries": _recovery_count,
    }


def _restart_camera_locked() -> bool:
    """
    Attempt to recover a wedged Picamera2 / Unicam V4L2 pipeline while holding `_camera_lock`.
    First cycles `stop() -> configure() -> start()`, and falls back to recreating `Picamera2()`.
    """
    global picam2, _camera_config, _recovery_count
    if _Picamera2_cls is None:
        return False

    _recovery_count += 1
    print(f"[CAMERA] Attempting camera pipeline recovery #{_recovery_count}...")
    log_event(f"CAMERA_RECOVERY_ATTEMPT_{_recovery_count}")

    # Step 1: Try cycling stop() -> configure() -> start() on the existing instance
    if picam2 is not None:
        try:
            picam2.stop()
            time.sleep(0.3)
            _camera_config = _configure_and_start(picam2)
            time.sleep(0.5)
            print(f"[CAMERA] ✓ Camera pipeline restarted via stop/start (#{_recovery_count})")
            log_event("CAMERA_RECOVERY_SUCCESS")
            return True
        except Exception as e:
            print(f"[CAMERA] stop/start recovery failed ({e}); attempting full re-init...")
            try:
                if hasattr(picam2, "close"):
                    picam2.close()
            except Exception:
                pass
            picam2 = None

    # Step 2: Recreate the Picamera2 instance from scratch
    try:
        time.sleep(0.5)
        new_cam = _Picamera2_cls()
        _camera_config = _configure_and_start(new_cam)
        time.sleep(1.0)
        picam2 = new_cam
        print(f"[CAMERA] ✓ Camera pipeline re-initialized from scratch (#{_recovery_count})")
        log_event("CAMERA_RECOVERY_SUCCESS")
        return True
    except Exception as e:
        print(f"[CAMERA] ✗ Full camera re-initialization failed: {e}")
        log_event("CAMERA_RECOVERY_FAILED")
        return False


def capture_bgr_frame(timeout: float = CAMERA_REQUEST_TIMEOUT_SEC) -> np.ndarray | None:
    """
    Capture a fresh full-resolution frame from Picamera2 with a bounded timeout,
    always releasing the underlying DMA request buffer, and convert RGB -> BGR.
    Automatically restarts the camera pipeline after repeated timeouts/failures.
    """
    global _consecutive_failures
    if picam2 is None and _Picamera2_cls is None:
        return None

    if not _camera_lock.acquire(timeout=timeout + 1.0):
        print("[CAMERA] Timed out waiting to acquire _camera_lock")
        return None

    try:
        if picam2 is None:
            if not _restart_camera_locked():
                return None

        request = None
        try:
            if hasattr(picam2, "wait"):
                job = picam2.capture_request(wait=False)
                request = picam2.wait(job, timeout=timeout)
            else:
                request = picam2.capture_request()

            if request is None:
                raise TimeoutError("picam2.capture_request returned None")

            try:
                frame = request.make_array("main")
            finally:
                request.release()

            _consecutive_failures = 0

            #rotate + flip
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
            frame = cv2.flip(frame, 0)
            return frame

        except Exception as e:
            _consecutive_failures += 1
            print(
                f"[CAMERA] Capture error/timeout ({_consecutive_failures}/"
                f"{CAMERA_MAX_FAILURES_BEFORE_RESTART}): {e}"
            )
            if _consecutive_failures >= CAMERA_MAX_FAILURES_BEFORE_RESTART:
                _consecutive_failures = 0
                _restart_camera_locked()
            return None
    finally:
        _camera_lock.release()


def get_latest_frame() -> np.ndarray | None:
    """Return a thread-safe copy of the most recent frame from the buffer."""
    with _frame_lock:
        if _latest_frame is None:
            return None
        return _latest_frame.copy()


def capture_fresh_bgr_frame(
    max_age_sec: float = 0.25,
    wait_timeout_sec: float = CAMERA_REQUEST_TIMEOUT_SEC,
) -> np.ndarray | None:
    """
    Return a fresh BGR frame for scan/analysis without competing with `_capture_loop`
    for Picamera2 requests when the background capture thread is active.
    Waits for a frame newer than `max_age_sec` (or the next captured frame),
    and falls back to `capture_bgr_frame()` if the capture loop is not running.
    """
    if _capture_thread_started:
        deadline = time.monotonic() + wait_timeout_sec
        with _frame_cond:
            start_seq = _latest_frame_seq
            while True:
                now = time.monotonic()
                if (
                    _latest_frame is not None
                    and _latest_frame_time > 0.0
                    and (
                        (now - _latest_frame_time) <= max_age_sec
                        or _latest_frame_seq > start_seq
                    )
                ):
                    return _latest_frame.copy()

                remaining = deadline - now
                if remaining <= 0:
                    break
                _frame_cond.wait(timeout=min(remaining, 0.25))

    return capture_bgr_frame(timeout=wait_timeout_sec)


def _capture_loop() -> None:
    """Background daemon loop that continuously updates `_latest_frame` and `_latest_jpeg`."""
    global _latest_frame, _latest_jpeg, _latest_frame_time, _latest_frame_seq
    if picam2 is None and _Picamera2_cls is None:
        return

    while True:
        frame = capture_bgr_frame()
        if frame is not None:
            jpeg_bytes = None
            try:
                ret, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY],
                )
                if ret:
                    jpeg_bytes = buffer.tobytes()
            except Exception as e:
                print(f"[CAMERA] JPEG encoding error: {e}")

            with _frame_cond:
                _latest_frame = frame
                if jpeg_bytes is not None:
                    _latest_jpeg = jpeg_bytes
                _latest_frame_time = time.monotonic()
                _latest_frame_seq += 1
                _frame_cond.notify_all()
        else:
            time.sleep(0.1)

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
    Uses pre-encoded JPEG buffers and waits on `_frame_cond` so stalled streams
    do not spin-encode identical frames at 30 FPS.
    """
    last_sent_seq = -1

    while True:
        with _frame_cond:
            if _latest_jpeg is None or _latest_frame_seq == last_sent_seq:
                _frame_cond.wait(timeout=1.0)

            jpeg_bytes = _latest_jpeg
            current_seq = _latest_frame_seq

        if jpeg_bytes is None:
            time.sleep(0.05)
            continue

        last_sent_seq = current_seq
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
        )
        time.sleep(STREAM_INTERVAL_SEC)
