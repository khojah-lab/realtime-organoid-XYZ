"""Browse and download scan captures stored in S3.

Captures are named <chamber>_<YYYYMMDD>_<HHMMSS>.jpg (see take_scan_photo in
server.py) and stored under YYYY/MM/DD/HH/ (see s3_upload.py). Captures taken
within SCAN_GAP of each other belong to one scan. Needs s3:ListBucket and
s3:GetObject on the bucket.
"""
import datetime
import io
import os
import re
import tempfile
import time
import zipfile

import cv2
import numpy as np
from botocore.exceptions import ClientError
from flask import Blueprint, jsonify, request, send_file

from s3_upload import BUCKET, get_client, object_key

CAPTURE_NAME = re.compile(r"^(?P<chamber>[a-z_]+)_(?P<stamp>\d{8}_\d{6})\.jpg$")
STAMP_FORMAT = "%Y%m%d_%H%M%S"
INPUT_FORMAT = "%Y-%m-%dT%H:%M"
SCAN_GAP     = datetime.timedelta(minutes=10)
THUMBNAIL_WIDTH  = 320
MAX_ZIP_FILES    = 1000
MAX_ZIP_DAYS     = 366
ZIP_MEMORY_LIMIT = 50 * 1024 * 1024
DATES_CACHE_SECONDS = 60


