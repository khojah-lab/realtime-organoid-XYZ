from datetime import date, datetime, timedelta
import logging
import threading

from flask import Blueprint, jsonify, request

from config import LA_TZ
from .analytics import WELLS, read_day, upload_loop

analytics_bp = Blueprint("time_plot", __name__, url_prefix="/time_plot",
                         static_folder="static", template_folder="templates")


@analytics_bp.record_once
def start_uploader(state):
    threading.Thread(target=upload_loop, name="AnalyticsUpload", daemon=True).start()


@analytics_bp.get("/data")
def data():
    try:
        start = date.fromisoformat(request.args.get("start", datetime.now(LA_TZ).date().isoformat()))
        days = int(request.args.get("days", 1))
        well = request.args.get("well", "all")
        if days not in (1, 7, 14, 30) or well not in ("all", *WELLS):
            raise ValueError
        end = start + timedelta(days=days)
    except (ValueError, OverflowError):
        return jsonify(error="Choose a valid starting date, range and well."), 400

    rows = []
    try:
        for i in range(days):
            observations, _ = read_day(start + timedelta(days=i))
            rows.extend(r for r in observations if well == "all" or r["well"] == well)
    except Exception:
        logging.getLogger(__name__).exception("Cannot read daily analytics")
        return jsonify(error="Could not load analytics from S3. Try again."), 503

    def midnight(day):
        return LA_TZ.localize(datetime.combine(day, datetime.min.time())).isoformat()
    return jsonify(start=midnight(start), end=midnight(end), observations=rows)
