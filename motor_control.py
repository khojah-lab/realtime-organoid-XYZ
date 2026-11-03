"""
motor_control.py
────────────────────────────────────────────────────────────────
Stepper-motor control only.
DC motor logic lives in dc_motor_control.py.

HAT addresses
  kit1  0x60  — Z axis (up / down),  stepper1 + stepper2 in sync
  kit2  0x61  — XY platform,  stepper1 = X,  stepper2 = Y

x_motor and y_motor are exported so server.py can use them in
move_platform() without creating a second MotorKit at 0x61,
which would cause an I2C conflict.
────────────────────────────────────────────────────────────────
"""

import time
from adafruit_motorkit import MotorKit
from adafruit_motor import stepper

# ── Hardware init ─────────────────────────────────────────────
try:
    kit1 = MotorKit(address=0x60)   # Z axis
except Exception as e:
    print(f"[WARNING] Z-axis MotorKit (0x60) not found: {e}")
    kit1 = None

try:
    kit2 = MotorKit(address=0x61)   # XY platform
except Exception as e:
    print(f"[WARNING] XY-platform MotorKit (0x61) not found: {e}")
    kit2 = None

x_motor = kit2.stepper1 if kit2 else None   # X axis — left / right
y_motor = kit2.stepper2 if kit2 else None   # Y axis — forward / backward


# ── Shared step helper ────────────────────────────────────────
def do_steps(motors, direction, steps: int = 50, delay: float = 0.005) -> None:
    """Drive one or more stepper motor objects for a fixed number of steps."""
    for _ in range(steps):
        for m in motors:
            m.onestep(direction=direction, style=stepper.SINGLE)
        time.sleep(delay)


# ── Release ───────────────────────────────────────────────────
def release_all() -> None:
    """De-energise all stepper coils (reduces heat when idle)."""
    if kit1:
        kit1.stepper1.release()
        kit1.stepper2.release()
    if kit2:
        kit2.stepper1.release()
        kit2.stepper2.release()


# ── Z axis (kit1) ─────────────────────────────────────────────
def move_up() -> None:
    if kit1:
        do_steps([kit1.stepper1, kit1.stepper2], stepper.BACKWARD)


def move_down() -> None:
    if kit1:
        do_steps([kit1.stepper1, kit1.stepper2], stepper.FORWARD)


# ── X axis (kit2 stepper1) ────────────────────────────────────
def move_left() -> None:
    if kit2:
        do_steps([kit2.stepper1], stepper.BACKWARD)


def move_right() -> None:
    if kit2:
        do_steps([kit2.stepper1], stepper.FORWARD)


# ── Y axis (kit2 stepper2) ────────────────────────────────────
# Note: forward/backward are intentionally swapped in server.py
#       to match the physical orientation of the stage.
def move_forward() -> None:
    if kit2:
        do_steps([kit2.stepper2], stepper.FORWARD)


def move_backward() -> None:
    if kit2:
        do_steps([kit2.stepper2], stepper.BACKWARD)