# Setup Scripts and Host Context

Installation scripts and documentation for the host system.

## Host Environment

- **OS:** Ubuntu Linux
- **Hostname:** lafayette
- **Key packages:** docker-ce, ffmpeg, rclone, tailscale, smartmontools, git-crypt, mergerfs

## File Inventory

| File | Purpose |
|------|---------|
| `systemd-setup.sh` | Scans `/docker/systemd/`, symlinks all `.service` files, enables them |
| `mail-setup.sh` | Configures host mail routing through Docker smtp-relay |
| `README-systemd.md` | Systemd service management documentation |
| `README-mail.md` | Docker mail routing system documentation |
| `README-backups.md` | Restic backup operations, restore procedures, troubleshooting |
| `apt-list.txt` | Inventory of ~70 host packages |

## When Modifying Host Setup

- **Package additions**: update `apt-list.txt` to keep inventory current
- **New systemd services**: add `.service` file to `/docker/systemd/`, then run `systemd-setup.sh` or follow manual steps in `systemd/AGENTS.md`
- **Mail config changes**: edit `mail-setup.sh` and re-run, or apply manually per `README-mail.md`
