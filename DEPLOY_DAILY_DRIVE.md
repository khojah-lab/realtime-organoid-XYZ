# Pi deployment — keep Drive disabled until camera recovery is confirmed

Current remote service/camera state has NOT been verified. SSH from this workspace
timed out. Start by confirming the website and camera on the user's existing Pi
terminal (read-only):

```bash
systemctl is-active xyz.service
curl -sS --max-time 5 http://127.0.0.1:3000/hardware_status
journalctl -u xyz.service -n 40 --no-pager
```

Do not proceed to activation until camera state has been checked and an appropriate
brief service restart window is available. Do not change AUTO_SCAN_ENABLED.

## 1. Transfer only Drive files

The delivery ZIP contains services/drive_backup.py, dev/backup_drive.py,
dev/authorize_drive.py and documentation; no credentials, photos, config.py,
server.py, camera code or motor code. Extract it into a NEW staging directory on
the Pi. Preserve copies of the three existing files before replacing them. Keep
the automatic Drive flag false. Existing running Python processes retain the old
module until a service restart; copying files alone does not activate them.

## 2. Configure the existing service drop-in

Edit the observed file:

```bash
sudo nano /etc/systemd/system/xyz.service.d/90-drive-backup.conf
```

Keep all existing unrelated settings. Replace/add these lines under [Service]:

```ini
Environment="XYZ_DRIVE_BACKUP_ENABLED=false"
Environment="XYZ_DRIVE_FOLDER_ID=1ZIO_pjMMXZ1M5lLLFCAXVSh92ZX_CRiK"
Environment="XYZ_DRIVE_EXPECTED_EMAIL=khojahlab@gmail.com"
```

At the chosen activation time, generate ONE fixed timestamp:

```bash
date --iso-8601=seconds
```

Save that exact output in this additional line, replacing the placeholder:

```ini
Environment="XYZ_DRIVE_START_AT=PASTE_FIXED_TIMESTAMP_HERE"
```

Do not leave the placeholder, use shell substitution inside Environment, or
regenerate this value during subsequent restarts. No cutoff has been chosen by
the local patch. Preserve XYZ_DRIVE_TOKEN_FILE and XYZ_DRIVE_STATE_FILE.

## 3. Check account/root without uploading

From /home/khojahlab/SpringXYZ, use the exact same fixed timestamp:

```bash
XYZ_DRIVE_FOLDER_ID=1ZIO_pjMMXZ1M5lLLFCAXVSh92ZX_CRiK \
XYZ_DRIVE_EXPECTED_EMAIL=khojahlab@gmail.com \
XYZ_DRIVE_START_AT='PASTE_FIXED_TIMESTAMP_HERE' \
XYZ_DRIVE_TOKEN_FILE=/home/khojahlab/SpringXYZ/drive_token.json \
./venv/bin/python dev/backup_drive.py --check
```

If it fails, leave Drive disabled. Do not share the token or run authorization
again blindly. Root ownership or the existing token identity may need correction.

## 4. Activate only after checks

Change just XYZ_DRIVE_BACKUP_ENABLED to true in the drop-in. The following restart
briefly interrupts the website/camera, so do it between scans:

```bash
sudo systemctl daemon-reload
sudo systemctl restart xyz.service
systemctl is-active xyz.service
```

Take one new six-well scan, confirm each file is in capture-date/well and owned by
lab. Verify no pre-cutoff files appeared, camera preview works and AWS still works.
Check logs with journalctl -u xyz.service -n 60 --no-pager.
A later restart must retain the same timestamp and receipt database.

If validation fails, change only the Drive flag back to false and apply it with
one brief restart. Never stop the whole service as the ongoing solution for
pausing Drive. Do not delete old images or the previous test directory.
