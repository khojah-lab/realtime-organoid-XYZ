"""
routes/analysis_routes.py
────────────────────────────────────────────────────────────────
Routes for automated 6-well plate scanning, organoid detection,
and historical cloud image retrieval/download.
────────────────────────────────────────────────────────────────
"""

import base64
import datetime
import glob
import os
import threading
import traceback
import cv2
from flask import Blueprint, current_app, jsonify, request, send_file

from config import LA_TZ, IMAGES_DOWNLOADED_DIR
from services.cloud_storage import fetch_image, fetch_images_from_t1_to_t2
from services.detection import run_detection
from services.scanner import get_scan_status, run_scan
from services.telemetry import emit_socket_event

analysis_bp = Blueprint("analysis", __name__)


# ── Automated 6-Well Plate Scan ───────────────────────────────
@analysis_bp.route("/scan_now")
def scan_now():
    """Trigger an immediate 6-well automated scan in a background thread."""
    threading.Thread(target=run_scan, daemon=True).start()
    return "OK"


@analysis_bp.route("/scan_status")
def scan_status_route():
    """Return current automated scan status for UI polling."""
    return jsonify(get_scan_status())


# ── Organoid Detection ────────────────────────────────────────
@analysis_bp.route("/detect_organoid")
def detect_organoid():
    """Run organoid detection on the current camera frame."""
    print("[DETECT] Starting organoid detection...")
    threading.Thread(target=run_detection, daemon=True).start()
    return jsonify({"success": True, "message": "Detection started"})


# ── Historical Image Retrieval & Bulk Download ────────────────
@analysis_bp.route("/retrieve_past_image")
def retrieve_past_image():
    """Fetch a historical image by timestamp from Swift storage and emit `past_image_result`."""
    dt_str = request.args.get("datetime")
    try:
        ts = datetime.datetime.strptime(dt_str, "%Y-%m-%dT%H:%M")
        ts = LA_TZ.localize(ts)
        print(f"[RETRIEVE] Searching for image at: {ts}")

        success = fetch_image(ts)
        if success:
            print("[RETRIEVE] Download successful, looking for file...")
            search_pattern = os.path.join(
                IMAGES_DOWNLOADED_DIR, f"*{ts.strftime('%d_%m_%Y_%H_%M')}*.png"
            )
            matching_files = glob.glob(search_pattern)

            if matching_files:
                fpath = matching_files[0]
                print(f"[RETRIEVE] Found file: {fpath}")
                if os.path.exists(fpath):
                    img = cv2.imread(fpath)
                    if img is not None:
                        _, buf = cv2.imencode(".jpg", img)
                        b64 = base64.b64encode(buf).decode("utf-8")
                        emit_socket_event("past_image_result", {"data": b64})
                        return "OK"

            print("[RETRIEVE] File not found after download")
        else:
            print("[RETRIEVE] Download failed")

        emit_socket_event("past_image_result", {"data": False})
    except Exception as e:
        print("retrieve_past_image error:", e)
        traceback.print_exc()
        emit_socket_event("past_image_result", {"data": False})
    return "OK"


@analysis_bp.route("/prepare_download_images")
def prepare_download():
    """Download images between `from` and `to` timestamps and bundle them into a zip file."""
    from_str = request.args.get("from")
    to_str   = request.args.get("to")
    try:
        print(f"[DOWNLOAD] Preparing images from {from_str} to {to_str}")
        t1 = LA_TZ.localize(datetime.datetime.strptime(from_str, "%Y-%m-%dT%H:%M"))
        t2 = LA_TZ.localize(datetime.datetime.strptime(to_str, "%Y-%m-%dT%H:%M"))

        zip_path = fetch_images_from_t1_to_t2(t1, t2)
        if zip_path and os.path.exists(zip_path):
            current_app.config["LAST_ZIP"] = zip_path
            print(f"[DOWNLOAD] Zip created: {zip_path}")
            return jsonify({"success": True})
        else:
            print("[DOWNLOAD] No images found in range")
            return jsonify(
                {"success": False, "error": "No images found in this time range"}
            )
    except Exception as e:
        print("prepare_download error:", e)
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


@analysis_bp.route("/download_images")
def download_images():
    """Serve the most recently prepared image archive zip file."""
    zip_path = current_app.config.get("LAST_ZIP")
    if zip_path and os.path.exists(zip_path):
        return send_file(zip_path, as_attachment=True)
    return "No zip ready", 404
