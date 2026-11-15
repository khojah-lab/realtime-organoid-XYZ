"""Drive diagnostics only. Old bulk historical uploader is no longer a CLI action."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.drive_backup import validate_destination
from services.drive_spool import status

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        validate_destination()
        print('Lab account and destination verified. No photos uploaded or folders created.')
    else:
        print(json.dumps(status(), indent=2))
        print('Use the website to enable new scan backups. Run dev/drive_upload_worker.py via systemd.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
