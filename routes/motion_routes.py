"""
routes/motion_routes.py
────────────────────────────────────────────────────────────────
Routes for 3-axis (XYZ) stepper motor positioning, stage navigation
bookmarks, circular well scanning, DC shaker motor channels, and
camera zoom/focus/autofocus adjustments.
────────────────────────────────────────────────────────────────
"""

import datetime
import threading
import time
from flask import Blueprint, jsonify, request

from config import DEFAULT_MANUAL_STEPS, LA_TZ
from hardware.dc_motors import (
    get_motor_states,
    set_all_motors,
    set_motor,
    stop_all_motors,
    stop_motor as stop_motor_single,
)
from hardware.gpio_control import set_led
from hardware.stepper_motors import release_all
from routes.main_routes import system_params
from services.scanner import (get_scan_status, scan_status, take_scan_photo, reserve_scan,
                              request_scan_stop, finish_scan_status)
from services.stage_navigator import get_navigator
from services.telemetry import emit_socket_event, log_event

motion_bp = Blueprint("motion", __name__)

# Each request moves one short burst. The UI repeats requests while a button is
# held, so a burst is dropped if the same axis is still moving (otherwise two
# threads would step the same motor at once).
axis_locks = {"x": threading.Lock(), "y": threading.Lock(), "z": threading.Lock()}
nav_move_lock = threading.Lock()
active_goto = None  # (cancel, finished) events for the current navigation command


def cancel_goto():
    with nav_move_lock:
        if active_goto is not None:
            cancel, finished = active_goto
            cancel.set()
            return finished
    return None

MOVE_DIRECTIONS = {"up", "down", "left", "right", "forward", "backward"}


def _parse_steps() -> int:
    """Use the requested step count for both taps and hold repeats."""
    try:
        val = int(request.args.get("steps", DEFAULT_MANUAL_STEPS))
        return max(1, min(10000, abs(val)))
    except (ValueError, TypeError):
        return DEFAULT_MANUAL_STEPS


def start_move(axis: str, dx: int, dy: int, dz: int, event_name: str, delta_label: str):
    """
    Validate scan-running state, acquire the per-axis lock non-blocking,
    and run `StageNavigator.move_by` in a background daemon thread.
    """
    if get_scan_status()["running"] and not request.args.get("override"):
        if not request.args.get("repeat"):
            log_event(f"{event_name}_REJECTED  Scan in progress")
        return "SCAN_RUNNING", 409

    is_repeat = bool(request.args.get("repeat"))
    lock = axis_locks[axis]
    if not lock.acquire(blocking=False):
        return "BUSY"

    def run():
        t0 = time.perf_counter()
        try:
            nav = get_navigator()
            pos = nav.move_by(dx=dx, dy=dy, dz=dz)
            if not is_repeat:
                elapsed_us = int((time.perf_counter() - t0) * 1_000_000)
                log_event(
                    f"{event_name:<20} {delta_label} -> (X={pos['x']:+d}, Y={pos['y']:+d}, Z={pos['z']:+d})",
                    latency_us=elapsed_us,
                )
        finally:
            lock.release()

    threading.Thread(target=run, daemon=True).start()
    return "OK"


# ── XYZ Stepper Stage Controls (Tracked via StageNavigator) ───
@motion_bp.route("/up")
def up():
    s = _parse_steps()
    return start_move("z", 0, 0, s, "MOVE_UP", f"dz=+{s}")


@motion_bp.route("/down")
def down():
    s = _parse_steps()
    return start_move("z", 0, 0, -s, "MOVE_DOWN", f"dz=-{s}")


@motion_bp.route("/left")
def left():
    s = _parse_steps()
    return start_move("x", -s, 0, 0, "MOVE_LEFT", f"dx=-{s}")


@motion_bp.route("/right")
def right():
    s = _parse_steps()
    return start_move("x", s, 0, 0, "MOVE_RIGHT", f"dx=+{s}")


@motion_bp.route("/forward")
def forward():
    # +Y moves from bottom row toward top row (stepper.BACKWARD inside StageNavigator)
    s = _parse_steps()
    return start_move("y", 0, s, 0, "MOVE_FORWARD", f"dy=+{s}")