def create_captures_blueprint(image_dir):
    blueprint     = Blueprint("captures", __name__, url_prefix="/captures")
    thumbnail_dir = os.path.join(image_dir, ".thumbnails")

    dates_cache = {"fetched": 0.0, "dates": []}

    def list_prefixes(prefix):
        """Names of the folders directly under prefix."""
        names = []
        paginator = get_client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix, Delimiter="/"):
            names += [entry["Prefix"][len(prefix):-1] for entry in page.get("CommonPrefixes", [])]
        return names

    def list_dates():
        """Every YYYY-MM-DD that has captures, newest first. Cached because it takes one S3 call per month."""
        if time.monotonic() - dates_cache["fetched"] > DATES_CACHE_SECONDS:
            dates = []
            for year in filter(re.compile(r"^\d{4}$").match, list_prefixes("")):
                for month in filter(re.compile(r"^\d{2}$").match, list_prefixes(f"{year}/")):
                    for day in filter(re.compile(r"^\d{2}$").match, list_prefixes(f"{year}/{month}/")):
                        dates.append(f"{year}-{month}-{day}")
            dates_cache.update(fetched=time.monotonic(), dates=sorted(dates, reverse=True))
        return dates_cache["dates"]

    def list_day(day):
        """Captures taken on a date, oldest first."""
        captures = []
        paginator = get_client().get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET, Prefix=day.strftime("%Y/%m/%d/")):
            for item in page.get("Contents", []):
                name  = item["Key"].rsplit("/", 1)[-1]
                match = CAPTURE_NAME.match(name)
                if match:
                    captures.append({
                        "name":    name,
                        "chamber": match["chamber"],
                        "taken":   datetime.datetime.strptime(match["stamp"], STAMP_FORMAT),
                        "bytes":   item["Size"],
                    })
        captures.sort(key=lambda capture: capture["taken"])
        return captures

    def download(name):
        """Bytes of a capture, or None if it is not in the bucket."""
        try:
            return get_client().get_object(Bucket=BUCKET, Key=object_key(name))["Body"].read()
        except ClientError as error:
            if error.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise

    def group_into_scans(captures):
        scans = []
        for capture in captures:
            if scans and capture["taken"] - scans[-1][-1]["taken"] <= SCAN_GAP:
                scans[-1].append(capture)
            else:
                scans.append([capture])
        return scans

    def describe(capture):
        return {
            "name":    capture["name"],
            "chamber": capture["chamber"],
            "time":    capture["taken"].strftime("%H:%M:%S"),
            "bytes":   capture["bytes"],
        }

    @blueprint.route("/dates")
    def dates():
        # Scans per date aren't known without listing every day, so the page gets them from /scans
        return jsonify({"dates": [{"date": date, "scans": None} for date in list_dates()]})

    @blueprint.route("/scans")
    def scans():
        try:
            day = datetime.datetime.strptime(request.args.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        day_captures = list_day(day)
        return jsonify({"scans": [
            {
                "time":     scan[0]["taken"].strftime("%H:%M"),
                "captures": [describe(capture) for capture in scan],
            }
            for scan in group_into_scans(day_captures)
        ]})

    @blueprint.route("/image/<name>")
    def image(name):
        if not CAPTURE_NAME.match(name):
            return jsonify({"error": "no such capture"}), 404
        thumbnail_path = os.path.join(thumbnail_dir, name)
        if request.args.get("thumb") and os.path.isfile(thumbnail_path):
            return send_file(thumbnail_path, mimetype="image/jpeg", max_age=3600)

        data = download(name)
        if data is None:
            return jsonify({"error": "no such capture"}), 404
        if not request.args.get("thumb"):
            return send_file(io.BytesIO(data), mimetype="image/jpeg", max_age=3600)

        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify({"error": "unreadable image"}), 500
        height = int(frame.shape[0] * THUMBNAIL_WIDTH / frame.shape[1])
        os.makedirs(thumbnail_dir, exist_ok=True)
        cv2.imwrite(thumbnail_path, cv2.resize(frame, (THUMBNAIL_WIDTH, height)))
        return send_file(thumbnail_path, mimetype="image/jpeg", max_age=3600)

    def select_for_zip():
        """Captures chosen by ?name=... or ?from=...&to=...; returns (captures, error)."""
        names = request.args.getlist("name")
        if names:
            captures = []
            for name in names:
                match = CAPTURE_NAME.match(name)
                if not match:
                    return None, f"no such capture: {name}"
                captures.append({"name": name, "taken": datetime.datetime.strptime(match["stamp"], STAMP_FORMAT)})
            return sorted(captures, key=lambda capture: capture["taken"]), None
        try:
            start = datetime.datetime.strptime(request.args.get("from", ""), INPUT_FORMAT)
            end   = datetime.datetime.strptime(request.args.get("to", ""), INPUT_FORMAT)
        except ValueError:
            return None, "give name=... or from/to as YYYY-MM-DDTHH:MM"
        if end < start:
            return None, "'to' must be after 'from'"
        if (end.date() - start.date()).days >= MAX_ZIP_DAYS:
            return None, f"the range is limited to {MAX_ZIP_DAYS} days"
        # The inputs have minute precision, so include captures through the end minute
        end += datetime.timedelta(minutes=1)
        captures = []
        for offset in range((end.date() - start.date()).days + 1):
            captures += list_day(start.date() + datetime.timedelta(days=offset))
        return [c for c in captures if start <= c["taken"] < end], None

    @blueprint.route("/zip")
    def zip_captures():
        captures, error = select_for_zip()
        if error:
            return jsonify({"error": error}), 400
        if not captures:
            return jsonify({"error": "no captures in that selection"}), 404
        if len(captures) > MAX_ZIP_FILES:
            return jsonify({"error": f"{len(captures)} images selected; the limit is {MAX_ZIP_FILES}"}), 413

        archive_file = tempfile.SpooledTemporaryFile(max_size=ZIP_MEMORY_LIMIT)
        with zipfile.ZipFile(archive_file, "w", zipfile.ZIP_STORED) as archive:  # JPEGs don't compress
            for capture in captures:
                data = download(capture["name"])
                if data is None:
                    return jsonify({"error": f"no such capture: {capture['name']}"}), 404
                archive.writestr(capture["name"], data)
        archive_file.seek(0)

        first, last = captures[0]["taken"], captures[-1]["taken"]
        filename = f"captures_{first:%Y%m%d_%H%M}-{last:%Y%m%d_%H%M}.zip"
        return send_file(archive_file, mimetype="application/zip",
                         as_attachment=True, download_name=filename)

    return blueprint
