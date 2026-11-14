"""Drive-only capture spool and durable control. Never imports AWS or deletes its files."""
import contextlib
import datetime as dt
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
from config import BASE_DIR, DRIVE_FOLDER_ID, LA_TZ, CHAMBER_NAMES

SPOOL = Path(os.getenv('XYZ_DRIVE_SPOOL', str(BASE_DIR / 'drive_spool')))
DB = Path(os.getenv('XYZ_DRIVE_UPLOAD_DB', str(BASE_DIR / 'drive_upload_state.sqlite3')))
RETENTION_SECONDS = 600

@contextlib.contextmanager
def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS control (id INTEGER PRIMARY KEY, requested INTEGER,
          enabled INTEGER, paused INTEGER, generation INTEGER, destination TEXT,
          error TEXT, heartbeat REAL);
        CREATE TABLE IF NOT EXISTS scans (id TEXT PRIMARY KEY, enabled INTEGER, destination TEXT);
        CREATE TABLE IF NOT EXISTS photos (path TEXT PRIMARY KEY, scan TEXT, name TEXT,
          well TEXT, day TEXT, destination TEXT, md5 TEXT, size INTEGER,
          ready INTEGER DEFAULT 0, verified REAL, remote TEXT, deleted INTEGER DEFAULT 0,
          attempts INTEGER DEFAULT 0, next_try REAL DEFAULT 0, error TEXT);
        ''')
        db.execute('INSERT OR IGNORE INTO control VALUES (1,0,0,0,0,NULL,NULL,NULL)')
        db.commit()
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally: db.close()

def control():
    with connect() as db: return dict(db.execute('SELECT * FROM control WHERE id=1').fetchone())

def request_enabled(enabled):
    if type(enabled) is not bool: raise ValueError('enabled must be a boolean')
    with connect() as db:
        # Enabling never directly starts capture: the worker must validate first.
        row = db.execute('SELECT * FROM control WHERE id=1').fetchone()
        if bool(row['requested']) == enabled: return
        db.execute('UPDATE control SET requested=?,enabled=0,generation=generation+1,error=NULL WHERE id=1', (int(enabled),))

def request_paused(paused):
    if type(paused) is not bool: raise ValueError('paused must be a boolean')
    with connect() as db: db.execute('UPDATE control SET paused=? WHERE id=1', (int(paused),))

def activate(prepare):
    """prepare validates identity/root and creates today's folders; no images imported."""
    row = control()
    if not row['requested'] or row['enabled']: return
    try:
        prepare(dt.datetime.now(LA_TZ).strftime('%Y-%m-%d'))
        with connect() as db:
            db.execute('''UPDATE control SET enabled=1,destination=?,error=NULL
                WHERE id=1 AND requested=1 AND generation=?''', (DRIVE_FOLDER_ID, row['generation']))
    except Exception as exc:
        with connect() as db:
            db.execute('UPDATE control SET error=? WHERE id=1 AND generation=?',
                       (str(exc)[:1000], row['generation']))

def begin_scan():
    """Called once before a full scan. Changes during the scan do not change this row."""
    scan_id = uuid.uuid4().hex
    with connect() as db:
        db.execute('''INSERT INTO scans SELECT ?,enabled,destination FROM control WHERE id=1''', (scan_id,))
    return scan_id

def safe_path(relative):
    path = SPOOL / relative
    root = SPOOL.resolve()
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root):
        raise ValueError('Path outside Drive spool')
    for parent in [path, *path.parents]:
        if parent.is_symlink(): raise ValueError('Symlink in Drive spool path')
        if parent == SPOOL.parent: break
    return path

def checksum(path):
    h = hashlib.md5()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def note_capture_error(exc):
    with connect() as db: db.execute('UPDATE control SET error=? WHERE id=1', ('Local capture: '+str(exc)[:900],))

def capture(scan_id, name, well, taken, jpeg):
    """Publish an independent full JPEG. No reads/scans of old images/ or AWS staging."""
    if well not in CHAMBER_NAMES or Path(name).name != name or not name.endswith('.jpg'):
        raise ValueError('Invalid capture identity')
    if taken.tzinfo is None: raise ValueError('Capture time must include timezone')
    relative = scan_id + '/' + name
    path = safe_path(relative)
    with connect() as db:
        scan = db.execute('SELECT * FROM scans WHERE id=?', (scan_id,)).fetchone()
        if scan is None: raise ValueError('Unknown scan session')
        if not scan['enabled']: return False
        db.execute('''INSERT INTO photos(path,scan,name,well,day,destination,md5,size)
            VALUES (?,?,?,?,?,?,?,?)''', (relative,scan_id,name,well,taken.astimezone(LA_TZ).strftime('%Y-%m-%d'),
                                         scan['destination'],hashlib.md5(jpeg).hexdigest(),len(jpeg)))
    # First record intent, then publish; recovery touches ONLY registered rows.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.part')
    with temp.open('xb') as f:
        f.write(jpeg); f.flush(); os.fsync(f.fileno())
    try:
        os.replace(temp, path)
    except FileNotFoundError:
        # Recovery may have published the fully flushed copy concurrently.
        if not path.exists() or checksum(path) != hashlib.md5(jpeg).hexdigest(): raise
    with connect() as db: db.execute('UPDATE photos SET ready=1,error=NULL WHERE path=?', (relative,))
    return True

def recover():
    with connect() as db:
        rows = db.execute('SELECT * FROM photos WHERE ready=0 AND deleted=0').fetchall()
        for row in rows:
            try:
                path = safe_path(row['path']); temp = path.with_suffix('.part')
                candidate = path if path.exists() else temp
                if candidate.is_symlink(): raise ValueError('Unsafe partial file')
                if candidate.stat().st_size != row['size'] or checksum(candidate) != row['md5']:
                    raise RuntimeError('Incomplete Drive capture; retained for inspection')
                if candidate == temp: os.replace(temp,path)
                db.execute('UPDATE photos SET ready=1,error=NULL WHERE path=?', (row['path'],))
            except Exception as exc:
                db.execute('UPDATE photos SET error=? WHERE path=?', (str(exc)[:1000],row['path']))

def upload_one(upload):
    if control()['paused']: return False
    with connect() as db:
        row = db.execute('''SELECT * FROM photos WHERE ready=1 AND verified IS NULL
            AND deleted=0 AND next_try<=? ORDER BY next_try,path LIMIT 1''', (time.time(),)).fetchone()
    if row is None: return False
    try:
        path = safe_path(row['path'])
        if path.stat().st_size != row['size'] or checksum(path) != row['md5']:
            raise RuntimeError('Drive copy changed; upload/cleanup blocked')
        remote = upload(path, dict(row))
        if not remote or checksum(path) != row['md5']: raise RuntimeError('Verification failed')
        with connect() as db:
            db.execute('UPDATE photos SET verified=?,remote=?,error=NULL WHERE path=?',
                       (time.time(),str(remote),row['path']))
    except Exception as exc:
        with connect() as db:
            delay = min(3600,60*2**min(row['attempts'],6))
            db.execute('UPDATE photos SET attempts=attempts+1,next_try=?,error=? WHERE path=?',
                       (time.time()+delay,str(exc)[:1000],row['path']))
    return True

def cleanup(now=None):
    now = time.time() if now is None else now
    with connect() as db:
        rows = db.execute('SELECT * FROM photos WHERE deleted=0 AND verified<=?', (now-RETENTION_SECONDS,)).fetchall()
        for row in rows:
            try:
                path = safe_path(row['path'])
                if path.exists():
                    if path.stat().st_size != row['size'] or checksum(path) != row['md5']:
                        raise RuntimeError('Drive copy changed; cleanup blocked')
                    path.unlink()
                db.execute('UPDATE photos SET deleted=1,error=NULL WHERE path=?', (row['path'],))
                try: path.parent.rmdir()
                except OSError: pass
            except Exception as exc:
                db.execute('UPDATE photos SET error=? WHERE path=?', (str(exc)[:1000],row['path']))

def status():
    result = control()
    with connect() as db:
        result.update(dict(db.execute('''SELECT COUNT(*) AS total,
            COALESCE(SUM(verified IS NULL),0) AS pending,
            COALESCE(SUM(verified IS NOT NULL),0) AS verified,
            COALESCE(SUM(deleted),0) AS deleted,
            COALESCE(SUM(CASE WHEN deleted=0 THEN size ELSE 0 END),0) AS local_bytes FROM photos''').fetchone()))
        result['errors'] = [dict(r) for r in db.execute('SELECT name,error FROM photos WHERE error IS NOT NULL LIMIT 5')]
    SPOOL.mkdir(parents=True,exist_ok=True)
    disk = shutil.disk_usage(SPOOL)
    result['free_gb'] = round(disk.free/1024**3,2)
    result['low_space'] = disk.free < max(1024**3,disk.total*.1)
    result['worker_alive'] = bool(result['heartbeat'] and time.time()-result['heartbeat']<90)
    return result
