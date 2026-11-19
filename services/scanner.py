"""
services/scanner.py
────────────────────────────────────────────────────────────────
Automated 6-well plate scanning workflow and hourly scan scheduler.
Coordinates stage movement, LED illumination, image capture, and
real-time UI status updates.
────────────────────────────────────────────────────────────────
"""

import datetime
import json
import re
import threading
import time
import cv2
import pytz

from config import (
    AUTO_SCAN_ENABLED,
    BASE_DIR,
    LA_TZ,
    CAPTURE_JPEG_QUALITY,
    CHAMBER_NAMES,
)
from hardware.camera import capture_fresh_bgr_frame
from hardware.gpio_control import set_led
from services.stage_navigator import get_navigator
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


def reserve_scan(mode):
    global _active_cancel
    with _scan_lock:
        if _active_cancel is not None:
            return None
        _active_cancel = threading.Event()
        scan_status.update(running=True, mode=mode, stopping=False, current_step="Starting scan...")
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
        scan_status.update(running=False, mode=None, stopping=False)
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
    cancel = reserve_scan("six_chamber")
    if cancel is None:
        return
    _run_reserved_scan(cancel)


def _run_reserved_scan(cancel):
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
            finish_scan_status(cancel, "Six-chamber scan stopped.")


def _run_scan(drive_session, cancel) -> None:
    """Execute a full 6-chamber automated scan while keeping the camera stream active."""
    nav = get_navigator()
    if nav.state["position_uncertain"]:
        raise ValueError("Stage position uncertain. Align to a known well and Sync before scanning.")
    # Capture filenames use "center"; navigation bookmarks use "middle".
    targets = {name: tuple(nav.bookmarks[name.replace("_center", "_middle")])
               for name in CHAMBER_NAMES}

    def move_to_chamber(name):
        x, y = targets[name]
        scan_status["current_step"] = f"Moving to {name} ({x}, {y})..."
        emit_socket_event("scan_status", scan_status)
        pos = nav.move_to(x, y, cancel=cancel)
        if cancel.is_set():
            return False
        if (pos["x"], pos["y"]) != (x, y):
            raise ValueError(f"Could not reach {name} at ({x}, {y}). Check the bookmark and stage limits.")
        return not cancel.wait(1.0)

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
                if cancel.is_set() or not move_to_chamber(chamber):
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

            if move_to_chamber("bottom_right"):
                print("  Returned to bottom_right")

        finally:
            set_led(False)
            emit_socket_event("led_state", {"state": False})
            print("  [LED] OFF after scan\n")

            now = datetime.datetime.now(LA_TZ)
            if not cancel.is_set():
                scan_status["last_scan"] = now.strftime("%Y-%m-%d %H:%M")
                scan_status["current_step"] = ""


_schedule_changed = threading.Condition()
_schedule_file = BASE_DIR / "state" / "scan_schedule.json"
_schedule = dict(enabled=AUTO_SCAN_ENABLED, start="00:00", end="23:59", interval=60)


def validate_schedule(data):
    if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
        raise ValueError("Choose whether the schedule is enabled.")
    for key in ("start", "end"):
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", str(data.get(key))):
            raise ValueError("Enter start and end times in HH:MM format.")
    minutes = data.get("interval")
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise ValueError("Interval must be a whole number from 1 to 1440 minutes.")
    return {key: data[key] for key in ("enabled", "start", "end", "interval")}


def get_schedule():
    with _schedule_changed:
        return dict(_schedule)


def save_schedule(data):
    global _schedule
    settings = validate_schedule(data)
    with _schedule_changed:
        _schedule_file.parent.mkdir(parents=True, exist_ok=True)
        temp = _schedule_file.with_suffix(".tmp")
        temp.write_text(json.dumps(settings), encoding="utf8")
        temp.replace(_schedule_file)
        _schedule = settings
        _schedule_changed.notify_all()
    return settings


def next_scan_time(settings, now):
    if not settings["enabled"]:
        return None
    def minutes(value):
        hour, minute = map(int, value.split(":"))
        return hour * 60 + minute

    start = minutes(settings["start"])
    span = (minutes(settings["end"]) - start) % 1440
    # Walk real minutes so nonexistent spring-forward times are skipped.
    candidate = now.astimezone(datetime.timezone.utc).replace(second=0, microsecond=0)
    while True:
        candidate += datetime.timedelta(minutes=1)
        local = candidate.astimezone(LA_TZ)
        offset = (local.hour * 60 + local.minute - start) % 1440
        if offset <= span and offset % settings["interval"] == 0:
            return local


def _scan_scheduler_loop():
    while True:
        with _schedule_changed:
            now = datetime.datetime.now(LA_TZ)
            due = next_scan_time(_schedule, now)
            scan_status["next_scan"] = due.strftime("%Y-%m-%d %H:%M %Z") if due else "—"
            scan_status["next_scan_iso"] = due.isoformat() if due else None
            emit_socket_event("scan_status", dict(scan_status))
            if due is None:
                _schedule_changed.wait()
                continue
            if _schedule_changed.wait(timeout=max(0, due.timestamp() - time.time())):
                continue
            cancel = reserve_scan("six_chamber")
        if cancel is not None:
            threading.Thread(target=_run_reserved_scan, args=(cancel,), daemon=True).start()


def start_scan_scheduler():
    global _scheduler_started, _schedule
    with _schedule_changed:
        if _scheduler_started:
            return
        try:
            _schedule = validate_schedule(json.loads(_schedule_file.read_text(encoding="utf8")))
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as exc:
            _schedule["enabled"] = False
            print(f"[SCAN] Schedule disabled: {exc}")
        _scheduler_started = True
        threading.Thread(target=_scan_scheduler_loop, daemon=True, name="ScanScheduler").start()
