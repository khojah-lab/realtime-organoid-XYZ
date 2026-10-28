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
from services.telemetry import log_event

motion_bp = Blueprint("motion", __name__)


# ── XYZ Stepper Stage Controls ────────────────────────────────
@motion_bp.route("/up")
def up():
    log_event("MOVE_UP")
    threading.Thread(target=move_up, daemon=True).start()
    return "OK"


@motion_bp.route("/down")
def down():
    log_event("MOVE_DOWN")
    threading.Thread(target=move_down, daemon=True).start()
    return "OK"


@motion_bp.route("/left")
def left():
    log_event("MOVE_LEFT")
    threading.Thread(target=move_left, daemon=True).start()
    return "OK"


@motion_bp.route("/right")
def right():
    log_event("MOVE_RIGHT")
    threading.Thread(target=move_right, daemon=True).start()
    return "OK"


@motion_bp.route("/forward")
def forward():
    log_event("MOVE_FORWARD")
    # Y axis intentionally inverted to match physical stage orientation
    threading.Thread(target=move_backward, daemon=True).start()
    return "OK"


@motion_bp.route("/backward")
def backward():
    log_event("MOVE_BACKWARD")
    # Y axis intentionally inverted to match physical stage orientation
    threading.Thread(target=move_forward, daemon=True).start()
    return "OK"


@motion_bp.route("/stop")
def stop():
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

        print(f"[DC CH{ch}] speed={speed} dir={direction} dur={duration}s")
    except Exception as e:
        print(f"[DC MOTOR] Error: {e}")
        return str(e), 400
    return "OK"


@motion_bp.route("/dc_motor_stop")
def dc_motor_stop():
    """Immediately stop a single DC motor channel or all channels."""
    ch = request.args.get("ch")
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
    print("ZOOM/FOCUS ->", system_params["zoom"], system_params["focus"])
    return "OK"


@motion_bp.route("/autofocus")
@motion_bp.route("/autofocus_camera_from_html")
def autofocus():
    print("AUTOFOCUS REQUEST")
    return "OK"