@motion_bp.route("/backward")
def backward():
    # -Y moves from top row toward bottom row (stepper.FORWARD inside StageNavigator)
    s = _parse_steps()
    return start_move("y", 0, -s, 0, "MOVE_BACKWARD", f"dy=-{s}")


@motion_bp.route("/move_hold_end")
def move_hold_end():
    """Reported by the UI when an arrow is released after a hold (not for single taps)."""
    direction = request.args.get("direction", "")
    if direction not in MOVE_DIRECTIONS:
        return "Unknown direction", 400
    try:
        seconds = float(request.args.get("seconds", 0))
        bursts  = int(request.args.get("bursts", 0))
    except ValueError:
        return "Bad number", 400
    pos = get_navigator().pos
    log_event(
        f"MOVE_{direction.upper()}_HELD     {bursts} bursts ({seconds:.1f}s) -> "
        f"(X={pos['x']:+d}, Y={pos['y']:+d}, Z={pos['z']:+d})"
    )
    return "OK"


@motion_bp.route("/stop")
def stop():
    if cancel_goto() is not None:
        return "OK"
    release_all()
    pos = get_navigator().pos
    log_event(f"STOP_STEPPERS        Coils released @ (X={pos['x']:+d}, Y={pos['y']:+d}, Z={pos['z']:+d})")
    return "OK"


# ── Stage Navigation & Circular Scan UI Endpoints ─────────────
@motion_bp.route("/nav/state", methods=["GET"])
def nav_state():
    """Return current StageNavigator state (position, bookmarks, soft_limits, geometry)."""
    return jsonify(get_navigator().get_public_state())


@motion_bp.route("/nav/zero", methods=["POST"])
def nav_zero():
    """Set current position as (0, 0, 0) (`bottom_left` landmark) and clear uncertainty."""
    nav = get_navigator()
    pos = nav.set_origin()
    log_event(f"NAV_ZERO             Origin set -> (X={pos['x']:+d}, Y={pos['y']:+d}, Z={pos['z']:+d})")
    return jsonify(nav.get_public_state())


@motion_bp.route("/nav/reset_to", methods=["POST"])
def nav_reset_to():
    """Override software (X, Y) coordinates to a bookmark without moving the motors."""
    data = request.get_json(silent=True) or request.form or request.args
    name = (data.get("name") or "").strip()
    nav = get_navigator()
    if name not in nav.bookmarks:
        return jsonify({"error": f"Unknown bookmark '{name}'"}), 400
    pos = nav.force_sync_to_bookmark(name)
    log_event(
        f"NAV_SYNC             Synced to {name} -> (X={pos['x']:+d}, Y={pos['y']:+d}) [no motion]"
    )
    return jsonify(nav.get_public_state())


@motion_bp.route("/nav/mark", methods=["POST"])
def nav_mark():
    """Save or overwrite a bookmark with current (X, Y) or explicit coordinates."""
    data = request.get_json(silent=True) or request.form or request.args
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Bookmark name required"}), 400
    nav = get_navigator()
    x = int(data["x"]) if "x" in data and data["x"] not in (None, "") else None
    y = int(data["y"]) if "y" in data and data["y"] not in (None, "") else None
    coords = nav.set_bookmark(name, x=x, y=y)
    log_event(f"NAV_MARK             {name} = (X={coords[0]:+d}, Y={coords[1]:+d})")
    return jsonify(nav.get_public_state())


@motion_bp.route("/nav/config", methods=["POST"])
def nav_config():
    """Update soft limits and/or circular scan geometry."""
    data = request.get_json(silent=True) or request.form or request.args
    nav = get_navigator()
    try:
        if all(k in data for k in ("min_x", "max_x", "min_y", "max_y")):
            nav.set_soft_limits(
                int(data["min_x"]),
                int(data["max_x"]),
                int(data["min_y"]),
                int(data["max_y"]),
            )
            lims = nav.soft_limits
            log_event(
                f"NAV_LIMITS           X=[{lims['min_x']}, {lims['max_x']}] Y=[{lims['min_y']}, {lims['max_y']}]"
            )
        if all(k in data for k in ("well_radius_steps", "step_x", "step_y")):
            settle = float(data["move_settle_sec"]) if "move_settle_sec" in data else None
            nav.set_geometry(
                int(data["well_radius_steps"]),
                int(data["step_x"]),
                int(data["step_y"]),
                move_settle_sec=settle,
            )
            g = nav.geometry
            log_event(
                f"NAV_GEOMETRY         R={g['well_radius_steps']}, step=({g['step_x']}, {g['step_y']})"
            )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(nav.get_public_state())


