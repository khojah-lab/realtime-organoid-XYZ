# Run with: python3 timing_data/test_timing.py
# This file is for testing accuracy and efficacy of the timing.
# Test 3 should show 500,000 us and 1,200,000 us if Timer is running
# accurately.

import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import LOG_FILE
from services.telemetry import Timer, log_event

print("=" * 45)
print("TEST 1: Basic log_event (no latency)")
print("=" * 45)
log_event("MOVE_LEFT")
log_event("LED_ON")
log_event("LED_OFF")

print()
print("=" * 45)
print("TEST 2: log_event with manual latency")
print("=" * 45)
log_event("MOVE_RIGHT", latency_us=82341)

print()
print("=" * 45)
print("TEST 3: Timer context manager")
print("=" * 45)
with Timer("FAKE_CAPTURE"):
    time.sleep(0.5)   # pretend this is rpicam-still

with Timer("FAKE_FULL_SCAN"):
    time.sleep(1.2)   # pretend this is run_scan()

print()
print("=" * 45)
print("TEST 4: Check CSV was written")
print("=" * 45)
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r") as f:
        rows = list(csv.reader(f))
    print(f"CSV ({LOG_FILE}) has {len(rows)} rows (including header):")
    for row in rows:
        print(" ", row)
else:
    print("ERROR: CSV file was not created!")

print()
print("NOTE: SocketIO emit skipped in this test (no Flask running)")
print("That part gets tested when you actually run server.py")
