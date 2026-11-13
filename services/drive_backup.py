"""Independent backup of local originals. No AWS imports, reads or credentials."""
import datetime
import hashlib
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading

from config import (
    CHAMBER_NAMES, IMAGE_DIR, DRIVE_BACKUP_ENABLED, DRIVE_FOLDER_ID,
    DRIVE_TOKEN_FILE, DRIVE_STATE_FILE, DRIVE_BACKUP_INTERVAL,
)

log = logging.getLogger(__name__)
SCOPES = ["https://www.googleapis.com/auth/drive"]
NAME = re.compile(r"^(?P<well>" + "|".join(map(re.escape, CHAMBER_NAMES)) + r")_(?P<stamp>\d{8}_\d{6})\.jpg$")
FOLDER_MIME = "application/vnd.google-apps.folder"
_client_local = threading.local()
_run_lock = threading.Lock()
_start_lock = threading.Lock()
_started = False


def parse_name(name):
    match = NAME.fullmatch(name)
    if match:
        try:
            datetime.datetime.strptime(match["stamp"], "%Y%m%d_%H%M%S")
            return match["well"]
        except ValueError:
            pass
    return None


def get_client():
    client = getattr(_client_local, "client", None)
    if client is None:
        if not DRIVE_TOKEN_FILE.is_file():
            raise RuntimeError("Drive token missing; run dev/authorize_drive.py.")
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from google_auth_httplib2 import AuthorizedHttp
        import httplib2
        credentials = Credentials.from_authorized_user_file(str(DRIVE_TOKEN_FILE), SCOPES)
        # Bound network stalls, and never share an httplib2 client across threads.
        http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=60))
        client = build("drive", "v3", http=http, cache_discovery=False)
        _client_local.client = client
    return client


def quote(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def list_files(query):
    page_token = None
    while True:
        page = get_client().files().list(
            q="trashed = false and (" + query + ")",
            fields="nextPageToken,files(id,name,md5Checksum,size)",
            pageSize=1000, pageToken=page_token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute(num_retries=3)
        yield from page.get("files", [])
        page_token = page.get("nextPageToken")
        if not page_token:
            break


def well_folders():
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("XYZ_DRIVE_FOLDER_ID is empty.")
    folders = {}
    for item in list_files(f"'{quote(DRIVE_FOLDER_ID)}' in parents and mimeType = '{FOLDER_MIME}'"):
        if item["name"] in CHAMBER_NAMES:
            if item["name"] in folders:
                raise RuntimeError("Duplicate Drive well folder: " + item["name"])
            folders[item["name"]] = item["id"]
    for well in CHAMBER_NAMES:
        if well not in folders:
            item = get_client().files().create(
                body={"name": well, "parents": [DRIVE_FOLDER_ID], "mimeType": FOLDER_MIME},
                fields="id", supportsAllDrives=True,
            ).execute()
            folders[well] = item["id"]
    return folders


def checksum(path):
    digest = hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_one(path, folder, digest):
    """Recover an interrupted upload without silently duplicating or overwriting."""
    matches = list(list_files(f"'{quote(folder)}' in parents and name = '{quote(path.name)}'"))
    if matches:
        if len(matches) != 1 or matches[0].get("md5Checksum") != digest:
            raise RuntimeError("Drive name conflict; preserve both files for manual review.")
        return matches[0]["id"]
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(path), mimetype="image/jpeg", resumable=True)
    try:
        request = get_client().files().create(
            body={"name": path.name, "parents": [folder]},
            media_body=media, fields="id,md5Checksum", supportsAllDrives=True,
        )
        result = None
        while result is None:
            _, result = request.next_chunk(num_retries=3)
    finally:
        media.stream().close()
    if result.get("md5Checksum") != digest:
        raise RuntimeError("Drive checksum mismatch; backup remains pending.")
    return result["id"]


def backup_once(image_dir=IMAGE_DIR, state_file=DRIVE_STATE_FILE):
    """Scan local originals, record verified uploads, never delete local/AWS files."""
    stats = {"uploaded": 0, "skipped": 0, "failed": 0}
    if not _run_lock.acquire(blocking=False):
        return stats
    connection = None
    try:
        state_file = Path(state_file)
        state_file.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(state_file), timeout=30)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS uploaded (target TEXT, path TEXT, size INTEGER, "
            "mtime_ns INTEGER, md5 TEXT, file_id TEXT, PRIMARY KEY(target,path))"
        )
        folders = None
        for path in sorted(Path(image_dir).rglob("*.jpg")):
            well = parse_name(path.name)
            if not well or path.is_symlink():
                continue
            try:
                before = path.stat()
                identity = str(path.resolve())
                row = connection.execute(
                    "SELECT size,mtime_ns FROM uploaded WHERE target=? AND path=?",
                    (DRIVE_FOLDER_ID, identity),
                ).fetchone()
                if row == (before.st_size, before.st_mtime_ns):
                    stats["skipped"] += 1
                    continue
                digest = checksum(path)
                if folders is None:
                    folders = well_folders()
                file_id = upload_one(path, folders[well], digest)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise RuntimeError("Local capture changed during upload; will retry.")
                connection.execute(
                    "INSERT OR REPLACE INTO uploaded VALUES (?,?,?,?,?,?)",
                    (DRIVE_FOLDER_ID, identity, before.st_size, before.st_mtime_ns, digest, file_id),
                )
                connection.commit()
                stats["uploaded"] += 1
                log.info("Drive verified: %s", path.name)
            except Exception:
                stats["failed"] += 1
                log.exception("Drive backup pending: %s", path.name)
                # An authorization/folder outage affects every file; retry next cycle.
                if folders is None:
                    break
    finally:
        if connection is not None:
            connection.close()
        _run_lock.release()
    return stats


def start_drive_backup():
    """Optional worker; missing SDK/auth never prevents the main server starting."""
    global _started
    if not DRIVE_BACKUP_ENABLED:
        return
    with _start_lock:
        if _started:
            return
        _started = True

    def work():
        import time
        while True:
            try:
                stats = backup_once()
                log.info("Drive backup: %s", stats)
            except Exception:
                log.exception("Drive backup unavailable; local originals retained")
            time.sleep(DRIVE_BACKUP_INTERVAL)

    threading.Thread(target=work, daemon=True, name="IndependentDriveBackup").start()
