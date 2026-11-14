"""Independent AWS worker using the existing AWS staging/upload/cleanup behavior."""
from pathlib import Path
import sys
import time
import logging
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from config import BASE_DIR, IMAGES_UPLOAD_DIR
from services.cloud_storage import upload_pending_images

def main():
    import fcntl
    logging.basicConfig(level=logging.INFO)
    with (BASE_DIR/'aws-upload.worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        from services.storage_worker import run
        run('aws', lambda: upload_pending_images(str(IMAGES_UPLOAD_DIR)))

if __name__=='__main__': main()
