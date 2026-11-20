"""Measurements from a single field, with a durable outbox for daily S3 JSON."""
import hashlib
import json
import logging
import math
import threading
from collections import defaultdict
from contextlib import closing

import cv2

from config import BASE_DIR, LA_TZ
from services.cloud_storage import BUCKET, get_client
from services.storage_manager import publish

OUTBOX = BASE_DIR / "state" / "time_plot_pending"
WELLS = tuple(f"{row}_{col}" for row in ("top", "bottom") for col in ("left", "middle", "right"))
wake = threading.Event()
log = logging.getLogger(__name__)


def record_field(frame, well, scan_id, timestamp, filename):
    from services.detection import organoid_contours

    well = well.replace("_center", "_middle")
    if well not in WELLS or not scan_id:
        raise ValueError("Unknown well or missing scan ID")
    areas = [cv2.contourArea(contour) for contour in organoid_contours(frame)]
    diameters = [2 * math.sqrt(area / math.pi) for area in areas]
    taken = timestamp.astimezone(LA_TZ)
    key = hashlib.sha256(f"{scan_id}/{filename}".encode()).hexdigest()
    record = dict(id=key, well=well, scan_id=scan_id, timestamp=taken.isoformat(),
                  count=len(areas), mean_diameter_px=sum(diameters)/len(areas) if areas else None)
    publish(OUTBOX / f"{taken.date()}_{key}.json", json.dumps(record).encode())
    wake.set()


def read_day(day):
    try:
        obj = get_client().get_object(Bucket=BUCKET, Key=f"time_plot/v1/{day}.json")
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404", "NotFound"):
            return [], None
        raise
    with closing(obj["Body"]) as body:
        rows = json.load(body)["observations"]
    return rows, obj["ETag"]


def flush_day(day, files):
    existing, etag = read_day(day)
    rows = {row["id"]: row for row in existing}
    for path in files:
        record = json.loads(path.read_bytes())
        rows[record["id"]] = record
    payload = dict(version=1, date=day, observations=sorted(rows.values(), key=lambda r: r["timestamp"]))
    # A competing writer leaves the outbox intact; retry with the newer ETag.
    condition = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
    get_client().put_object(Bucket=BUCKET, Key=f"time_plot/v1/{day}.json",
                            Body=json.dumps(payload).encode(), ContentType="application/json", **condition)
    for path in files:
        path.unlink(missing_ok=True)


def upload_loop():
    while True:
        wake.clear()
        by_day = defaultdict(list)
        for path in OUTBOX.glob("*.json"):
            by_day[path.name[:10]].append(path)
        for day, files in by_day.items():
            try:
                flush_day(day, files)
            except Exception:
                log.exception("Daily analytics upload pending for %s", day)
        wake.wait(60)
