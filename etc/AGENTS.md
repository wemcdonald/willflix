# /willflix/etc — System Config Source of Truth

Files here are the **canonical versions** of system config files. They are maintained in git and deployed to their system locations by `rebuild-lafayette`.

## Deployment Map

| Repo file | System location | Deployed by |
|-----------|----------------|-------------|
| `smartd.conf` | `/etc/smartd.conf` | `rebuild-lafayette` + `sudo systemctl restart smartd` |
| `snapraid.conf` | `/etc/snapraid.conf` | `rebuild-lafayette` |
| `fstab` | `/etc/fstab` | Manual (review before applying) |
| `root-crontab` | `sudo crontab -l` | `rebuild-lafayette` via `crontab root-crontab` |
| `willflix-check-backups.conf` | Read by `bin/cron/willflix-check-backups` | Direct (same path) |
| `willflix-services.conf` | Read by `bin/cron/willflix-check-services` | Direct (same path) |
| `willflix-notify.config` | Read by `bin/willflix-notify` | Direct (same path) |
| `systemd/` | `/etc/systemd/system/` | `rebuild-lafayette` |
| `backup.d/` | Backup job configs | Read by backup scripts |
| `logrotate.d/willflix` | `/etc/logrotate.d/willflix` | Symlink (created manually) |

## Editing Rules

- **Always edit the repo copy first**, then deploy to the system location.
- Never edit `/etc/smartd.conf`, `/etc/snapraid.conf`, or root crontab directly — `rebuild-lafayette` will overwrite your changes.
- Exception: `/etc/fstab` changes should be tested in-place first, then synced back here.
