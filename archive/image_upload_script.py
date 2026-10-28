import os
import datetime
import time
import shutil
import pytz
import smtplib
from swiftCloudAuth import *

# Must match IMAGES_BASE_DIR in server.py
IMAGES_BASE_DIR = "/home/khojahlab/Downloads/Web/Reem_Khojah_Lab_Cloud_motor-main/images_upload"

def execute_upload_script(path):
    try:
        print(f"[UPLOAD] Attempting to upload from: {path}")
        files = os.listdir(path)
        if not files:
            print(f"[UPLOAD] No files found in {path}")
            return False
            
        print(f"[UPLOAD] Found {len(files)} files to upload")
        x = sv.upload('image_store_motor', objects=[path + f for f in files])
        for t in x:
            print(f"[UPLOAD] File uploaded: {t}")
        
        # Only remove if upload succeeded
        shutil.rmtree(path)
        print(f"[UPLOAD] Successfully uploaded and removed {path}")
        return True
    except Exception as e:
        print(f"[UPLOAD] Error during upload: {e}")
        return False

def set_upload_time():
    print("[UPLOAD] Upload watcher started")
    start_time = datetime.datetime.utcnow()
    los_angeles_tz = pytz.timezone("America/Los_Angeles")
    start_time = start_time.replace(tzinfo=pytz.utc).astimezone(los_angeles_tz)

    while True:
        try:
            new_time = datetime.datetime.utcnow()
            los_angeles_tz = pytz.timezone("America/Los_Angeles")
            new_time = new_time.replace(tzinfo=pytz.utc).astimezone(los_angeles_tz)

            if start_time.hour != new_time.hour:
                # Fixed typo: was start_[time.day] — now correctly start_time.day
                # Uses absolute IMAGES_BASE_DIR to match server.py
                path = os.path.join(
                    IMAGES_BASE_DIR,
                    str(start_time.month),
                    str(start_time.day),      # <-- typo fixed here
                    str(start_time.hour)
                ) + "/"
                
                print(f"[UPLOAD] Checking path: {path}")
                if os.path.exists(path):
                    execute_upload_script(path)
                else:
                    print(f"[UPLOAD] No folder found at {path}, skipping.")
                start_time = new_time

            time.sleep(60)
        except Exception as e:
            print(f"[UPLOAD] Watcher error: {e}")
            time.sleep(60)