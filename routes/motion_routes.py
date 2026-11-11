"""
routes/motion_routes.py
────────────────────────────────────────────────────────────────
Routes for 3-axis (XYZ) stepper motor positioning, DC shaker
motor channels, and camera zoom/focus/autofocus adjustments.
────────────────────────────────────────────────────────────────
"""

import threading
from flask import Blueprint, request
from hardware.dc_motors import (
    get_motor_states,
    set_all_motors,
    set_motor,
    stop_all_motors,
    stop_motor as stop_motor_single,
)
from hardware.stepper_motors import (
    move_backward,
    move_down,
    move_forward,
    move_left,
    move_right,
    move_up,
    release_all,
)
from routes.main_routes import system_params
from services.scanner import get_scan_status
from services.telemetry import log_event

motion_bp = Blueprint("motion", __name__)

# Each request moves one short burst. The UI repeats requests while a button is
# held, so a burst is dropped if the same axis is still moving (otherwise two
# threads would step the same motor at once).
axis_locks = {"x": threading.Lock(), "y": threading.Lock(), "z": threading.Lock()}

MOVE_DIRECTIONS = {"up", "down", "left", "right", "forward", "backward"}


def start_move(axis: str, move_function, event_name: str):
    """
    Validate scan-running state, acquire the per-axis lock non-blocking,
    and run `move_function` in a background daemon thread.
    """
    # Steppers have no position feedback, so a manual move during a scan
    # shifts every remaining chamber. The UI sends override=1 after confirmation.
    if get_scan_status()["running"] and not request.args.get("override"):
        if not request.args.get("repeat"):
            log_event(f"{event_name}_REJECTED_SCAN_RUNNING")
        return "SCAN_RUNNING", 409

    if not request.args.get("repeat"):
        log_event(event_name)

    lock = axis_locks[axis]
    if not lock.acquire(blocking=False):
        return "BUSY"

    def run():
        try:
            move_function()
        finally:
            lock.release()

    threading.Thread(target=run, daemon=True).start()
    return "OK"


# ── XYZ Stepper Stage Controls ────────────────────────────────
@motion_bp.route("/up")
def up():
    return start_move("z", move_up, "MOVE_UP")


@motion_bp.route("/down")
def down():
    return start_move("z", move_down, "MOVE_DOWN")


@motion_bp.route("/left")
def left():
    return start_move("x", move_left, "MOVE_LEFT")


@motion_bp.route("/right")
def right():
    return start_move("x", move_right, "MOVE_RIGHT")


@motion_bp.route("/forward")
def forward():
    # Y axis intentionally inverted to match physical stage orientation
    return start_move("y", move_backward, "MOVE_FORWARD")


@motion_bp.route("/backward")
def backward():
    # Y axis intentionally inverted to match physical stage orientation
    return start_move("y", move_forward, "MOVE_BACKWARD")


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
    log_event(f"MOVE_{direction.upper()}_HELD_{seconds:.1f}s_{bursts}_BURSTS")
    return "OK"


@motion_bp.route("/stop")
def stop():
    log_event("STOP_RELEASE_STEPPERS")
    release_all()
    return "OK"


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

        log_event(f"DC_ALL_{flow_dir}_SPEED_{speed}_DUR_{duration}s")
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

        log_event(f"DC_CH{ch}_{direction}_SPEED_{speed}_DUR_{duration}s")
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
    log_event(f"ZOOM_{system_params['zoom']}_FOCUS_{system_params['focus']}")
    print("ZOOM/FOCUS ->", system_params["zoom"], system_params["focus"])
    return "OK"


@motion_bp.route("/autofocus")
@motion_bp.route("/autofocus_camera_from_html")
def autofocus():
    log_event("AUTOFOCUS_REQUEST")
    print("AUTOFOCUS REQUEST")
    return "OK"
