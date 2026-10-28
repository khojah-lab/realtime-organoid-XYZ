"""
services/telemetry.py
────────────────────────────────────────────────────────────────
Telemetry and Socket.IO event bridge for the microscopy platform.
Logs events with timestamps, latency, CSV persistence, and live
WebSocket emission.
────────────────────────────────────────────────────────────────
"""

import csv
import datetime
import os
import time
from config import LA_TZ, LOG_DIR, LOG_FILE

os.makedirs(LOG_DIR, exist_ok=True)

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "action", "latency_us"])

_socketio = None


def set_socketio(sio) -> None:
    """Register the Flask-SocketIO instance after app initialization."""
    global _socketio
    _socketio = sio


def emit_socket_event(event: str, payload: dict, namespace: str = "/") -> None:
    """Safely emit a Socket.IO event to connected clients if Socket.IO is initialized."""
    if _socketio is not None:
        try:
            _socketio.emit(event, payload, namespace=namespace)
        except Exception as e:
            print(f"[SOCKETIO] Emit error ({event}): {e}")


def log_event(action: str, latency_us: int | None = None) -> None:
    """
    Log a named event with optional latency.
    - Prints to terminal
    - Appends to logs/actions.csv
    - Emits 'new_action' to frontend via SocketIO if connected
    """
    now = datetime.datetime.now(LA_TZ)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    lat_str = f"{latency_us} us" if latency_us is not None else ""
    print(f"[TELEMETRY] {timestamp}  {action:<25} {lat_str}")

    # CSV append (open in 'a' mode so restarts never overwrite history)
    try:
        with open(LOG_FILE, "a", newline="") as f:
            csv.writer(f).writerow([timestamp, action, latency_us or ""])
    except Exception as e:
        print(f"[TELEMETRY] CSV write error: {e}")

    # Live frontend push
    emit_socket_event(
        "new_action",
        {
            "timestamp": timestamp,
            "action": action,
            "latency_us": latency_us,
        },
    )


class Timer:
    """
    Context manager that wraps a block of code and logs its duration in microseconds.

    Usage:
        with Timer("IMAGE_CAPTURE"):
            ...
    """

    def __init__(self, action: str):
        self.action = action
        self.start = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed_us = int((time.perf_counter() - self.start) * 1_000_000)
        log_event(self.action, latency_us=elapsed_us)
