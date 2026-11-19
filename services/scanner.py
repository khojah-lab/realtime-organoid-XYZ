"""
services/scanner.py
────────────────────────────────────────────────────────────────
Automated 6-well plate scanning workflow and hourly scan scheduler.
Coordinates stage movement, LED illumination, image capture, and
real-time UI status updates.
────────────────────────────────────────────────────────────────
"""

import datetime
import threading
import time
import cv2
import pytz

from config import (
    AUTO_SCAN_ENABLED,
    LA_TZ,
    CAPTURE_JPEG_QUALITY,
    CHAMBER_NAMES,
    CHAMBER_MOVEMENTS,
    RETURN_HOME_MOVEMENTS,
)
from hardware.camera import capture_fresh_bgr_frame
from hardware.gpio_control import set_led
from hardware.stepper_motors import move_platform
from services import storage_manager
from services.telemetry import Timer, emit_socket_event, log_event

# ── Scan Status State (shared with UI) ────────────────────────
scan_status = {
    "running":      False,
    "last_scan":    "Never",
    "next_scan":    "Calculating..." if AUTO_SCAN_ENABLED else "—",
    "current_step": "",
}

_active_cancel = None
_scheduler_started = False
_scan_lock = threading.Lock()


def reserve_scan():
    global _active_cancel
    with _scan_lock:
        if _active_cancel is not None:
            return None
        _active_cancel = threading.Event()
        scan_status.update(running=True, stopping=False, current_step="Starting scan...")
        return _active_cancel


def request_scan_stop():
    with _scan_lock:
        if _active_cancel is not None:
            _active_cancel.set()
            scan_status["stopping"] = True
        return dict(scan_status)


def finish_scan_status(cancel, stopped_message):
    global _active_cancel
    with _scan_lock:
        if cancel.is_set():
            scan_status["current_step"] = stopped_message
        scan_status.update(running=False, stopping=False)
        _active_cancel = None
        emit_socket_event("scan_status", dict(scan_status))


def get_scan_status() -> dict:
    """Return a copy of the current scan status dictionary."""
    return dict(scan_status)


def take_scan_photo(chamber_name: str, drive_session=None) -> str | None:
    now = datetime.datetime.now(LA_TZ)
    name = f"{chamber_name}_{now.strftime('%Y%m%d_%H%M%S')}.jpg"
    try:
        frame = capture_fresh_bgr_frame()
        if frame is None:
            raise RuntimeError("Camera frame unavailable")
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, CAPTURE_JPEG_QUALITY])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        return storage_manager.capture(drive_session, name, now, encoded.tobytes())
    except Exception as exc:
        print(f"[SCAN] Capture failed: {exc}")
        return None


def run_scan() -> None:
    cancel = reserve_scan()
    if cancel is None:
        return
    sid = None
    try:
        sid = storage_manager.begin_scan()
        _run_scan(sid, cancel)
    except Exception as exc:
        scan_status["current_step"] = str(exc)
        emit_socket_event("scan_status", scan_status)
        print(f"[SCAN] {exc}")
    finally:
        try:
            if sid:
                storage_manager.finish_scan(sid)
        finally:
            finish_scan_status(cancel, "Scan stopped. Align the stage to bottom right before the next six-chamber scan.")


def _run_scan(drive_session, cancel) -> None:
    """Execute a full 6-chamber automated scan while keeping the camera stream active."""
    log_event("SCAN_START")
    scan_status["running"]      = True
    scan_status["current_step"] = "Starting scan..."
    emit_socket_event("scan_status", scan_status)

    set_led(True)
    emit_socket_event("led_state", {"state": True})
    print("  [LED] ON for scan")

    with Timer("FULL_SCAN"):
        try:
            scan_start     = time.time()
            captured_files = []

            print("=" * 45)
            print("  AUTOMATED CHAMBER SCAN — 6 chambers")
            print("=" * 45)

            for i, chamber in enumerate(CHAMBER_NAMES):
                if cancel.is_set():
                    return
                if CHAMBER_MOVEMENTS[i] is not None:
                    axis, direction, steps = CHAMBER_MOVEMENTS[i]
                    scan_status["current_step"] = f"Moving to {chamber}..."
                    emit_socket_event("scan_status", scan_status)
                    print(f"  Moving {axis.upper()} {direction} {steps} steps...")
                    move_platform(axis, direction, steps, cancel=cancel)
                    if cancel.wait(1.0):
                        return

                total = len(CHAMBER_NAMES)
                scan_status["current_step"] = f"Capturing {chamber} ({i+1}/{total})..."
                emit_socket_event("scan_status", scan_status)
                print(f"\n  Chamber {i+1}/{total}: {chamber}")
                if cancel.is_set():
                    return
                fname = take_scan_photo(chamber, drive_session)

                if fname:
                    captured_files.append(fname)
                    print(f"  ✓ Chamber {i+1} complete\n")
                else:
                    print(f"  ⚠ Chamber {i+1} photo failed\n")

            elapsed = time.time() - scan_start
            print(f"  Captures done: {len(captured_files)}/{len(CHAMBER_NAMES)} in {elapsed:.0f}s")

            print("\n" + "=" * 45)
            print("  RETURNING TO START POSITION (bottom_right)")
            print("=" * 45)

            scan_status["current_step"] = "Returning to start..."
            emit_socket_event("scan_status", scan_status)

            try:
                for axis, direction, steps in RETURN_HOME_MOVEMENTS:
                    print(f"  Moving {axis.upper()} {direction} {steps} steps...")
                    move_platform(axis, direction, steps, cancel=cancel)
                    if cancel.wait(1.0):
                        return
                print("  ✓ Returned to bottom_right\n")
            except Exception as e:
                print(f"  ✗ Return home error: {e}")

        finally:
            set_led(False)
            emit_socket_event("led_state", {"state": False})
            print("  [LED] OFF after scan\n")

            now = datetime.datetime.now(LA_TZ)
            if not cancel.is_set():
                scan_status["last_scan"] = now.strftime("%Y-%m-%d %H:%M")
                scan_status["current_step"] = ""


def _scan_scheduler_loop() -> None:
    """Background loop that triggers `run_scan()` at the top of every hour."""
    while True:
        now = datetime.datetime.now(LA_TZ)
        next_hr = (now + datetime.timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0
        )
        wait = (next_hr - now).total_seconds()
        scan_status["next_scan"] = next_hr.strftime("%Y-%m-%d %H:%M")
        emit_socket_event("scan_status", scan_status)
        print(f"[SCAN] Next scan at {scan_status['next_scan']} (in {wait/60:.1f} min)")
        time.sleep(wait)
        run_scan()


def start_scan_scheduler() -> None:
    """Start the hourly automated scan scheduler daemon thread once."""
    global _scheduler_started
    if not AUTO_SCAN_ENABLED:
        scan_status["next_scan"] = "—"
        print("[SCAN] Automatic hourly scan scheduler disabled (AUTO_SCAN_ENABLED=False).")
        return
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_scan_scheduler_loop, daemon=True, name="ScanScheduler").start()
