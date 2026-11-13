"""
config.py
────────────────────────────────────────────────────────────────
Central configuration, directory paths, hardware pin/address
mappings, and scan parameters for the XYZ Organoid Imaging System.
────────────────────────────────────────────────────────────────
"""

import os
from pathlib import Path
import pytz

# ── Timezone ──────────────────────────────────────────────────
LA_TZ = pytz.timezone("America/Los_Angeles")

# ── Directory & File Paths ────────────────────────────────────
# Defaults to the repository directory so the server can run on
# both the Raspberry Pi (/home/khojahlab/SpringXYZ) and local dev machines.
BASE_DIR = Path(
    os.getenv("SPRINGXYZ_BASE_DIR")
    or os.getenv("XYZ_BASE_DIR")
    or Path(__file__).resolve().parent
)

IMAGE_DIR             = BASE_DIR / "images"
IMAGES_UPLOAD_DIR     = BASE_DIR / "images_upload"
IMAGES_DOWNLOADED_DIR = BASE_DIR / "images_downloaded"
LOG_DIR               = BASE_DIR / "logs"
LOG_FILE              = LOG_DIR / "actions.csv"

MODEL_DIR             = BASE_DIR / "my_model"
SAVED_MODEL_DIR       = MODEL_DIR / "saved_model"
LABEL_MAP_PATH        = BASE_DIR / "label_map.pbtxt"

# Ensure runtime directories exist
for _directory in (IMAGE_DIR, IMAGES_UPLOAD_DIR, IMAGES_DOWNLOADED_DIR, LOG_DIR):
    os.makedirs(_directory, exist_ok=True)

# ── Server Settings ───────────────────────────────────────────
SECRET_KEY  = os.getenv("FLASK_SECRET_KEY", "microscopy_secret")
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "3000"))

# ── GPIO Pin Assignments (BCM Numbering) ──────────────────────
LIMIT_SWITCH_LR = 17
LIMIT_SWITCH_UD = 27
LED_PIN         = 18

# ── I2C Motor HAT Addresses ───────────────────────────────────
Z_STEPPER_HAT_ADDR  = 0x60   # Z axis (stepper1 + stepper2 in sync)
XY_STEPPER_HAT_ADDR = 0x61   # XY platform (stepper1 = X, stepper2 = Y)
DC_MOTOR_HAT_ADDR   = 0x63   # 4-channel DC shaker motors

# ── Camera Configuration ──────────────────────────────────────
CAMERA_MAIN_SIZE                   = (1024, 1024)   # High-quality capture stream
CAMERA_LORES_SIZE                  = (800, 800)     # Smooth web preview stream
CAMERA_BUFFER_COUNT                = 6
CAPTURE_INTERVAL_SEC               = 0.033          # ~30 FPS capture loop
STREAM_INTERVAL_SEC                = 0.030          # ~30 FPS MJPEG stream loop
STREAM_JPEG_QUALITY                = 80
CAPTURE_JPEG_QUALITY               = 90
CAMERA_REQUEST_TIMEOUT_SEC         = 2.5            # Bounded timeout per Picamera2 request
CAMERA_STALL_TIMEOUT_SEC           = 5.0            # Max frame age before stream is flagged stalled
CAMERA_MAX_FAILURES_BEFORE_RESTART = 2              # Consecutive timeouts before cycling Picamera2

# ── Stepper & 6-Well Scan Configuration ───────────────────────
DEFAULT_MANUAL_STEPS   = 50
STEPS_BETWEEN_CHAMBERS = 4000
STEP_DELAY             = 0.005

CHAMBER_NAMES = [
    "bottom_right",
    "bottom_center",
    "bottom_left",
    "top_left",
    "top_center",
    "top_right",
]

# Each entry is (axis, direction_str, steps) or None for the starting chamber
CHAMBER_MOVEMENTS = [
    None,
    ("x", "BACKWARD", STEPS_BETWEEN_CHAMBERS),
    ("x", "BACKWARD", STEPS_BETWEEN_CHAMBERS),
    ("y", "BACKWARD", STEPS_BETWEEN_CHAMBERS),
    ("x", "FORWARD",  STEPS_BETWEEN_CHAMBERS),
    ("x", "FORWARD",  STEPS_BETWEEN_CHAMBERS),
]

RETURN_HOME_MOVEMENTS = [
    ("y", "FORWARD", STEPS_BETWEEN_CHAMBERS),
]

# ── AWS S3 Cloud Storage Settings ─────────────────────────────
S3_BUCKET = os.getenv("XYZ_S3_BUCKET", "realtime-organoid-xyz-data")
S3_REGION = os.getenv("XYZ_S3_REGION", "us-east-2")

# Independent Google Drive backup (AWS configuration above is unchanged).
DRIVE_BACKUP_ENABLED = os.getenv("XYZ_DRIVE_BACKUP_ENABLED", "false").lower() in ("1", "true", "yes")
DRIVE_FOLDER_ID = os.getenv("XYZ_DRIVE_FOLDER_ID", "1ttE0_okxThWxGyPuAqLBbRuuzV2Gzxa5")
DRIVE_TOKEN_FILE = Path(os.getenv("XYZ_DRIVE_TOKEN_FILE", str(BASE_DIR / "drive_token.json")))
DRIVE_STATE_FILE = Path(os.getenv("XYZ_DRIVE_STATE_FILE", str(BASE_DIR / "drive_backup.sqlite3")))
DRIVE_BACKUP_INTERVAL = max(10, int(os.getenv("XYZ_DRIVE_BACKUP_INTERVAL", "60")))
