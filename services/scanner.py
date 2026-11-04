"""
services/scanner.py
────────────────────────────────────────────────────────────────
Automated 6-well plate scanning workflow and hourly scan scheduler.
Coordinates stage movement, LED illumination, image capture, and
real-time UI status updates.
────────────────────────────────────────────────────────────────
"""

import datetime
import os
import shutil
import threading
import time
import cv2
import pytz

from config import (
    LA_TZ,
    IMAGE_DIR,
    IMAGES_UPLOAD_DIR,
    CAPTURE_JPEG_QUALITY,
    CHAMBER_NAMES,
    CHAMBER_MOVEMENTS,
    RETURN_HOME_MOVEMENTS,
)
from hardware.camera import capture_fresh_bgr_frame
from hardware.gpio_control import set_led
from hardware.stepper_motors import move_platform
from services.cloud_storage import upload_pending_images
from services.telemetry import Timer, emit_socket_event, log_event

# ── Scan Status State (shared with UI) ────────────────────────
scan_status = {
    "running":      False,
    "last_scan":    "Never",
    "next_scan":    "Calculating...",
    "current_step": "",
}

_scheduler_started = False


def get_scan_status() -> dict:
    """Return a copy of the current scan status dictionary."""
    return dict(scan_status)


def take_scan_photo(chamber_name: str) -> str | None:
    """
    Capture a high-resolution photo for `chamber_name`, save it to `images/`,
    and copy it to the hourly `images_upload/MM/DD/HH/` staging directory.
    """
    now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    now = now_utc.astimezone(LA_TZ)
    timestamp = now.strftime("%Y%m%d_%H%M%S")

    os.makedirs(IMAGE_DIR, exist_ok=True)
    local_path = os.path.join(IMAGE_DIR, f"{chamber_name}_{timestamp}.jpg")

    upload_dir = os.path.join(
        IMAGES_UPLOAD_DIR,
        str(now.month).zfill(2),
        str(now.day).zfill(2),
        str(now.hour).zfill(2),
    )
    os.makedirs(upload_dir, exist_ok=True)
    upload_path = os.path.join(upload_dir, f"{chamber_name}_{timestamp}.jpg")

    print(f"  [SCAN] Capturing {chamber_name}...")

    try:
        frame = capture_fresh_bgr_frame()
        if frame is None:
            print("  [SCAN] ✗ Camera frame unavailable")
            return None

        with Timer(f"CAPTURE_{chamber_name}"):
            success = cv2.imwrite(
                local_path,
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, CAPTURE_JPEG_QUALITY],
            )

        if success and os.path.exists(local_path):
            print(f"  [SCAN] ✓ {local_path} ({os.path.getsize(local_path)} bytes)")
            shutil.copy2(local_path, upload_path)
            return local_path
        else:
            print("  [SCAN] ✗ Failed to save image")
    except Exception as e:
        print(f"  [SCAN] ✗ Capture error: {e}")

    return None


def run_scan() -> None:
    """Execute a full 6-chamber automated scan while keeping the camera stream active."""
    if scan_status["running"]:
        print("[SCAN] Already running, skipping.")
        return

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
                if CHAMBER_MOVEMENTS[i] is not None:
                    axis, direction, steps = CHAMBER_MOVEMENTS[i]
                    scan_status["current_step"] = f"Moving to {chamber}..."
                    emit_socket_event("scan_status", scan_status)
                    print(f"  Moving {axis.upper()} {direction} {steps} steps...")
                    move_platform(axis, direction, steps)
                    time.sleep(1.0)

                total = len(CHAMBER_NAMES)
                scan_status["current_step"] = f"Capturing {chamber} ({i+1}/{total})..."
                emit_socket_event("scan_status", scan_status)
                print(f"\n  Chamber {i+1}/{total}: {chamber}")
                fname = take_scan_photo(chamber)

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
                    move_platform(axis, direction, steps)
                    time.sleep(1.0)
                print("  ✓ Returned to bottom_right\n")
            except Exception as e:
                print(f"  ✗ Return home error: {e}")

        finally:
            set_led(False)
            emit_socket_event("led_state", {"state": False})
            print("  [LED] OFF after scan\n")

            now = datetime.datetime.now(LA_TZ)
            scan_status["running"]      = False
            scan_status["last_scan"]    = now.strftime("%Y-%m-%d %H:%M")
            scan_status["current_step"] = ""
            emit_socket_event("scan_status", scan_status)
            print(f"  ✓ Scan complete at {scan_status['last_scan']}\n")

            threading.Thread(
                target=upload_pending_images,
                args=(str(IMAGES_UPLOAD_DIR),),
                daemon=True,
            ).start()


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
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(target=_scan_scheduler_loop, daemon=True, name="ScanScheduler").start()
