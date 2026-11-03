import os
import re
import threading

import boto3

BUCKET = os.environ.get("XYZ_S3_BUCKET", "realtime-organoid-xyz-data")
REGION = "us-east-2"

TIMESTAMP_PATTERN = re.compile(r"_(\d{4})(\d{2})(\d{2})_(\d{2})\d{4}\.jpg$")

_upload_lock = threading.Lock()
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("s3", region_name=REGION)
    return _client


def object_key(filename):
    """Key is YYYY/MM/DD/HH/<filename>, taken from the timestamp in the filename."""
    match = TIMESTAMP_PATTERN.search(filename)
    if not match:
        return None
    year, month, day, hour = match.groups()
    return f"{year}/{month}/{day}/{hour}/{filename}"


def upload_pending_images(staging_dir):
    """Upload every .jpg under staging_dir, deleting each local file only after its upload succeeds.

    Files that fail stay in place and are retried on the next call.
    """
    if not _upload_lock.acquire(blocking=False):
        print("[UPLOAD] Upload already in progress, skipping.")
        return

    try:
        uploaded = failed = 0
        for directory, _, filenames in os.walk(staging_dir):
            for filename in sorted(filenames):
                key = object_key(filename)
                if key is None:
                    continue
                path = os.path.join(directory, filename)
                try:
                    _get_client().upload_file(path, BUCKET, key)
                    os.remove(path)
                    uploaded += 1
                except Exception as e:
                    failed += 1
                    print(f"[UPLOAD] Failed to upload {path}: {e}")

        # Remove emptied hour/day/month folders, never the staging root itself.
        for directory, _, _ in os.walk(staging_dir, topdown=False):
            if directory != staging_dir and not os.listdir(directory):
                os.rmdir(directory)

        print(f"[UPLOAD] Uploaded {uploaded} to s3://{BUCKET}, {failed} failed")
    finally:
        _upload_lock.release()
