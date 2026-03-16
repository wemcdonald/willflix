---
name: manage-backups
description: Use when checking backup status, restoring files, running manual backups, troubleshooting restic, or performing any backup and recovery operations on the homelab
---

# Restic Backup Management

## Architecture

| Component | Value |
|-----------|-------|
| Container | `mazzolino/restic` (named `restic-backup`) |
| Repository | `/Volumes/Bonus1/lafayette` |
| Schedule | Daily at 3:30 AM |
| Retention | 10 last / 7 daily / 8 weekly / 24 monthly |
| Compression | Max (`--compression max`) |
| Password | `/docker/config/secrets/restic_password` |
| Full docs | `/docker/setup/README-backups.md` |

## Convenience Wrapper

`drestic` = `docker exec restic-backup restic -r /Volumes/Bonus1/lafayette`

All commands below use this wrapper. If unavailable, substitute the full `docker exec` form.

## Quick Reference

| Task | Command |
|------|---------|
| List snapshots | `drestic snapshots` |
| Latest snapshot | `drestic snapshots --latest 1` |
| Snapshot stats | `drestic stats` |
| Check integrity | `drestic check` |
| Manual backup | `drestic backup /path` |
| Restore snapshot | `drestic restore {id} --target /tmp/restore` |
| Restore specific file | `drestic restore {id} --target /tmp/restore --include /path/to/file` |
| Diff two snapshots | `drestic diff {id1} {id2}` |
| Prune old snapshots | `drestic forget --prune` |
| Mount for browsing | `drestic mount /mnt/restic` |

## Common Workflows

### Check backup health

```bash
drestic snapshots --latest 1   # Verify recent backup exists
drestic check                   # Verify repository integrity
```

### Restore a file from latest backup

```bash
# 1. Find the snapshot
drestic snapshots --latest 1

# 2. Browse what's in it (optional)
drestic ls {snapshot_id} /path/to/dir

# 3. Restore specific file
drestic restore {snapshot_id} --target /tmp/restore --include /docker/appdata/myservice/config.yml

# 4. Copy restored file into place
cp /tmp/restore/docker/appdata/myservice/config.yml /docker/appdata/myservice/config.yml

# 5. Clean up
rm -rf /tmp/restore
```

### Find when a file changed

```bash
# List snapshots, then diff adjacent ones
drestic snapshots
drestic diff {older_id} {newer_id}
```

## Emergency Recovery

If the backup container is down and cannot be restarted:

1. Install restic on the host directly
2. Set environment variables:
   ```bash
   export RESTIC_REPOSITORY=/Volumes/Bonus1/lafayette
   export RESTIC_PASSWORD_FILE=/docker/config/secrets/restic_password
   ```
3. Run restic commands directly (same syntax, drop the `drestic` prefix):
   ```bash
   restic snapshots --latest 1
   restic restore {id} --target /tmp/restore
   ```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| No recent snapshots | `docker logs restic-backup --since 24h` |
| Lock contention | `drestic unlock` then retry |
| Integrity errors | `drestic check --read-data` (slow, reads all data) |
| Container not running | `docker ps -a \| grep restic` then `sudo systemctl restart restic-backup` |
