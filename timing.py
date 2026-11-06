# timing.py
# Telemetry module for microscopy platform
# Logs events with timestamps, latency, and live websocket emission

import time
import datetime
import csv
import os
import pytz

LA_TZ = pytz.timezone("America/Los_Angeles")

BASE_DIR = os.environ.get("XYZ_BASE_DIR", "/home/khojahlab/SpringXYZ")
LOG_DIR  = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "actions.csv")
os.makedirs(LOG_DIR, exist_ok=True)

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "action", "latency_us"])

_socketio = None

def set_socketio(sio):
    """Call this in server.py after socketio = SocketIO(...) is created."""
    global _socketio
    _socketio = sio

def log_event(action: str, latency_us: int = None):
    """
    Log a named event with optional latency.
    - Prints to terminal
    - Appends to CSV
    - Emits to frontend via SocketIO if connected
    """
    now       = datetime.datetime.now(LA_TZ)
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    # Terminal output
    lat_str = f"{latency_us} us" if latency_us is not None else ""
    print(f"[TELEMETRY] {timestamp}  {action:<25} {lat_str}")

    # CSV append (open in 'a' mode so restarts never overwrite history)
    try:
        with open(LOG_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([timestamp, action, latency_us or ""])
    except Exception as e:
        print(f"[TELEMETRY] CSV write error: {e}")

    # Live frontend push
    if _socketio is not None:
        try:
            _socketio.emit('new_action', {
                "timestamp":  timestamp,
                "action":     action,
                "latency_us": latency_us,
            }, namespace='/')
        except Exception as e:
            print(f"[TELEMETRY] SocketIO emit error: {e}")

class Timer:
    """
    Wraps a block of code and logs its duration automatically.

    Usage:
        with Timer("IMAGE_CAPTURE"):
            subprocess.run(...)
    """
    def __init__(self, action: str):
        self.action = action
        self.start  = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed_us = int((time.perf_counter() - self.start) * 1_000_000)
        log_event(self.action, latency_us=elapsed_us)
