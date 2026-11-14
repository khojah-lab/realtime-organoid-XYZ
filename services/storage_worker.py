"""Shared worker loop; each provider remains an independent OS process."""
import logging
import threading
import time
from services import storage_manager as manager

def run(provider, legacy):
    def upkeep():
        while True:
            try:
                manager.heartbeat(provider)
            except Exception: logging.exception('Storage upkeep failed; files retained')
            time.sleep(60)
    def quotas():
        while True:
            try: manager.capacity(provider)
            except Exception: logging.exception('Cloud usage unavailable')
            time.sleep(3600)
    threading.Thread(target=upkeep,daemon=True).start()
    threading.Thread(target=quotas,daemon=True).start()
    last_legacy=0
    while True:
        try:
            manager.cleanup(provider)
            if time.monotonic()-last_legacy>=60:
                with manager.connect() as db:
                    paused=db.execute('SELECT paused FROM workers WHERE provider=?',(provider,)).fetchone()[0]
                if not paused: legacy()
                last_legacy=time.monotonic()
            if manager.process_one(provider): continue
        except Exception: logging.exception('Storage worker will retry')
        time.sleep(2)
