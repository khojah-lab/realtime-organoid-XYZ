"""
hardware/__init__.py
────────────────────────────────────────────────────────────────
Aggregates hardware connectivity status across camera, stepper
HATs, and DC motor HATs for the UI status banner.
────────────────────────────────────────────────────────────────
"""

from hardware.camera import is_camera_connected
from hardware.stepper_motors import kit1, kit2
from hardware.dc_motors import is_dc_hat_connected


def get_disconnected_hardware() -> list[str]:
    """Return a list of human-readable names for any disconnected peripherals."""
    disconnected = []
    if kit1 is None:
        disconnected.append("Z-Axis Stepper HAT (0x60)")
    if kit2 is None:
        disconnected.append("XY-Platform Stepper HAT (0x61)")
    if not is_dc_hat_connected():
        disconnected.append("DC Motor HAT (0x63)")
    if not is_camera_connected():
        disconnected.append("Camera (Picamera2)")
    return disconnected
