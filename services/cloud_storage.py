"""
services/cloud_storage.py
────────────────────────────────────────────────────────────────
AWS S3 cloud storage client and background uploader for captured
microscopy scan images.
────────────────────────────────────────────────────────────────
"""

import os
import re
import threading

from config import S3_BUCKET, S3_REGION

try:
    import boto3
    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None
    _BOTO3_AVAILABLE = False

BUCKET = S3_BUCKET
REGION = S3_REGION

TIMESTAMP_PATTERN = re.compile(r"_(\d{4})(\d{2})(\d{2})_(\d{2})\d{4}\.jpg$")

_upload_lock = threading.Lock()
_client = None


def get_client():
    """Return a cached boto3 S3 client for `REGION`."""
    global _client
    if not _BOTO3_AVAILABLE:
        raise RuntimeError("boto3 is not installed in this environment.")
    if _client is None:
        _client = boto3.client("s3", region_name=REGION)
    return _client


def object_key(filename: str) -> str | None:
    """Key is YYYY/MM/DD/HH/<filename>, taken from the timestamp in the filename."""
    match = TIMESTAMP_PATTERN.search(filename)
    if not match:
        return None
    year, month, day, hour = match.groups()
    return f"{year}/{month}/{day}/{hour}/{filename}"


def upload_pending_images(staging_dir: str) -> None:
    """
    Upload every .jpg under `staging_dir`, deleting each local file only after
    its upload succeeds. Files that fail stay in place and are retried on the next call.
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
                    get_client().upload_file(path, BUCKET, key)
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
