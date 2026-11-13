# Independent Google Drive backup

This branch preserves the original AWS upload, camera, motor controls, scheduled
six-well scan, detection, image browser, thumbnails and ZIP download.
The website continues to read AWS. Google Drive is a separate backup destination,
not a replacement for the image browser and not a copy sourced from S3.

## Data flow

- Scanner publishes a complete JPEG atomically into images/.
- Existing AWS flow copies to images_upload/, uploads to S3 and clears its staging.
- Separate Drive worker reads images/ directly, uploads and checks Drive's MD5.
- drive_backup.sqlite3 records successful Drive transfers independently of AWS.
- Drive never deletes images/ or images_upload/, never requires AWS credentials,
  and never waits for AWS to succeed. Failure on either destination does not gate
  the other. Both still require local disk space and a working network.

Source names and scan order are unchanged:
bottom_right, bottom_center, bottom_left, top_left, top_center, top_right.
Each has its own subfolder in:
https://drive.google.com/drive/folders/1ttE0_okxThWxGyPuAqLBbRuuzV2Gzxa5

Example: top_left/top_left_20261113_120141.jpg
Timestamp follows the original scanner's America/Los_Angeles local time.
The original seconds-only naming is retained for compatibility with the existing
AWS browser. Avoid capturing the same well twice in a second or across repeated
DST wall-clock times; source-name collisions are a pre-existing scanner limitation.
A different-content name collision on Drive is logged rather than overwritten.

## Setup on your computer

1. Enable Google Drive API in a Google Cloud project.
2. Configure OAuth consent; for External Testing add the uploading Google account
   as a test user. It needs Editor access to the target folder.
3. Create an OAuth client of type Desktop app; download its JSON to the repository
   as drive_client_secret.json.
4. In the Python environment used for this project:
   
       python -m pip install -r requirements-drive.txt
       python dev/authorize_drive.py

5. Log in and approve access in the browser. The helper writes drive_token.json
   and finds/creates the six well folders. Keep both JSON files private.
   It requests the Drive scope because this is an existing folder supplied by URL;
   that scope grants wider Drive access, while this code targets only the configured
   folder and its well folders. The chat's Drive connection is separate from this token.

An External OAuth app in Testing can issue refresh tokens that expire after seven
days; address the consent application's production/internal status before unattended
long experiments. School policy may require administrator approval.

## Raspberry Pi

Install requirements-drive.txt in the existing Pi environment (requirements.txt
and its AWS dependency are unchanged). Transfer the token privately to the Pi and
restrict its filesystem permissions to the service account. Configure:

    XYZ_DRIVE_BACKUP_ENABLED=true
    XYZ_DRIVE_FOLDER_ID=1ttE0_okxThWxGyPuAqLBbRuuzV2Gzxa5
    XYZ_DRIVE_TOKEN_FILE=/home/khojahlab/SpringXYZ/drive_token.json

Set these as exported environment variables or in the existing xyz.service
Environment/EnvironmentFile. The program does not automatically read .env.
Reload systemd if its configuration changed, then restart the existing service.

Drive backup is OFF by default so existing main behavior works without Google
packages or authorization. When enabled, the first pass runs on server startup
and subsequent passes run every 60 seconds (XYZ_DRIVE_BACKUP_INTERVAL, minimum 10).
Set the flag false and restart to disable it.

To run only Drive backup, without starting AWS, cameras or the website:

    python dev/backup_drive.py

This explicit command runs one pass even when the automatic-worker flag is false.
Run it with the automatic worker stopped. Use only one uploader process per target.
The worker lock prevents duplicate concurrent passes in one server process.

## Recovery and operations

Enabling backup also backs up existing matching JPEGs in images/, not just future
scans. It never downloads historical images from AWS.
Pending files are retried after network/authentication errors. Restarting the
server uses the SQLite receipt log to skip already verified, unchanged captures.
If an upload succeeded before a crash, the next pass finds the existing Drive
filename and checksum before recording success, preventing another copy.
Duplicate well folders or conflicting files require human review.

Do not delete original images before backup finishes. Existing local originals are
retained, so monitor disk space. Successful receipt entries are not a continuous
remote integrity audit: manually deleting a backed-up Drive file will not trigger
automatic recreation. To deliberately recheck/rebuild from local originals, stop
the worker and use a NEW state file via XYZ_DRIVE_STATE_FILE (or --state).
Keep the old state file for audit; reruns reuse matching remote files.

## Validation

Offline tests mock Google API calls and hardware, and exercise capture-to-backup
routing, all six names, retries, durable receipts, pagination, collision handling,
checksum failures, and AWS deletion/failure independence.

    python -m unittest discover -s tests -p "test_drive_backup.py" -v

Live acceptance after OAuth setup: run one scan, check six Drive folders, confirm
the original AWS image browser/ZIP still work, then test Drive with AWS unavailable
and AWS with Drive unavailable. Real hardware and live authorization are not
validated by the offline tests.

References:
https://developers.google.com/workspace/drive/api/guides/manage-uploads
https://developers.google.com/identity/protocols/oauth2/native-app
