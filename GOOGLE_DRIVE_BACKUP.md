# Google Drive backup

The active implementation now uses the website-controlled, independent Drive
spool. See [DRIVE_STORAGE_WORKFLOW.md](DRIVE_STORAGE_WORKFLOW.md) for behavior,
one-time service deployment, acceptance checks and rollback.

services/drive_backup.py retains API/checksum helpers and legacy routines for
compatibility/tests. Its old directory-scanning worker is no longer started by
server.py. Do not manually start it; it is not the new admission/cleanup workflow.