@motion_bp.route("/nav/stop", methods=["POST"])
def nav_stop():
    finished = cancel_goto()
    if finished is None:
        return jsonify(status="idle")
    return jsonify(status="stopped" if finished.wait(timeout=2) else "stopping")


@motion_bp.route("/nav/goto", methods=["POST"])
def nav_goto():
    """Move stage to a named bookmark or explicit (x, y) coordinates in a background thread."""
    if get_scan_status()["running"]:
        log_event("NAV_GOTO_REJECTED    Scan in progress")
        return jsonify({"error": "Scan in progress"}), 409

    data = request.get_json(silent=True) or request.form or request.args
    nav = get_navigator()
    name = (data.get("name") or "").strip()

    if name:
        if name not in nav.bookmarks:
            return jsonify({"error": f"Unknown bookmark '{name}'"}), 400
        tx, ty = nav.bookmarks[name]
        label = name
    else:
        try:
            tx = int(data["x"])
            ty = int(data["y"])
            label = f"({tx}, {ty})"
        except (KeyError, ValueError, TypeError):
            return jsonify({"error": "Provide bookmark 'name' or integer 'x' and 'y'"}), 400

    global active_goto
    cancel = threading.Event()
    finished = threading.Event()
    with nav_move_lock:
        if active_goto is not None:
            return jsonify({"error": "Stage is already moving"}), 409
        active_goto = (cancel, finished)

    def run_goto():
        global active_goto
        t0 = time.perf_counter()
        try:
            pos = nav.move_to(tx, ty, cancel=cancel)
            event = "NAV_GOTO_STOPPED" if cancel.is_set() else "NAV_GOTO"
            elapsed_us = int((time.perf_counter() - t0) * 1_000_000)
            log_event(
                f"{event:<21}{label} -> (X={pos['x']:+d}, Y={pos['y']:+d})",
                latency_us=elapsed_us,
            )
        finally:
            with nav_move_lock:
                finished.set()
                active_goto = None

    try:
        threading.Thread(target=run_goto, daemon=True).start()
    except RuntimeError:
        with nav_move_lock:
            finished.set()
            active_goto = None
        raise
    return jsonify({"status": "moving", "target": [tx, ty], "label": label})


@motion_bp.route("/scan/stop", methods=["POST"])
def stop_scan():
    status = request_scan_stop()
    return jsonify(status)


@motion_bp.route("/nav/scan_well", methods=["POST"])
def nav_scan_well():
    """
    Execute a circular boustrophedon (snake) scan on a single bookmarked well,
    return to `(0, 0)` landmark, and emit `scan_verify_prompt` to the UI.
    """
    if get_scan_status()["running"]:
        return jsonify({"error": "A scan is already running"}), 409

    nav = get_navigator()
    if nav.state.get("position_uncertain"):
        log_event("SCAN_REJECTED        Stage position uncertain; zero or sync required")
        return jsonify({
            "error": "Stage position is marked UNCERTAIN after an interrupted move. Zero or Sync first."
        }), 409

    data = request.get_json(silent=True) or request.form or request.args
    well_name = (data.get("well") or "bottom_middle").strip()
    if well_name not in nav.bookmarks:
        return jsonify({"error": f"Unknown bookmark '{well_name}'"}), 400

    # Optional inline geometry override from UI inputs
    try:
        if all(k in data and data[k] not in (None, "") for k in ("radius", "step_x", "step_y")):
            nav.set_geometry(int(data["radius"]), int(data["step_x"]), int(data["step_y"]))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    cx, cy = nav.bookmarks[well_name]
    geom = nav.geometry
    tiles = nav.generate_circular_grid(
        center_x=cx,
        center_y=cy,
        radius=int(geom["well_radius_steps"]),
        step_x=int(geom["step_x"]),
        step_y=int(geom["step_y"]),
    )
    if not tiles:
        return jsonify({"error": "No tiles fit within circle and soft limits"}), 400

    cancel = reserve_scan("circular")
    if cancel is None:
        return jsonify({"error": "A scan is already running"}), 409

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
    return jsonify({"status": "started", "well": well_name, "tiles": len(tiles)})


