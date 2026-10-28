"""
services/cloud_storage.py
────────────────────────────────────────────────────────────────
Unified OpenStack Swift cloud storage client and local zip
packaging for uploading and downloading historical microscopy images.
Consolidates:
  - archive/swiftCloudAuth.py
  - archive/image_download_script.py
  - image_upload_script.py
  - prepare_zip.py
────────────────────────────────────────────────────────────────
"""

import datetime
import os
import shutil
import time
from zipfile import ZipFile
import pytz

from config import (
    LA_TZ,
    IMAGES_UPLOAD_DIR,
    IMAGES_DOWNLOADED_DIR,
    SWIFT_CONTAINER,
    SWIFT_OPTIONS,
)

try:
    import swiftclient.service
    _SWIFT_AVAILABLE = True
except ImportError:
    swiftclient = None
    _SWIFT_AVAILABLE = False


def get_swift_service():
    """Create and return an OpenStack SwiftService client using `config.SWIFT_OPTIONS`."""
    if not _SWIFT_AVAILABLE:
        raise RuntimeError("python-swiftclient is not installed in this environment.")
    return swiftclient.service.SwiftService(options=SWIFT_OPTIONS)


# ── ZIP Archive Helpers ───────────────────────────────────────
def get_all_file_paths(directory: str) -> list[str]:
    """Recursively collect all file paths inside `directory`."""
    file_paths = []
    for root, _, files in os.walk(directory):
        for filename in files:
            file_paths.append(os.path.join(root, filename))
    return file_paths


def write_zip_file(directory: str) -> str:
    """Compress all files inside `directory` into `<directory>.zip` and return its path."""
    clean_dir = directory.rstrip("/\\")
    zip_path = f"{clean_dir}.zip"
    file_paths = get_all_file_paths(directory)

    with ZipFile(zip_path, "w") as zip_archive:
        for file_path in file_paths:
            arcname = os.path.relpath(file_path, start=os.path.dirname(clean_dir))
            zip_archive.write(file_path, arcname=arcname)

    return zip_path


# ── Swift Object Path Formatting ──────────────────────────────
def get_remote_prefix(ts: datetime.datetime) -> str:
    """Return the Swift object folder prefix for a given timestamp."""
    return f"images/{ts.month}/{ts.day}/{ts.hour}/"


def get_remote_path_from_timestamp(ts: datetime.datetime) -> str:
    """Return the full Swift object path for a timestamped PNG image."""
    return f"{get_remote_prefix(ts)}{ts.strftime('%d_%m_%Y_%H_%M')}.png"


# ── Download Operations ───────────────────────────────────────
def fetch_image(timestamp: datetime.datetime) -> bool:
    """Download a single historical image matching `timestamp` into `images_downloaded/`."""
    os.makedirs(IMAGES_DOWNLOADED_DIR, exist_ok=True)
    sv = get_swift_service()

    results = sv.download(
        SWIFT_CONTAINER,
        objects=[get_remote_path_from_timestamp(timestamp)],
        options={
            "out_directory": str(IMAGES_DOWNLOADED_DIR) + "/",
            "prefix": get_remote_prefix(timestamp),
            "remove_prefix": True,
        },
    )
    for res in results:
        return bool(res.get("success"))
    return False


def fetch_images_from_t1_to_t2(
    t1: datetime.datetime, t2: datetime.datetime
) -> str | None:
    """
    Download all images recorded between `t1` and `t2` from Swift storage,
    bundle them into a `.zip` archive in `images_downloaded/`, and return the zip path.
    """
    os.makedirs(IMAGES_DOWNLOADED_DIR, exist_ok=True)
    range_name = f"{t1.strftime('%d_%m_%Y_%H_%M')}-{t2.strftime('%d_%m_%Y_%H_%M')}"
    out_directory = os.path.join(IMAGES_DOWNLOADED_DIR, range_name) + "/"

    sv = get_swift_service()
    cursor = t1.replace(second=59)
    end_ts = t2.replace(second=59)

    while cursor <= end_ts:
        end_of_hour = cursor.replace(minute=59)
        files = []

        while cursor <= end_of_hour and cursor <= end_ts:
            files.append(get_remote_path_from_timestamp(cursor))
            cursor += datetime.timedelta(minutes=1)

        results = sv.download(
            SWIFT_CONTAINER,
            objects=files,
            options={
                "out_directory": out_directory,
                "prefix": get_remote_prefix(end_of_hour),
                "remove_prefix": True,
            },
        )
        for _ in results:
            pass

    if not os.path.exists(out_directory) or not get_all_file_paths(out_directory):
        return None

    return write_zip_file(out_directory)


# ── Upload Operations ─────────────────────────────────────────
def upload_directory_to_swift(directory_path: str) -> bool:
    """Upload all files in `directory_path` to Swift and remove the directory on success."""
    try:
        print(f"[UPLOAD] Attempting to upload from: {directory_path}")
        if not os.path.exists(directory_path):
            return False

        files = os.listdir(directory_path)
        if not files:
            print(f"[UPLOAD] No files found in {directory_path}")
            return False

        sv = get_swift_service()
        objects = [os.path.join(directory_path, f) for f in files]
        print(f"[UPLOAD] Found {len(objects)} files to upload")

        results = sv.upload(SWIFT_CONTAINER, objects=objects)
        for res in results:
            print(f"[UPLOAD] Uploaded: {res}")

        shutil.rmtree(directory_path)
        print(f"[UPLOAD] Successfully uploaded and removed {directory_path}")
        return True
    except Exception as e:
        print(f"[UPLOAD] Error during upload: {e}")
        return False


def run_hourly_upload_watcher() -> None:
    """Watch `IMAGES_UPLOAD_DIR` and upload completed hourly folders to Swift."""
    print("[UPLOAD] Upload watcher started")
    start_time = datetime.datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(LA_TZ)

    while True:
        try:
            new_time = (
                datetime.datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(LA_TZ)
            )
            if start_time.hour != new_time.hour:
                folder_path = os.path.join(
                    IMAGES_UPLOAD_DIR,
                    str(start_time.month).zfill(2),
                    str(start_time.day).zfill(2),
                    str(start_time.hour).zfill(2),
                )
                print(f"[UPLOAD] Checking path: {folder_path}")
                if os.path.exists(folder_path):
                    upload_directory_to_swift(folder_path)
                else:
                    print(f"[UPLOAD] No folder found at {folder_path}, skipping.")
                start_time = new_time

            time.sleep(60)
        except Exception as e:
            print(f"[UPLOAD] Watcher error: {e}")
            time.sleep(60)
