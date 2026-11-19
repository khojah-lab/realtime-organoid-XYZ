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


def start_circular_scan(data, *, remember_geometry=False):
    if get_scan_status()["running"]:
        return {"error": "A scan is already running"}, 409

    nav = get_navigator()
    if nav.state.get("position_uncertain"):
        log_event("SCAN_REJECTED        Stage position uncertain; zero or sync required")
        return {
            "error": "Stage position is marked UNCERTAIN after an interrupted move. Zero or Sync first."
        }, 409

    well_name = (data.get("well") or "bottom_middle").strip()
    if well_name not in nav.bookmarks:
        return {"error": f"Unknown bookmark '{well_name}'"}, 400

    geom = dict(nav.geometry)
    try:
        if all(k in data and data[k] not in (None, "") for k in ("radius", "step_x", "step_y")):
            radius, sx, sy = (int(data[k]) for k in ("radius", "step_x", "step_y"))
            if min(radius, sx, sy) < 1:
                raise ValueError("Radius and step sizes must be positive.")
            if remember_geometry:
                nav.set_geometry(radius, sx, sy)
            geom.update(well_radius_steps=radius, step_x=sx, step_y=sy)
    except ValueError as e:
        return {"error": str(e)}, 400

    cx, cy = nav.bookmarks[well_name]
    tiles = nav.generate_circular_grid(
        center_x=cx,
        center_y=cy,
        radius=int(geom["well_radius_steps"]),
        step_x=int(geom["step_x"]),
        step_y=int(geom["step_y"]),
    )
    if not tiles:
        return {"error": "No tiles fit within circle and soft limits"}, 400

    cancel = reserve_scan("circular")
    if cancel is None:
        return {"error": "A scan is already running"}, 409

    def run_circular_scan():
        t_start = time.perf_counter()
        scan_status["running"] = True
        scan_status["current_step"] = f"Starting circular scan on {well_name} ({len(tiles)} tiles)..."
        emit_socket_event("scan_status", scan_status)

        set_led(True)
        emit_socket_event("led_state", {"state": True})

        log_event(
            f"SCAN_WELL_START      {well_name} (R={geom['well_radius_steps']}, "
            f"step={geom['step_x']}x{geom['step_y']}, {len(tiles)} tiles)"
        )

        settle_sec = float(geom.get("move_settle_sec", 0.5))
        captured = 0

        try:
            for idx, tile in enumerate(tiles, 1):
                if cancel.is_set():
                    return
                tx, ty = tile["x"], tile["y"]
                r_idx, c_idx = tile["row"], tile["col"]
                scan_status["current_step"] = (
                    f"{well_name} tile {idx}/{len(tiles)} (r{r_idx:02d}_c{c_idx:02d}) @ ({tx:+d}, {ty:+d})"
                )
                emit_socket_event("scan_status", scan_status)

                t_tile = time.perf_counter()
                pos = nav.move_to(tx, ty, cancel=cancel)
                if cancel.wait(max(0, settle_sec)):
                    return

                tile_label = f"{well_name}_r{r_idx:02d}_c{c_idx:02d}"
                saved = take_scan_photo(tile_label)
                if saved:
                    captured += 1
                tile_us = int((time.perf_counter() - t_tile) * 1_000_000)
                log_event(
                    f"SCAN_TILE [{idx:02d}/{len(tiles):02d}]    {tile_label} @ (X={pos['x']:+d}, Y={pos['y']:+d})",
                    latency_us=tile_us,
                )

            scan_status["current_step"] = "Returning to (0, 0) landmark..."
            emit_socket_event("scan_status", scan_status)
            pos = nav.move_to(0, 0, cancel=cancel)
            if cancel.is_set():
                return
            total_us = int((time.perf_counter() - t_start) * 1_000_000)
            log_event(
                f"SCAN_RETURN_ZERO     Arrived at (X={pos['x']:+d}, Y={pos['y']:+d}) — "
                f"{captured}/{len(tiles)} tiles captured, awaiting landmark check",
                latency_us=total_us,
            )
            emit_socket_event(
                "scan_verify_prompt",
                {
                    "well": well_name,
                    "tiles_captured": captured,
                    "tiles_total": len(tiles),
                    "position": pos,
                },
            )
        finally:
            set_led(False)
            emit_socket_event("led_state", {"state": False})
            now = datetime.datetime.now(LA_TZ)
            if not cancel.is_set():
                scan_status["last_scan"] = now.strftime("%Y-%m-%d %H:%M")
                scan_status["current_step"] = ""

    def worker():
        try:
            run_circular_scan()
        finally:
            finish_scan_status(cancel, "Circular scan stopped.")

    try:
        threading.Thread(target=worker, daemon=True).start()
    except RuntimeError:
        finish_scan_status(cancel, "Scan could not start.")
        raise
    return {"status": "started", "well": well_name, "tiles": len(tiles)}, 200


