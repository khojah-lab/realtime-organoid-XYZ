"""
hardware/dc_motors.py
────────────────────────────────────────────────────────────────
Controls 6 GA12-N20 DC motors via an Adafruit DC+Stepper Motor
HAT at I²C address 0x63 (separate from the two stepper HATs at
0x60 and 0x61).

HARDWARE NOTE — the HAT has 4 output channels (M1–M4).
Wire your 6 motors like this:

  Channel 1 (M1) ──► Motor 1  (independent)
  Channel 2 (M2) ──► Motor 2  (independent)
  Channel 3 (M3) ──► Motor 3 + Motor 5 in parallel
  Channel 4 (M4) ──► Motor 4 + Motor 6 in parallel

Motors wired in parallel on the same channel share speed and
direction. Verify that the stall-current sum of each parallel
pair stays within the HAT's 1.2 A per-channel rating.
────────────────────────────────────────────────────────────────
"""

import threading
from config import DC_MOTOR_HAT_ADDR

try:
    from adafruit_motorkit import MotorKit
except ImportError as e:
    print(f"[WARNING] adafruit_motorkit not installed ({e}) — DC motors disabled.")
    MotorKit = None

# ── Hardware init ────────────────────────────────────────────
_kit_dc = None
if MotorKit is not None:
    try:
        _kit_dc = MotorKit(address=DC_MOTOR_HAT_ADDR)
    except Exception as e:
        print(f"[WARNING] DC MotorKit (0x{DC_MOTOR_HAT_ADDR:02x}) not found: {e}")
        _kit_dc = None

# Friendly channel ID → MotorKit motor object
MOTORS = {
    1: _kit_dc.motor1 if _kit_dc else None,
    2: _kit_dc.motor2 if _kit_dc else None,
    3: _kit_dc.motor3 if _kit_dc else None,   # also drives motor 5 (parallel)
    4: _kit_dc.motor4 if _kit_dc else None,   # also drives motor 6 (parallel)
}

# ── Internal state ───────────────────────────────────────────
# Tracks per-channel throttle so the UI can read live state.
_state = {mid: 0.0 for mid in MOTORS}

# Per-channel threading events for cancelling auto-stop timers.
_stop_events: dict[int, threading.Event] = {}


# ── Private helpers ──────────────────────────────────────────
def _cancel_timer(motor_id: int) -> None:
    """Cancel any pending auto-stop timer for this channel."""
    ev = _stop_events.get(motor_id)
    if ev:
        ev.set()
        del _stop_events[motor_id]


def _apply_throttle(motor_id: int, throttle: float) -> None:
    if MOTORS[motor_id] is not None:
        MOTORS[motor_id].throttle = throttle
    _state[motor_id] = throttle


# ── Public API ───────────────────────────────────────────────
def is_dc_hat_connected() -> bool:
    """Return True if the DC Motor HAT at 0x63 initialized successfully."""
    return _kit_dc is not None


def set_motor(
    motor_id: int,
    speed: float,
    direction: str = "FORWARD",
    duration: float = 0.0,
) -> None:
    """
    Run a single DC motor channel.

    Parameters
    ----------
    motor_id  : 1–4  (channel on the HAT)
    speed     : 0.0–1.0
    direction : "FORWARD" | "BACKWARD" | "STOP"
    duration  : seconds to run; 0 = run until explicitly stopped
    """
    if motor_id not in MOTORS:
        raise ValueError(f"motor_id must be 1–4, got {motor_id!r}")

    speed = max(0.0, min(1.0, float(speed)))
    _cancel_timer(motor_id)

    if direction == "STOP" or speed == 0.0:
        _apply_throttle(motor_id, 0.0)
        return

    throttle = speed if direction == "FORWARD" else -speed
    _apply_throttle(motor_id, throttle)

    if duration > 0:
        ev = threading.Event()
        _stop_events[motor_id] = ev

        def _auto_stop(mid=motor_id, e=ev):
            e.wait(timeout=duration)
            if not e.is_set():          # not cancelled by a new command
                _apply_throttle(mid, 0.0)

        threading.Thread(target=_auto_stop, daemon=True).start()


def set_all_motors(
    speed: float,
    direction: str = "FORWARD",
    duration: float = 0.0,
) -> None:
    """Run all 4 channels simultaneously at the same speed/direction."""
    for mid in MOTORS:
        set_motor(mid, speed, direction, duration)


def stop_motor(motor_id: int) -> None:
    """Immediately stop a single channel."""
    if motor_id in MOTORS:
        _cancel_timer(motor_id)
        _apply_throttle(motor_id, 0.0)


def stop_all_motors() -> None:
    """Immediately stop all channels."""
    for mid in MOTORS:
        stop_motor(mid)


def get_motor_states() -> dict[int, float]:
    """
    Return the current throttle for every channel.
    Returns dict like {1: 0.75, 2: -0.5, 3: 0.0, 4: 0.0}
    Positive = FORWARD, negative = BACKWARD, 0 = stopped.
    """
    return dict(_state)
