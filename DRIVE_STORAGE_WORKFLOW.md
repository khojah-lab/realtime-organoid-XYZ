# Independent Google Drive capture and upload

## Implemented behavior

The website's Google Drive backup panel enables/disables admission of NEW scan
sessions. It never changes AWS configuration. A separate Drive service validates
the expected lab OAuth account/root owner and creates today's YYYY-MM-DD folder
and six empty well folders. Only after that succeeds is Drive marked enabled.
Activation is asynchronous (normally within 60 seconds); no images are imported,
no scan is started. Failure is shown on the page and retried.

Both timer and Scan Now share run_scan. Its process-local scan lock prevents
simultaneous starts. It snapshots Drive enabled/destination once before movement.
Enabling during a scan affects the NEXT full scan. Disabling during a previously
accepted scan still permits all six of that scan's captures. This means admission
covers a complete scan; camera/motor/disk failures can still prevent actual photos.

Each successful frame is encoded as a full-quality JPEG for Drive and saved into:

    drive_spool/<scan-id>/<well>_YYYYMMDD_HHMMSS.jpg

Drive intent and MD5/size are durably registered before file publication. A flushed
.part file is atomically published; recovery only examines registered entries,
never sweeps historical images/ into Drive. Completed interrupted captures recover;
incomplete/missing captures are flagged for review, not fabricated or auto-deleted.
Disk/database failure can still prevent a Drive copy; the website/log reports it.
A Drive failure does not suppress AWS capture, and AWS write/staging failure does
not prevent an already captured frame from being saved for Drive.

The existing AWS path is retained: images/ original -> images_upload/ staging ->
S3 -> removal of successful AWS staging copy. AWS staging publication is now
atomic because its independent worker can run while a scan is in progress.
The old images/ originals remain governed by the existing AWS-side retention
behavior (currently retained). Drive NEVER deletes them. This change prevents
Drive-specific copies accumulating after success; it does NOT clean historical
AWS originals or claim to solve every source of Pi disk usage.

## Workers and cleanup

- xyz.service: web, camera and scanning; no cloud-upload loops.
- xyz-drive-upload.service: Drive activation, retry, checksum verification, receipts,
  and its own cleanup. Uses drive_upload_state.sqlite3; no AWS imports.
- xyz-aws-upload.service: existing AWS uploader on images_upload/ every 60 seconds;
  no Drive imports or Drive deletion permissions in code.

Drive retries after 60, 120, 240 ... seconds up to one hour. Remote matching
filename+MD5 is reused after interrupted uploads; conflicting content is rejected.
All jobs keep their original target folder; changing server target config does
not silently redirect a queued job. Capture dates use America/Los_Angeles even
for delayed uploads or scans crossing midnight. State survives service restarts.

Drive cleanup runs independently of uploads every 60 seconds, including while
admission is OFF or uploads are PAUSED. After verified success + 600 seconds,
it checks the local copy still matches, deletes ONLY that registered Drive file,
and records deletion. Thus normal cleanup is approximately 10–11 minutes after
verification; stopped services, filesystem errors or busy storage can delay it.
Unverified, changed, unregistered or unsafe paths are not auto-deleted. Remote
files are never deleted. Remote manual deletion after verification is not audited.

OFF means stop NEW scan admissions, continue draining existing jobs. PAUSE means
stop taking new upload jobs, leave existing copies; an in-flight request may finish.
Pause does not disable admission, so new Drive copies can accumulate while paused.
The page shows pending/verified/cleaned counts, errors, worker heartbeat and space.
Low-space warning threshold: below 10% free or 1 GiB. It is not a disk reservation;
AWS and Drive still share physical disk/network/power.

## One-time Pi deployment — NOT performed by this local edit

Do not just pull and restart: the upload loops have moved to TWO services.
Back up Pi-local changes and merge the feature branch, including retaining its
AUTO_SCAN_ENABLED support. Do not overwrite calibration/hardware settings.
Do not run legacy backup_once/start_drive_backup or old upload scripts concurrently.
The old dev/backup_drive.py is now diagnostics only; --check does not upload.
Old XYZ_DRIVE_BACKUP_ENABLED/START_AT flags do not control the new Drive admission;
use the website. The new DB defaults to OFF and retains its state on restart.

1. Ensure the Pi venv has requirements-drive.txt and its existing AWS/Flask packages.
2. If /etc/xyz-storage.env already exists, MERGE the example, do not overwrite it:

```bash
sudo install -m 600 deploy/storage.env.example /etc/xyz-storage.env
sudo nano /etc/xyz-storage.env
```

Confirm the target lab folder, token, spool and DB paths. Website and Drive worker
must use exactly the same DB/spool/destination settings. Never set spool to the
AWS directories. Supply AWS credentials via the lab's existing private provider
or env file: workers do not inherit xyz.service drop-in variables automatically.
No credentials are included in Git. Do not delete the new DB while captures exist.

3. Install units and common environment configuration:

```bash
sudo install -m 644 deploy/xyz-drive-upload.service /etc/systemd/system/
sudo install -m 644 deploy/xyz-aws-upload.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/xyz.service.d
sudo install -m 644 deploy/95-drive-spool.conf /etc/systemd/system/xyz.service.d/
sudo systemctl daemon-reload
```

4. Between scans, restart xyz.service to remove old in-process upload workers, then
start the new services. This is a brief, one-time web/camera interruption:

```bash
sudo systemctl restart xyz.service
sudo systemctl enable --now xyz-drive-upload.service xyz-aws-upload.service
systemctl is-active xyz.service xyz-drive-upload.service xyz-aws-upload.service
```

If using the previous experimental storage split, stop its workers before this
migration and preserve its original files/DB for a separately verified migration.
Do not run both protocols simultaneously.

5. Open the panel. Enable Drive, wait for validation, verify empty date folders.
Trigger the next complete scan; verify six well photos in lab Drive. Verify only
Drive copies disappear 10–11 minutes after checksum success; AWS originals/staging
and cloud files are unaffected. Test OFF drain and PAUSE/RESUME. Network failures
must preserve copies and show errors. Check journalctl -u xyz-drive-upload and
journalctl -u xyz-aws-upload. Existing gallery remains AWS-based.

## Rollback

Stop BOTH new uploader services first. Preserve drive_spool and the receipt DB.
Restore the backed-up code and relevant service configuration, then restart the
web service between scans. Do not resume a legacy Drive importer unintentionally.
Already cleaned verified Drive copies remain in the cloud; local deletion cannot
be undone. Pending new-format copies require this worker to drain or manual review.

The existing site has no login; keep it on the trusted lab/private network.
New control requests require same-origin/session CSRF checks, not a new account system.