@motion_bp.route("/nav/verify_landmark", methods=["POST"])
def nav_verify_landmark():
    """Log operator visual verification of the (0, 0) landmark after a scan."""
    data = request.get_json(silent=True) or request.form or request.args
    centered = str(data.get("centered", "true")).lower() in ("true", "1", "yes")
    pos = get_navigator().pos
    if centered:
        log_event(f"SCAN_VERIFY_OK       Landmark (0, 0) verified centered @ (X={pos['x']:+d}, Y={pos['y']:+d})")
    else:
        log_event(f"SCAN_VERIFY_DRIFT    Drift flagged at (0, 0) — jog onto landmark and click Zero (0,0)")
    return jsonify({"ok": True, "centered": centered})


# ── DC Shaker Motor Controls ──────────────────────────────────
@motion_bp.route("/update_parameters_motor")
def update_parameters_motor():
    """Run or stop all 4 DC motor channels simultaneously."""
    try:
        speed    = float(request.args.get("motorspeed", 0))
        duration = float(request.args.get("spin_dur", 0))
        flow_dir = request.args.get("flow_dir", "OFF").upper()

        system_params["motor_speed"]    = speed
        system_params["spin_duration"]  = duration
        system_params["flow_direction"] = flow_dir

        if flow_dir == "OFF":
            threading.Thread(target=stop_all_motors, daemon=True).start()
        else:
            direction = "FORWARD" if flow_dir in ("UP", "RIGHT") else "BACKWARD"
            threading.Thread(
                target=set_all_motors,
                args=(speed, direction, duration),
                daemon=True,
            ).start()

        log_event(f"DC_ALL_{flow_dir:<13} speed={speed} dur={duration}s")
        print(f"[MOTOR ALL] speed={speed} dir={flow_dir} dur={duration}s")
    except Exception as e:
        print(f"[MOTOR ALL] Error: {e}")
    return "OK"


@motion_bp.route("/dc_motor")
def dc_motor():
    """Control a single DC motor channel (1–4)."""
    try:
        ch        = int(request.args.get("ch", 1))
        speed     = float(request.args.get("speed", 0))
        direction = request.args.get("direction", "FORWARD").upper()
        duration  = float(request.args.get("duration", 0))

        threading.Thread(
            target=set_motor,
            args=(ch, speed, direction, duration),
            daemon=True,
        ).start()

        log_event(f"DC_CH{ch}_{direction:<13} speed={speed} dur={duration}s")
        print(f"[DC CH{ch}] speed={speed} dir={direction} dur={duration}s")
    except Exception as e:
        print(f"[DC MOTOR] Error: {e}")
        return str(e), 400
    return "OK"


@motion_bp.route("/dc_motor_stop")
def dc_motor_stop():
    """Immediately stop a single DC motor channel or all channels."""
    ch = request.args.get("ch")
    log_event(f"DC_CH{ch}_STOP" if ch else "DC_ALL_STOP")
    if ch:
        threading.Thread(target=stop_motor_single, args=(int(ch),), daemon=True).start()
    else:
        threading.Thread(target=stop_all_motors, daemon=True).start()
    return "OK"


@motion_bp.route("/dc_motor_states")
def dc_motor_states():
    """Return live per-channel DC motor throttle values."""
    return get_motor_states()


# ── Camera Zoom / Focus / Autofocus ───────────────────────────
@motion_bp.route("/update_parameters_zoom_focus")
def update_zoom_focus():
    system_params["zoom"]  = request.args.get("zoom", 0)
    system_params["focus"] = request.args.get("focus", 0)
    log_event(f"ZOOM_FOCUS           zoom={system_params['zoom']} focus={system_params['focus']}")
    print("ZOOM/FOCUS ->", system_params["zoom"], system_params["focus"])
    return "OK"


@motion_bp.route("/autofocus")
@motion_bp.route("/autofocus_camera_from_html")
def autofocus():
    log_event("AUTOFOCUS_REQUEST")
    print("AUTOFOCUS REQUEST")
    return "OK"
