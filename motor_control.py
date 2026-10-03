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
kit1 = MotorKit(address=0x60)   # Z axis
kit2 = MotorKit(address=0x61)   # XY platform

# Exported so server.py move_platform() can use them directly
# without opening a second MotorKit instance at 0x61
x_motor = kit2.stepper1   # X axis — left / right
y_motor = kit2.stepper2   # Y axis — forward / backward


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
    kit1.stepper1.release()
    kit1.stepper2.release()
    kit2.stepper1.release()
    kit2.stepper2.release()


# ── Z axis (kit1) ─────────────────────────────────────────────
def move_up() -> None:
    do_steps([kit1.stepper1, kit1.stepper2], stepper.BACKWARD)


def move_down() -> None:
    do_steps([kit1.stepper1, kit1.stepper2], stepper.FORWARD)


# ── X axis (kit2 stepper1) ────────────────────────────────────
def move_left() -> None:
    do_steps([kit2.stepper1], stepper.BACKWARD)


def move_right() -> None:
    do_steps([kit2.stepper1], stepper.FORWARD)


# ── Y axis (kit2 stepper2) ────────────────────────────────────
# Note: forward/backward are intentionally swapped in server.py
#       to match the physical orientation of the stage.
def move_forward() -> None:
    do_steps([kit2.stepper2], stepper.FORWARD)


def move_backward() -> None:
    do_steps([kit2.stepper2], stepper.BACKWARD)