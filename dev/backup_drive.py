"""Run one independent backup pass, without importing the web server or AWS."""
import argparse
import logging
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import IMAGE_DIR, DRIVE_STATE_FILE
from services.drive_backup import backup_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, default=IMAGE_DIR)
    parser.add_argument("--state", type=Path, default=DRIVE_STATE_FILE)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    stats = backup_once(args.images, args.state)
    print(stats)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
