# Daily Google Drive backup

Uploads local originals independently of AWS. Camera, motors, AWS staging,
website and image names are unchanged. Automatic Drive backup stays OFF by default.

## Destination and layout

Root: https://drive.google.com/drive/folders/1ZIO_pjMMXZ1M5lLLFCAXVSh92ZX_CRiK
Expected uploading account AND folder owner: khojahlab@gmail.com.
The worker checks the OAuth identity and root ownership before every pass.
Existing date/well folders must also belong to that lab account. It does not
change sharing permissions. The chat connector could read the new folder name,
but did not return owner information; live validation on the Pi is still required.

    Lab_Realtime_Images/
      2026-11-13/
        bottom_right/
        bottom_center/
        bottom_left/
        top_left/
        top_center/
        top_right/
          top_right_20261113_143052.jpg

Dates and filename timestamps use the existing scanner's America/Los_Angeles
capture time, not the upload time. A day's six well folders are created when its
first eligible image is uploaded. Empty days are not created in advance.
Existing second-resolution filenames are retained for AWS/browser compatibility.
Ambiguous/nonexistent DST wall times are rejected for review; same-well captures
within one second remain a pre-existing filename collision limitation.

## Fixed start time

XYZ_DRIVE_START_AT is REQUIRED, e.g. an ISO timestamp with -08:00 or -07:00 offset,
or +00:00 UTC. Set it once at activation; never recompute it on restart.
No default historical import exists. Captures before the cutoff are counted as
historical and skipped, even if their filesystem timestamps were recently changed.
Captures at/after the cutoff remain eligible after outages and restarts.
The receipt database stores the cutoff per destination and rejects silent changes.
Keep this database and the original configured cutoff. Missing/invalid timestamps
block Drive uploads without blocking the camera/server.

Old Drive folders and local images are never moved or deleted. Historical imports
are not implemented in this realtime worker; plan a separate Archive import if
needed. Do not lower the cutoff to backfill the live directory.

## Local checks

    python -m unittest discover -s tests -p test_drive_backup.py -v

On the Pi, with the same explicit environment as the service:

    ./venv/bin/python dev/backup_drive.py --check

This validates the lab account, root, and timestamp without uploading or creating
folders. Do not run backup_drive.py without --check until ready: an explicit run
uploads even when the automatic worker flag is false. Use only one uploader
process per destination. Existing lock protects threads, not multiple processes.

## Deployment

Follow DEPLOY_DAILY_DRIVE.md. Do not replace the Pi's hardware config.py or server.py.
The new worker imports existing paths/timezone from config.py and reads new policy
variables directly from the environment. Existing target environment overrides
any local default; the service target MUST be changed to the new folder ID.

MD5 validation, retry receipts and interrupted-upload reuse remain active.
Receipts use a daily-layout namespace so old flat-layout receipts are not reused.
Remote deletion is not continuously audited; originals remain local.
OAuth refresh token lifetime and lab storage capacity still require monitoring.
