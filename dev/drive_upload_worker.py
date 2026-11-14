"""Drive-only Linux service. No camera, Flask, AWS or historical image discovery."""
import logging
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from services import drive_spool as spool
from services import drive_backup as drive

def prepare(day):
    drive.validate_destination()
    drive.day_folders(day)

def upload(path,row):
    if row['destination'] != drive.DRIVE_FOLDER_ID:
        raise RuntimeError('Queued destination differs from configured lab folder')
    drive.validate_destination()
    folders=drive.day_folders(row['day'])
    return drive.upload_one(path,folders[row['well']],row['md5'])

def main():
    import fcntl
    logging.basicConfig(level=logging.INFO)
    spool.DB.parent.mkdir(parents=True,exist_ok=True)
    with spool.DB.with_suffix('.worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        def upkeep():
            while True:
                try:
                    with spool.connect() as db: db.execute('UPDATE control SET heartbeat=? WHERE id=1',(time.time(),))
                    spool.cleanup()
                except Exception: logging.exception('Drive upkeep failed; copies retained')
                time.sleep(60)
        threading.Thread(target=upkeep,daemon=True).start()
        last_prepare=0
        while True:
            try:
                if time.monotonic()-last_prepare>=60:
                    spool.activate(prepare); last_prepare=time.monotonic()
                spool.recover()
                if spool.upload_one(upload): continue
            except Exception: logging.exception('Drive worker will retry')
            time.sleep(2)

if __name__=='__main__': main()
