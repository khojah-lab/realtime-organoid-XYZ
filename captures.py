"""Browse and download scan captures stored on local disk.

Captures are named <chamber>_<YYYYMMDD>_<HHMMSS>.jpg (see take_scan_photo in
server.py). Captures taken within SCAN_GAP of each other belong to one scan.
"""
import datetime
import os
import re
import tempfile
import zipfile

import cv2
from flask import Blueprint, jsonify, request, send_file

CAPTURE_NAME = re.compile(r"^(?P<chamber>[a-z_]+)_(?P<stamp>\d{8}_\d{6})\.jpg$")
STAMP_FORMAT = "%Y%m%d_%H%M%S"
INPUT_FORMAT = "%Y-%m-%dT%H:%M"
SCAN_GAP     = datetime.timedelta(minutes=10)
THUMBNAIL_WIDTH = 320
MAX_ZIP_FILES   = 1000
ZIP_MEMORY_LIMIT = 50 * 1024 * 1024


def create_captures_blueprint(image_dir):
    blueprint     = Blueprint("captures", __name__, url_prefix="/captures")
    thumbnail_dir = os.path.join(image_dir, ".thumbnails")

    def list_captures():
        """All captures on disk, oldest first."""
        captures = []
        for entry in os.scandir(image_dir):
            match = CAPTURE_NAME.match(entry.name)
            if not (match and entry.is_file()):
                continue
            captures.append({
                "name":    entry.name,
                "chamber": match["chamber"],
                "taken":   datetime.datetime.strptime(match["stamp"], STAMP_FORMAT),
                "bytes":   entry.stat().st_size,
            })
        captures.sort(key=lambda capture: capture["taken"])
        return captures

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
        scans_per_date = {}
        for scan in group_into_scans(list_captures()):
            date = scan[0]["taken"].strftime("%Y-%m-%d")
            scans_per_date[date] = scans_per_date.get(date, 0) + 1
        return jsonify({"dates": [
            {"date": date, "scans": scans_per_date[date]}
            for date in sorted(scans_per_date, reverse=True)
        ]})

    @blueprint.route("/scans")
    def scans():
        try:
            day = datetime.datetime.strptime(request.args.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        day_captures = [c for c in list_captures() if c["taken"].date() == day]
        return jsonify({"scans": [
            {
                "time":     scan[0]["taken"].strftime("%H:%M"),
                "captures": [describe(capture) for capture in scan],
            }
            for scan in group_into_scans(day_captures)
        ]})

    @blueprint.route("/image/<name>")
    def image(name):
        if not CAPTURE_NAME.match(name) or not os.path.isfile(os.path.join(image_dir, name)):
            return jsonify({"error": "no such capture"}), 404
        full_path = os.path.join(image_dir, name)
        if not request.args.get("thumb"):
            return send_file(full_path, mimetype="image/jpeg", max_age=3600)

        thumbnail_path = os.path.join(thumbnail_dir, name)
        if not os.path.isfile(thumbnail_path):
            frame = cv2.imread(full_path)
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
            by_name = {c["name"]: c for c in list_captures()}
            missing = [name for name in names if name not in by_name]
            if missing:
                return None, f"no such capture: {missing[0]}"
            return sorted((by_name[name] for name in names), key=lambda capture: capture["taken"]), None
        try:
            start = datetime.datetime.strptime(request.args.get("from", ""), INPUT_FORMAT)
            end   = datetime.datetime.strptime(request.args.get("to", ""), INPUT_FORMAT)
        except ValueError:
            return None, "give name=... or from/to as YYYY-MM-DDTHH:MM"
        if end < start:
            return None, "'to' must be after 'from'"
        # The inputs have minute precision, so include captures through the end minute
        end += datetime.timedelta(minutes=1)
        return [c for c in list_captures() if start <= c["taken"] < end], None

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
                archive.write(os.path.join(image_dir, capture["name"]), capture["name"])
        archive_file.seek(0)

        first, last = captures[0]["taken"], captures[-1]["taken"]
        filename = f"captures_{first:%Y%m%d_%H%M}-{last:%Y%m%d_%H%M}.zip"
        return send_file(archive_file, mimetype="application/zip",
                         as_attachment=True, download_name=filename)

    return blueprint
