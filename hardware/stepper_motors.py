"""
hardware/stepper_motors.py
────────────────────────────────────────────────────────────────
Stepper-motor control for the 3-axis stage.
DC motor logic lives in hardware/dc_motors.py.

HAT addresses:
  kit1  0x60  — Z axis (up / down), stepper1 + stepper2 in sync
  kit2  0x61  — XY platform, stepper1 = X, stepper2 = Y

x_motor and y_motor are shared with move_platform() so only a
single MotorKit instance is created at 0x61 (preventing I2C conflicts).
────────────────────────────────────────────────────────────────
"""

import time
from config import (
    Z_STEPPER_HAT_ADDR,
    XY_STEPPER_HAT_ADDR,
    DEFAULT_MANUAL_STEPS,
    STEP_DELAY,
)

try:
    from adafruit_motorkit import MotorKit
    from adafruit_motor import stepper
except ImportError as e:
    print(f"[WARNING] adafruit_motorkit/stepper not installed ({e}) — steppers disabled.")
    MotorKit = None
    stepper = None

# ── Hardware Initialization ───────────────────────────────────
kit1 = None
kit2 = None

if MotorKit is not None:
    try:
        kit1 = MotorKit(address=Z_STEPPER_HAT_ADDR)   # Z axis
    except Exception as e:
        print(f"[WARNING] Z-axis MotorKit (0x{Z_STEPPER_HAT_ADDR:02x}) not found: {e}")
        kit1 = None

    try:
        kit2 = MotorKit(address=XY_STEPPER_HAT_ADDR)  # XY platform
    except Exception as e:
        print(f"[WARNING] XY-platform MotorKit (0x{XY_STEPPER_HAT_ADDR:02x}) not found: {e}")
        kit2 = None

x_motor = kit2.stepper1 if kit2 else None   # X axis — left / right
y_motor = kit2.stepper2 if kit2 else None   # Y axis — forward / backward


def resolve_stepper_direction(direction) -> int | None:
    """Convert 'FORWARD'/'BACKWARD' string or stepper constant into adafruit stepper constant."""
    if stepper is None:
        return None
    if isinstance(direction, str):
        return stepper.FORWARD if direction.upper() == "FORWARD" else stepper.BACKWARD
    return direction


# ── Shared Step Helpers ───────────────────────────────────────
def do_steps(
    motors: list,
    direction,
    steps: int = DEFAULT_MANUAL_STEPS,
    delay: float = STEP_DELAY,
) -> None:
    """Drive one or more stepper motor objects for a fixed number of steps."""
    if stepper is None:
        return
    resolved_dir = resolve_stepper_direction(direction)
    for _ in range(steps):
        for m in motors:
            m.onestep(direction=resolved_dir, style=stepper.SINGLE)
        time.sleep(delay)


def move_platform(axis: str, direction, steps: int, delay: float = STEP_DELAY) -> None:
    """
    Move x_motor or y_motor a given number of steps and release the coil when done.
    Used during automated multi-well chamber scans.
    """
    motor = x_motor if axis.lower() == "x" else y_motor
    if motor is None or stepper is None:
        print(f"  [WARNING] {axis.upper()} motor not connected — skipping move.")
        return

    resolved_dir = resolve_stepper_direction(direction)
    for _ in range(steps):
        motor.onestep(direction=resolved_dir, style=stepper.SINGLE)
        time.sleep(delay)
    motor.release()


# ── Release ───────────────────────────────────────────────────
def release_all() -> None:
    """De-energise all stepper coils (reduces heat when idle)."""
    if kit1:
        kit1.stepper1.release()
        kit1.stepper2.release()
    if kit2:
        kit2.stepper1.release()
        kit2.stepper2.release()


# ── Z Axis (kit1) ─────────────────────────────────────────────
def move_up() -> None:
    if kit1 and stepper:
        do_steps([kit1.stepper1, kit1.stepper2], stepper.BACKWARD)


def move_down() -> None:
    if kit1 and stepper:
        do_steps([kit1.stepper1, kit1.stepper2], stepper.FORWARD)


# ── X Axis (kit2 stepper1) ────────────────────────────────────
def move_left() -> None:
    if kit2 and stepper:
        do_steps([kit2.stepper1], stepper.BACKWARD)


def move_right() -> None:
    if kit2 and stepper:
        do_steps([kit2.stepper1], stepper.FORWARD)


# ── Y Axis (kit2 stepper2) ────────────────────────────────────
# Note: forward/backward are intentionally swapped in routes/motion_routes.py
#       to match the physical orientation of the stage.
def move_forward() -> None:
    if kit2 and stepper:
        do_steps([kit2.stepper2], stepper.FORWARD)


def move_backward() -> None:
    if kit2 and stepper:
        do_steps([kit2.stepper2], stepper.BACKWARD)
