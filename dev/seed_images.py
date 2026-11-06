"""Create fake scan captures for trying the image browser without a Pi.

Usage: python dev/seed_images.py [days]
Writes to $XYZ_BASE_DIR/images (default: the same temp directory run_server.py uses).
"""
import datetime
import os
import sys
import tempfile

import cv2
import numpy as np

CHAMBERS = ["bottom_right", "bottom_center", "bottom_left", "top_left", "top_center", "top_right"]

base_dir  = os.environ.get("XYZ_BASE_DIR", os.path.join(tempfile.gettempdir(), "xyz_dev"))
image_dir = os.path.join(base_dir, "images")
days      = int(sys.argv[1]) if len(sys.argv) > 1 else 3
os.makedirs(image_dir, exist_ok=True)

random = np.random.default_rng(0)
today  = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
count  = 0
for day in range(days):
    for hour in range(0, 24, 3):
        scan_start = today - datetime.timedelta(days=day) - datetime.timedelta(hours=today.hour - hour)
        if scan_start > datetime.datetime.now():
            continue
        for index, chamber in enumerate(CHAMBERS):
            taken = scan_start + datetime.timedelta(seconds=25 * index + 5)
            frame = np.full((1024, 1024, 3), 35, np.uint8)
            for _ in range(8):
                center = tuple(int(v) for v in random.integers(100, 924, 2))
                cv2.circle(frame, center, int(random.integers(20, 70)), (110, 190, 150), -1)
            cv2.putText(frame, chamber, (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
            cv2.putText(frame, taken.strftime("%Y-%m-%d %H:%M:%S"), (30, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.1, (200, 200, 200), 2)
            cv2.imwrite(os.path.join(image_dir, f"{chamber}_{taken:%Y%m%d_%H%M%S}.jpg"), frame)
            count += 1
print(f"Wrote {count} images to {image_dir}")
