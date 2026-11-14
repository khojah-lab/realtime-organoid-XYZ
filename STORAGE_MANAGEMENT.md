# Storage management v2

The web Image storage panel selects AWS only, Drive only, or both. Validate & apply
changes future scans; a running scan retains its stored mode. The scheduler,
camera settings, well positions, motion sequence and LED sequence are unchanged.

## Files and deletion

New captures are encoded once and durably saved to images/. The storage database
records intent and the required providers before publication. Independent workers
materialize their own full copy in aws_spool/ or drive_spool_v2/ before uploading.
If interrupted after the original is published, the worker recovers the copy.
Interrupted/incomplete originals remain visible as errors and are never deleted.

AWS preserves the existing bucket/region and YYYY/MM/DD/HH/name keys. New AWS
uploads use a full S3 GET SHA-256 comparison, including when recovering an upload
without a local success receipt. Existing conflicting keys are never overwritten.
This requires GetObject as well as PutObject and adds a read request/download.
Drive keeps capture-date/well/name folders and MD5 verification. Both record
success durably before cleanup. Failure retries use 60 seconds up to one hour.

AWS verified copies are removed on a subsequent worker cycle; Drive copies stay
at least 600 seconds. Maintenance can be delayed by network requests. Registered
originals are removed only after 7 x 24 hours since capture AND every remaining
required provider has a verified receipt. Matching thumbnails are then removed.
Changed originals/copies are retained with an error. No cloud objects are deleted.

Only new, registered originals are eligible. Old images/ originals and earlier
upload records are not silently adopted or deleted. Legacy images_upload/ and
drive_spool/ queues keep draining under their previous rules. The UI shows their
disk usage separately; new queue counters exclude legacy tasks.

Retire destination previews only completed scans with a verified other required
destination. Confirmation cancels those pending requirements and records an audit.
It never waives the last backup or changes future scan settings. Verified backups
are not deleted. Originals still obey 7-day retention. Preview must be refreshed
if qualifying filenames change. This feature applies to v2 registered photos.

## Monitoring

The panel shows directory bytes (logical file size), filesystem free/total space,
provider heartbeats, queues, errors and cleanup counters. Drive quota is for the
whole Google account. AWS usage sums current object sizes hourly using ListBucket;
it excludes previous object versions, incomplete multipart uploads and billing
overheads. Missing permissions produce an unavailable message, not a zero value.
Large buckets incur paginated LIST requests. Cloud statistics display timestamps.

Low space means free < max(1 GiB, 10% total). New scans are blocked below
max(512 MiB, 3% total). Existing scans are not forcibly interrupted. Uploads and the
web UI continue. Scheduled scans check again at the next scheduled time after space
is restored. Pending photos are not force-deleted to make room.

## Deploy on Pi

Back up the current code and runtime databases first. Preserve Pi-local scanner
and config changes (including AUTO_SCAN_ENABLED) when pulling; resolve conflicts
before restarting. Do not delete tokens, databases or image folders.

All three existing services use the same new code. Deploy between scans, then:

```bash
sudo systemctl restart xyz.service xyz-aws-upload.service xyz-drive-upload.service
systemctl is-active xyz.service xyz-aws-upload.service xyz-drive-upload.service
```

The website/preview briefly reconnects. On first use mode inherits BOTH if the old
Drive control was enabled, otherwise AWS only. Check the applied mode in the panel.
Old clients using enabled/paused control payloads must refresh the page.

Existing /etc/xyz-storage.env remains valid. S3 requires GetObject and PutObject;
HeadBucket validation and cloud usage require bucket listing permission. Drive uses
the existing lab OAuth credential/root checks. No new credentials are committed.

## Acceptance

For each mode verify that only selected destinations receive six new well photos.
Change mode mid-scan: the current scan remains unchanged. Verify per-provider
success and local copy cleanup. Pause/resume a provider to verify durable backlog.
Validate Drive date rollover. Seven-day deletion is unit-tested with injected
time; do not change the Pi clock to test retention. Check that old unregistered
originals stay untouched. Preview a retired pending destination only after another
provider verified; confirm and inspect the resulting required-provider state.

Local validation: 43 tests passed with mock cloud/hardware and isolated files.
Cloud permissions, actual quotas and hardware capture require Pi acceptance.