_schedule_changed = threading.Condition()
_schedule_file = BASE_DIR / "state" / "scan_schedule.json"
_schedule = dict(enabled=AUTO_SCAN_ENABLED, mode="six_chamber", start="00:00", end="23:59", interval=60)


def validate_schedule(data):
    if not isinstance(data, dict) or type(data.get("enabled")) is not bool:
        raise ValueError("Choose whether the schedule is enabled.")
    for key in ("start", "end"):
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", str(data.get(key))):
            raise ValueError("Enter start and end times in HH:MM format.")
    minutes = data.get("interval")
    if type(minutes) is not int or not 1 <= minutes <= 1440:
        raise ValueError("Interval must be a whole number from 1 to 1440 minutes.")
    settings = {key: data[key] for key in ("enabled", "start", "end", "interval")}
    for key in ("start_date", "end_date"):
        value = data.get(key)
        if value not in (None, ""):
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError("Choose a valid calendar date.")
            datetime.date.fromisoformat(value)
            settings[key] = value
    if settings.get("end_date") and settings.get("start_date", "") > settings["end_date"]:
        raise ValueError("End date must be on or after the start date.")
    mode = data.get("mode", "six_chamber")
    if mode not in ("six_chamber", "circular"):
        raise ValueError("Select a scan mode.")
    settings["mode"] = mode
    if mode == "circular":
        params = data.get("circular")
        if not isinstance(params, dict) or not isinstance(params.get("well"), str) or not params["well"]:
            raise ValueError("Select a well for the circular scan.")
        for key in ("radius", "step_x", "step_y"):
            if type(params.get(key)) is not int or params[key] < 1:
                raise ValueError("Circular radius and step sizes must be positive whole numbers.")
        settings["circular"] = {k: params[k] for k in ("well", "radius", "step_x", "step_y")}
    return settings


def get_schedule():
    with _schedule_changed:
        return dict(_schedule)


def save_schedule(data):
    global _schedule
    settings = validate_schedule(data)
    if settings["enabled"] and settings.get("end_date") and next_scan_time(settings, datetime.datetime.now(LA_TZ)) is None:
        raise ValueError("No scan start remains within the selected dates and times.")
    with _schedule_changed:
        _schedule_file.parent.mkdir(parents=True, exist_ok=True)
        temp = _schedule_file.with_suffix(".tmp")
        temp.write_text(json.dumps(settings), encoding="utf8")
        temp.replace(_schedule_file)
        _schedule = settings
        _schedule_changed.notify_all()
    emit_socket_event("scan_schedule", settings)
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
    first = datetime.date.fromisoformat(settings["start_date"]) if settings.get("start_date") else None
    last = datetime.date.fromisoformat(settings["end_date"]) if settings.get("end_date") else None
    if first and now.astimezone(LA_TZ).date() < first:
        midnight = LA_TZ.localize(datetime.datetime.combine(first, datetime.time.min))
        candidate = midnight.astimezone(datetime.timezone.utc) - datetime.timedelta(minutes=1)
    while True:
        candidate += datetime.timedelta(minutes=1)
        local = candidate.astimezone(LA_TZ)
        if last and local.date() > last:
            return None
        minute = local.hour * 60 + local.minute
        if first and local.date() == first and minute < start:
            continue
        offset = (minute - start) % 1440
        if offset <= span and offset % settings["interval"] == 0:
            return local


def _scan_scheduler_loop():
    global _schedule
    while True:
        with _schedule_changed:
            now = datetime.datetime.now(LA_TZ)
            due = next_scan_time(_schedule, now)
            scan_status["next_scan"] = due.strftime("%Y-%m-%d %H:%M %Z") if due else "—"
            scan_status["next_scan_iso"] = due.isoformat() if due else None
            emit_socket_event("scan_status", dict(scan_status))
            if due is None:
                if _schedule["enabled"]:
                    # The final eligible slot has passed. Also applies after a restart.
                    _schedule = dict(_schedule, enabled=False)
                    emit_socket_event("scan_schedule", dict(_schedule))
                _schedule_changed.wait()
                continue
            if _schedule_changed.wait(timeout=max(0, due.timestamp() - time.time())):
                continue
            if _schedule["mode"] == "circular":
                try:
                    result, status = start_circular_scan(_schedule["circular"])
                    if status != 200:
                        log_event(f"Scheduled circular scan skipped: {result['error']}")
                except Exception as exc:
                    log_event(f"Scheduled circular scan failed: {exc!r}")
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
