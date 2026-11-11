"""
routes/main_routes.py
────────────────────────────────────────────────────────────────
Core UI routes: dashboard HTML, live MJPEG stream, LED toggle,
hardware connectivity status, and system parameter synchronization.
────────────────────────────────────────────────────────────────
"""

from flask import Blueprint, Response, jsonify, render_template
from hardware import get_disconnected_hardware
from hardware.camera import generate_mjpeg_frames, get_camera_status
from hardware.gpio_control import toggle_led
from services.scanner import get_scan_status
from services.telemetry import emit_socket_event, log_event

main_bp = Blueprint("main", __name__)

# Shared UI system parameters
system_params = {
    "zoom":           0,
    "focus":          0,
    "motor_speed":    0,
    "flow_direction": "OFF",
    "spin_duration":  0,
}


@main_bp.route("/")
def index():
    """Render the microscopy control dashboard."""
    return render_template("main.html")


@main_bp.route("/video")
def video():
    """Live multipart MJPEG stream from the microscope camera."""
    resp = Response(
        generate_mjpeg_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@main_bp.route("/led_toggle")
def led_toggle():
    """Toggle the sample illumination LED and log the action."""
    state = toggle_led()
    log_event("LED_ON" if state else "LED_OFF")
    emit_socket_event("led_state", {"state": state})
    return "1" if state else "0"


@main_bp.route("/hardware_status")
def hardware_status():
    """Return a JSON list of any disconnected hardware modules and live camera status."""
    return jsonify({
        "disconnected": get_disconnected_hardware(),
        "camera": get_camera_status(),
    })


@main_bp.route("/system_parameters")
@main_bp.route("/get_system_parameters_from_html")
def get_system_parameters():
    """Push current system parameters, scan status, and hardware status over Socket.IO."""
    emit_socket_event("system_parameters", {"data": system_params})
    emit_socket_event("system_parameters_to_html", {"data": {"data": system_params}})
    emit_socket_event("scan_status", get_scan_status())
    emit_socket_event(
        "hardware_status",
        {
            "disconnected": get_disconnected_hardware(),
            "camera": get_camera_status(),
        },
    )
    return "OK"
