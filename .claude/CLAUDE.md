# Willflix Server (lafayette)

This is the ops repo for a personal headless Ubuntu server (hostname: `lafayette`) running a self-hosted media stack, SSO infrastructure, and backup systems. It runs for years unattended — reliability and monitoring are paramount.

## System Overview

- **OS**: Ubuntu 22.04 on Samsung 860 EVO 1TB SSD (root)
- **Hostname**: lafayette
- **Storage**: 11 data drives (MediaA–K) + 3 parity drives in a mergerfs + snapraid array, ~98TB usable
- **Services**: ~40 Docker containers behind Traefik reverse proxy with Authentik SSO
- **Docker config**: Lives in `/docker/` (separate git repo with git-crypt secrets)

## Storage Architecture

### MergerFS Pool
- **Mount**: `/Volumes/Media` (fuse.mergerfs)
- **Members**: `/Volumes/Media[A-K]` (glob pattern in fstab)
- **Create policy**: `mspmfs` (most free space)
- **fstab**: Drives mounted by `LABEL=` with `nofail`

### SnapRAID
- **Config**: `/etc/snapraid.conf`
- **Data disks**: d1–d10 (MediaA–J, MediaK pending addition)
- **Parity**: Triple parity on MediaParity1/2/3
- **Content files**: `/snapraid/snapraid.content` + copies on MediaB–F
- **Cron**: Root crontab runs `snapraid_daily` (Mon–Sat 1am), `snapraid_weekly` (Sun 1am)
- **Staleness monitor**: `check_snapraid_freshness` runs daily at 8:30am

### Drive Health
- **smartd**: Monitors all drives by stable `ata-*` ID paths in `/etc/smartd.conf`
- **Monthly self-tests**: Short on 1st of month, long on 1st Saturday
- **Alerts**: Via sendmail → smtp-relay → Gmail
- **MergerFS health check**: Every 15 minutes via `check_mergerfs_health` cron

## Key Directories

| Path | Purpose |
|------|---------|
| `/docker/` | Docker compose, Traefik, secrets (separate git repo) |
| `/docker/config/docker-compose.yml` | Main compose file |
| `/docker/config/secrets/` | git-crypt encrypted secrets |
| `~/willflix/` | This repo — ops scripts, docs, monitoring |
| `~/willflix/bin/cron/` | Cron scripts (symlinked from `~/bin/cron`) |
| `~/willflix/docs/` | System documentation, postmortems, PRDs |
| `/etc/smartd.conf` | SMART monitoring config (maintained here, applied to system) |
| `/etc/snapraid.conf` | SnapRAID array config |
| `/Volumes/Media*/` | Individual data/parity drive mounts |
| `/Volumes/Media` | MergerFS merged view |
| `/snapraid/` | SnapRAID content file (on root drive) |

## Mail / Alerting

- **Pipeline**: `/usr/sbin/sendmail` → `sendmail-system` script → curl SMTP → `smtp-relay` container → Gmail
- **sendmail-system**: `/docker/bin/sendmail-system` — maps local users to `wemcdonald@gmail.com`
- **Root crontab**: `MAILTO=will` (sendmail delivers cron errors to Gmail)
- **Known issue**: `/usr/bin/mail` command doesn't work; always use `sendmail` or `sendmail -t`

## Common Operations

### Service Management
```bash
# NEVER use bare `docker compose up -d` or `docker compose down`
# ALWAYS specify service names
cd /docker/config && docker compose up -d <service-name>
docker compose logs -f <container-name>
```

### Drive Health
```bash
sudo smartctl -a /dev/disk/by-id/ata-<DRIVE_ID>   # Full SMART info
sudo smartctl -t long /dev/sdX                      # Start long self-test
sudo smartctl -l selftest /dev/sdX                  # View test results
```

### SnapRAID
```bash
sudo snapraid status          # Array status
sudo snapraid diff             # Show pending changes
sudo snapraid sync             # Sync changes to parity
sudo snapraid scrub            # Verify parity integrity
sudo snapraid fix -d dN        # Reconstruct a disk from parity
```

### Monitoring
```bash
# Test that alerting works end-to-end
echo "Test" | /usr/sbin/sendmail wemcdonald@gmail.com
# Check mergerfs pool health manually
sudo ~/bin/cron/check_mergerfs_health
# Check snapraid freshness
sudo ~/bin/cron/check_snapraid_freshness
```

## Known Issues / Watch Items

- **MediaC (sdb)**: Seagate ST33000651AS, 67K hours, 6 pending sectors. Oldest drive, likely next to fail.
- **MediaJ recovery in progress**: Dying drive being rsynced to MediaSpare, then snapraid fix. See `docs/mediaj-recovery-plan.md`.
- **No hot spare**: MediaSpare is being consumed for MediaJ recovery. Need to buy replacement.
- **PostgreSQL has no backup**: authentik, nextcloud, healthdata DBs are unprotected.
- **ofelia**: Crash-looping ("empty scheduler"), needs config fix.
- **authentik-worker**: Unhealthy for 25+ days, stale heartbeat.

## Incident History

- **2026-03-03**: MediaJ drive failure. See `docs/mediaj-postmortem.md` for full analysis.
