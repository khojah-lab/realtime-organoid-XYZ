# Daily Drive validation

21 unittest cases passed on 2026-11-13 (local Windows Python 3.12).
Google API, hardware and AWS calls were mocked; the actual Google client media
wrapper was used for upload stream/closure tests. Dependencies were installed
into an isolated workspace test directory.

Covered: six wells, invalid names, pagination, duplicates, MD5 verification,
interrupted-upload reuse, retries, persistent receipts, target changes, AWS failure
and cleanup independence, disabled worker, historical capture filtering despite
recent filesystem writes, midnight routing, required timezone-aware cutoff,
persisted cutoff consistency, date/well folder parents and lab identity/ownership.

Not verified: live Pi deployment, actual camera frames, current OAuth account,
new root ownership, or a real upload. No production upload was enabled and no
remote images or folders were modified.
