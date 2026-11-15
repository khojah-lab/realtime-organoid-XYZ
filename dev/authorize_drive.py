"""Authorize this desktop application, then transfer the private token to the Pi."""
import argparse
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DRIVE_TOKEN_FILE
from services.drive_backup import SCOPES, validate_destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-secret", default="drive_client_secret.json")
    args = parser.parse_args()
    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(args.client_secret, SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    target = Path(DRIVE_TOKEN_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    descriptor = os.open(str(temporary), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(credentials.to_json())
    os.replace(temporary, target)
    validate_destination()
    print("Authorized lab account and destination verified. No folders or images created.")
    print("Set a fixed XYZ_DRIVE_START_AT before enabling backup.")


if __name__ == "__main__":
    main()
