"""Durable per-scan storage policy. Only registered new originals are eligible for cleanup."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid
from config import BASE_DIR, IMAGE_DIR, DRIVE_FOLDER_ID, S3_BUCKET, LA_TZ

DB = BASE_DIR / 'storage_state.sqlite3'
ROOTS = {'original': Path(IMAGE_DIR), 'aws': BASE_DIR / 'aws_spool', 'drive': BASE_DIR / 'drive_spool_v2'}
MODES = {'aws': ('aws',), 'drive': ('drive',), 'both': ('aws', 'drive')}
RETENTION = 7 * 86400

@contextlib.contextmanager
def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(DB, timeout=15)) as db, db:
        db.row_factory = sqlite3.Row
        db.executescript('''
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, mode TEXT);
        CREATE TABLE IF NOT EXISTS scans(id TEXT PRIMARY KEY, mode TEXT, started REAL, finished REAL);
        CREATE TABLE IF NOT EXISTS originals(name TEXT PRIMARY KEY, scan TEXT, taken REAL, digest TEXT,
          size INTEGER, ready INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0, error TEXT);
        CREATE TABLE IF NOT EXISTS jobs(name TEXT, provider TEXT, destination TEXT, required INTEGER DEFAULT 1,
          verified REAL, remote TEXT, deleted INTEGER DEFAULT 0, attempts INTEGER DEFAULT 0,
          next_try REAL DEFAULT 0, error TEXT, PRIMARY KEY(name,provider));
        CREATE TABLE IF NOT EXISTS workers(provider TEXT PRIMARY KEY, paused INTEGER DEFAULT 0,
          heartbeat REAL, error TEXT, capacity TEXT);
        CREATE TABLE IF NOT EXISTS audit(at REAL, action TEXT, detail TEXT);
        CREATE INDEX IF NOT EXISTS job_queue ON jobs(provider,required,verified,next_try);
        CREATE INDEX IF NOT EXISTS original_age ON originals(deleted,taken);
        ''')
        if not db.execute('SELECT 1 FROM settings').fetchone():
            from services import drive_spool
            mode = 'both' if drive_spool.control()['enabled'] else 'aws'
            db.execute('INSERT INTO settings VALUES(1,?)', (mode,))
        for p in ('aws', 'drive'):
            db.execute('INSERT OR IGNORE INTO workers(provider) VALUES(?)', (p,))
        db.commit()
        yield db

def safe(kind, name):
    if Path(name).name != name or not name.endswith('.jpg'):
        raise ValueError('Invalid photo name')
    root = ROOTS[kind]
    path = root / name
    if any(p.is_symlink() for p in (path, root, *root.parents)):
        raise ValueError('Symlink not allowed in managed storage')
    return path

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def publish(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.part')
    try:
        with temp.open('xb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()

def space():
    d = shutil.disk_usage(BASE_DIR)
    return dict(total=d.total, free=d.free, used=d.used,
                low=d.free < max(1024**3, d.total*.1),
                critical=d.free < max(512*1024**2, d.total*.03))

def set_mode(mode):
    if mode not in MODES: raise ValueError('Choose AWS, Drive or Both')
    # Validate before committing. Failure leaves the previous mode in force.
    if 'aws' in MODES[mode]:
        from services.cloud_storage import get_client
        get_client().head_bucket(Bucket=S3_BUCKET)
    if 'drive' in MODES[mode]:
        import datetime
        from services import drive_backup as drive
        drive.validate_destination()
        drive.day_folders(datetime.datetime.now(LA_TZ).strftime('%Y-%m-%d'))
    with connect() as db:
        db.execute('UPDATE settings SET mode=? WHERE id=1', (mode,))
        db.execute('INSERT INTO audit VALUES(?,?,?)', (time.time(),'mode',mode))

def begin_scan():
    if space()['critical']: raise RuntimeError('Disk critically low: new scan blocked; uploads continue')
    sid = uuid.uuid4().hex
    with connect() as db:
        mode = db.execute('SELECT mode FROM settings').fetchone()[0]
        db.execute('UPDATE scans SET finished=? WHERE finished IS NULL',(time.time(),))
        db.execute('INSERT INTO scans VALUES(?,?,?,NULL)', (sid,mode,time.time()))
    return sid

def finish_scan(sid):
    with connect() as db: db.execute('UPDATE scans SET finished=? WHERE id=?',(time.time(),sid))

def capture(sid, name, taken, jpeg):
    if taken.tzinfo is None: raise ValueError('Capture timestamp requires timezone')
    path = safe('original',name)
    if path.exists(): raise ValueError('Original name already exists; refusing overwrite')
    sha = hashlib.sha256(jpeg).hexdigest()
    with connect() as db:
        scan = db.execute('SELECT mode FROM scans WHERE id=?',(sid,)).fetchone()
        if not scan: raise ValueError('Unknown scan')
        db.execute('INSERT INTO originals(name,scan,taken,digest,size) VALUES(?,?,?,?,?)',
                   (name,sid,taken.timestamp(),sha,len(jpeg)))
        for p in MODES[scan[0]]:
            db.execute('INSERT INTO jobs(name,provider,destination) VALUES(?,?,?)',
                       (name,p,S3_BUCKET if p=='aws' else DRIVE_FOLDER_ID))
    publish(path,jpeg)
    with connect() as db: db.execute('UPDATE originals SET ready=1 WHERE name=?',(name,))
    # Workers create/recover their own physical copies from the durable original.
    return str(path)

def aws_upload(path, row):
    from services.cloud_storage import get_client, object_key
    client = get_client(); key = object_key(row['name'])
    if not key: raise ValueError('Invalid S3 filename')
    def check():
        result = client.get_object(Bucket=row['destination'],Key=key)
        body = result['Body']; h = hashlib.sha256()
        try:
            for chunk in iter(lambda: body.read(1024*1024),b''): h.update(chunk)
        finally: body.close()
        if h.hexdigest()!=row['digest']: raise RuntimeError('S3 content conflict/checksum mismatch')
    try:
        check()  # Recover a successful upload whose local receipt was interrupted.
    except Exception as exc:
        code = getattr(exc,'response',{}).get('Error',{}).get('Code')
        if code not in ('NoSuchKey','404','NotFound'): raise
        client.upload_file(str(path),row['destination'],key)
        check()
    return key

def drive_upload(path,row):
    import datetime
    from services import drive_backup as drive
    if row['destination'] != drive.DRIVE_FOLDER_ID: raise RuntimeError('Restore queued Drive destination configuration')
    drive.validate_destination()
    well = drive.parse_name(row['name'])
    day = datetime.datetime.fromtimestamp(row['taken'],LA_TZ).strftime('%Y-%m-%d')
    return drive.upload_one(path,drive.day_folders(day)[well],drive.checksum(path))

def process_one(provider, upload=None):
    with connect() as db:
        if db.execute('SELECT paused FROM workers WHERE provider=?',(provider,)).fetchone()[0]: return False
        row = db.execute('''SELECT j.*,o.digest,o.size,o.taken FROM jobs j JOIN originals o USING(name)
            WHERE provider=? AND required=1 AND verified IS NULL AND next_try<=?
            ORDER BY next_try,o.taken LIMIT 1''',(provider,time.time())).fetchone()
    if row is None: return False
    row = dict(row)
    try:
        original = safe('original',row['name']); copy = safe(provider,row['name'])
        if not copy.exists():
            if digest(original)!=row['digest']: raise RuntimeError('Original incomplete or changed; retained')
            publish(copy,original.read_bytes())
        if digest(copy)!=row['digest']: raise RuntimeError('Upload copy checksum mismatch; retained')
        remote = (upload or (aws_upload if provider=='aws' else drive_upload))(copy,row)
        if not remote or digest(copy)!=row['digest']: raise RuntimeError('Upload verification failed')
        with connect() as db:
            db.execute('UPDATE originals SET ready=1 WHERE name=?',(row['name'],))
            db.execute('UPDATE jobs SET verified=?,remote=?,error=NULL WHERE name=? AND provider=?',
                       (time.time(),str(remote),row['name'],provider))
    except Exception as exc:
        with connect() as db:
            db.execute('UPDATE jobs SET attempts=attempts+1,next_try=?,error=? WHERE name=? AND provider=?',
                       (time.time()+min(3600,60*2**min(row['attempts'],6)),str(exc)[:800],row['name'],provider))
    return True

def cleanup(provider, now=None):
    now = time.time() if now is None else now
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute('''SELECT j.*,o.digest FROM jobs j JOIN originals o USING(name)
             WHERE provider=? AND j.deleted=0 AND (verified<=? OR required=0)''',
             (provider,now-(600 if provider=='drive' else 0))).fetchall():
            try:
                path=safe(provider,row['name'])
                if path.exists():
                    if digest(path)!=row['digest']: raise RuntimeError('Changed copy retained')
                    path.unlink()
                db.execute('UPDATE jobs SET deleted=1,error=NULL WHERE name=? AND provider=?',(row['name'],provider))
            except Exception as exc:
                db.execute('UPDATE jobs SET error=? WHERE name=? AND provider=?',(str(exc),row['name'],provider))
        # Serialized with policy adjustments and the other worker. Never discovers old originals.
        rows=db.execute('''SELECT * FROM originals o WHERE ready=1 AND deleted=0 AND taken<=?
          AND EXISTS(SELECT 1 FROM jobs j WHERE j.name=o.name AND required=1)
          AND NOT EXISTS(SELECT 1 FROM jobs j WHERE j.name=o.name AND required=1 AND verified IS NULL)''',
          (now-RETENTION,)).fetchall()
        for row in rows:
            try:
                path=safe('original',row['name'])
                if path.exists():
                    if digest(path)!=row['digest']: raise RuntimeError('Changed original retained')
                    path.unlink()
                thumb=ROOTS['original']/'.thumbnails'/row['name']
                if thumb.parent.is_symlink() or thumb.is_symlink(): raise RuntimeError('Unsafe thumbnail retained')
                if thumb.exists(): thumb.unlink()
                db.execute('UPDATE originals SET deleted=1,error=NULL WHERE name=?',(row['name'],))
            except Exception as exc:
                db.execute('UPDATE originals SET error=? WHERE name=?',(str(exc),row['name']))

def waive_preview(provider):
    if provider not in ('aws','drive'): raise ValueError('Invalid provider')
    with connect() as db:
        return _waive_preview(db,provider)

def _waive_preview(db,provider):
        rows=db.execute('''SELECT j.name,o.size FROM jobs j JOIN originals o USING(name)
            JOIN scans s ON s.id=o.scan WHERE j.provider=? AND j.required=1 AND j.verified IS NULL
            AND s.finished IS NOT NULL AND EXISTS(SELECT 1 FROM jobs k WHERE k.name=j.name
              AND k.provider!=j.provider AND k.required=1 AND k.verified IS NOT NULL) ORDER BY j.name''',(provider,)).fetchall()
        names=[r['name'] for r in rows]
        return dict(provider=provider,names=names,count=len(names),bytes=sum(r['size'] for r in rows),
                token=hashlib.sha256(json.dumps([provider,names]).encode()).hexdigest())

def waive(provider, token):
    if provider not in ('aws','drive'): raise ValueError('Invalid provider')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        preview=_waive_preview(db,provider)
        if token!=preview['token']: raise ValueError('Queue changed; preview again')
        for name in preview['names']:
            db.execute('UPDATE jobs SET required=0 WHERE name=? AND provider=?',(name,provider))
        db.execute('INSERT INTO audit VALUES(?,?,?)',(time.time(),'waive',json.dumps(preview)))
    return preview

def capacity(provider):
    try:
        if provider=='drive':
            from services.drive_backup import get_client, validate_destination
            validate_destination()
            q=get_client().about().get(fields='storageQuota').execute()['storageQuota']
            value=dict(used=int(q.get('usage',0)),limit=int(q['limit']) if 'limit' in q else None)
        else:
            from services.cloud_storage import get_client
            pages=get_client().get_paginator('list_objects_v2').paginate(Bucket=S3_BUCKET)
            value=dict(used=sum(o['Size'] for page in pages for o in page.get('Contents',[])),limit=None)
        value.update(at=time.time(),error=None)
    except Exception as exc: value=dict(at=time.time(),error=str(exc)[:500])
    with connect() as db: db.execute('UPDATE workers SET capacity=? WHERE provider=?',(json.dumps(value),provider))

def heartbeat(provider):
    with connect() as db: db.execute('UPDATE workers SET heartbeat=? WHERE provider=?',(time.time(),provider))

def pause(provider, paused):
    if provider not in ('aws','drive') or type(paused) is not bool: raise ValueError('Invalid pause setting')
    with connect() as db: db.execute('UPDATE workers SET paused=? WHERE provider=?',(int(paused),provider))

def status():
    with connect() as db:
        result=dict(mode=db.execute('SELECT mode FROM settings').fetchone()[0],disk=space(),retention_days=7)
        result['last_scan']=dict(r) if (r:=db.execute('SELECT * FROM scans ORDER BY started DESC LIMIT 1').fetchone()) else None
        result['providers']={}
        for p in ('aws','drive'):
            w=dict(db.execute('SELECT * FROM workers WHERE provider=?',(p,)).fetchone())
            w['alive']=bool(w['heartbeat'] and time.time()-w['heartbeat']<150)
            w['capacity']=json.loads(w['capacity']) if w['capacity'] else None
            w.update(dict(db.execute('''SELECT COUNT(*) total,COALESCE(SUM(required=1 AND verified IS NULL),0) pending,
              COALESCE(SUM(verified IS NOT NULL),0) verified,COALESCE(SUM(deleted),0) cleaned FROM jobs WHERE provider=?''',(p,)).fetchone()))
            result['providers'][p]=w
        result['errors']=[dict(r) for r in db.execute('SELECT name,provider,error FROM jobs WHERE error IS NOT NULL AND required=1 LIMIT 10')]
        result['errors'] += [dict(r) for r in db.execute("SELECT name,'original' provider,error FROM originals WHERE error IS NOT NULL LIMIT 5")]
        result['originals']=dict(db.execute('''SELECT COUNT(*) total,COALESCE(SUM(deleted),0) cleaned,
          COALESCE(SUM(deleted=0 AND taken<=?),0) older_than_week FROM originals''',(time.time()-RETENTION,)).fetchone())
    from services import drive_spool
    dirs={**ROOTS,'thumbnails':ROOTS['original']/'.thumbnails','legacy_aws':BASE_DIR/'images_upload','legacy_drive':drive_spool.SPOOL}
    def directory_bytes(root):
        total=0
        for folder, children, files in os.walk(root,followlinks=False):
            children[:]=[n for n in children if not (Path(folder)/n).is_symlink()]
            for name in files:
                path=Path(folder)/name
                try:
                    if not path.is_symlink(): total+=path.stat().st_size
                except FileNotFoundError: pass  # Concurrent worker cleanup.
        return total
    result['directories']={k:directory_bytes(v) for k,v in dirs.items()}
    result['directories']['original']-=result['directories']['thumbnails']
    return result
