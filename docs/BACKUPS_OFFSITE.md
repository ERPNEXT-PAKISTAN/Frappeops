# Offsite Backups (S3 / Drive / Dropbox)

## Setup

1. Desk → **Backup Destination** → New
2. Choose provider:
   - **S3 Compatible / AWS S3** — bucket + access key + secret (optional endpoint for Contabo/MinIO/Backblaze). Needs `boto3` in the bench env, or set **Rclone Remote**.
   - **Google Drive / Dropbox** — install [rclone](https://rclone.org), run `rclone config`, set **Rclone Remote** (e.g. `gdrive`, `dropbox`).
3. FrappeOps Settings → **Default Backup Destination**, optionally **Auto Upload Backups Offsite**.

## Commands

| Action | Purpose |
|--------|---------|
| `site.backup` | Local backup (+ auto offsite if enabled) |
| `backup.upload_offsite` | Upload an existing Backup (confirm=1) |
| `backup.test_destination` | Head-bucket / rclone lsd check |

```bash
# Example: upload latest backup
bench --site frappeops.local execute frappeops.services.operations.runner.run_action \
  --kwargs "{'action_key':'backup.upload_offsite','target_type':'backup','target_name':'BKP-000001','params':{'confirm':1}}"
```

Secrets stay in Password fields; job logs redact keys.
