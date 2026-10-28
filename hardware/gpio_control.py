"""
hardware/gpio_control.py
────────────────────────────────────────────────────────────────
Manages Raspberry Pi GPIO pins for the illumination LED (BCM 18)
and hardware endstop limit switches (BCM 17, BCM 27).
Falls back gracefully when running outside a Raspberry Pi.
────────────────────────────────────────────────────────────────
"""

from config import LED_PIN, LIMIT_SWITCH_LR, LIMIT_SWITCH_UD

try:
    import RPi.GPIO as GPIO
    _GPIO_AVAILABLE = True
except (ImportError, RuntimeError) as e:
    print(f"[WARNING] RPi.GPIO not available ({e}) — running in simulated GPIO mode.")
    GPIO = None
    _GPIO_AVAILABLE = False

_led_state: bool = False
_initialized: bool = False


def init_gpio() -> None:
    """Configure BCM pin numbering, limit switch inputs, and LED output."""
    global _initialized, _led_state
    if _initialized:
        return

    if _GPIO_AVAILABLE and GPIO is not None:
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(LIMIT_SWITCH_LR, GPIO.IN)
            GPIO.setup(LIMIT_SWITCH_UD, GPIO.IN)
            GPIO.setup(LED_PIN, GPIO.OUT)
            GPIO.output(LED_PIN, GPIO.LOW)
        except Exception as e:
            print(f"[WARNING] Failed to configure GPIO pins: {e}")

    _led_state = False
    _initialized = True


def set_led(state: bool) -> bool:
    """Explicitly turn the illumination LED on (True) or off (False)."""
    global _led_state
    init_gpio()
    _led_state = bool(state)
    if _GPIO_AVAILABLE and GPIO is not None:
        try:
            GPIO.output(LED_PIN, GPIO.HIGH if _led_state else GPIO.LOW)
        except Exception as e:
            print(f"[WARNING] GPIO LED output error: {e}")
    return _led_state


def toggle_led() -> bool:
    """Toggle the illumination LED state and return the new state."""
    return set_led(not _led_state)


def get_led_state() -> bool:
    """Return current LED illumination state."""
    return _led_state


def cleanup_gpio() -> None:
    """Clean up GPIO hardware pins on server shutdown."""
    if _GPIO_AVAILABLE and GPIO is not None:
        try:
            GPIO.cleanup()
        except Exception as e:
            print(f"[WARNING] GPIO cleanup error: {e}")
