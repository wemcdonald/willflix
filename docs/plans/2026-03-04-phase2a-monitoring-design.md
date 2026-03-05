# Phase 2a: Comprehensive Service & Backup Monitoring — Design

**Date**: 2026-03-04
**Status**: Approved
**PRD**: `docs/lafayette-health-monitoring-prd.md`, Phase 2 (monitoring subset)
**Depends on**: Phase 1 (willflix-notify)

---

## Goals

Add monitoring for Docker containers, systemd units, and backup freshness. All monitoring scripts use `willflix-notify` for alerting and are independent cron jobs.

**Deliverables:**
- `willflix-check-docker` — container health monitoring
- `willflix-check-systemd` — failed unit monitoring
- `willflix-check-backups` — backup freshness monitoring
- Config files for ignore lists and backup definitions
- Crontab and heartbeat updates
- Stamp file integration for existing backup jobs

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Three independent scripts | One can fail without killing the others. Matches PRD principle: "independent cron jobs are more resilient." |
| Container list | Auto-discover from compose | Parse docker-compose.yml for expected services. No hardcoded list to maintain. |
| Systemd approach | Monitor + ignore list | Ignore known legacy units. Alert on anything new. Clean up legacy later. |
| Backup monitoring | Config-driven freshness checks | Each backup touches a stamp file on success. Monitor checks freshness against configured thresholds. |
| Check frequency | Every 15 minutes (docker/systemd), daily (backups) | Matches existing mergerfs check cadence. Low overhead. |

---

## willflix-check-docker

**Source:** Auto-discovers expected services from `/docker/config/docker-compose.yml` by extracting top-level service names (2-space indented, no further indent).

**Ignore list:** `etc/willflix-check-docker.ignore` — one container name per line, `#` comments.

**Detection:**

| Condition | Severity | Dedup Key |
|-----------|----------|-----------|
| Expected container not running (exited/missing) | CRITICAL | `docker-stopped-<name>` |
| Container unhealthy (healthcheck failing) | WARNING | `docker-unhealthy-<name>` |
| Container restarting (crash-loop) | CRITICAL | `docker-crashloop-<name>` |

**Cron:** Every 15 minutes.

**Freshness stamp:** `/var/tmp/willflix-monitors/willflix-check-docker`

---

## willflix-check-systemd

**Source:** `systemctl --failed --no-legend` output, filtered against ignore list.

**Ignore list:** `etc/willflix-check-systemd.ignore` — ships with:
```
certbot.service
courier-imap-ssl.service
mount-all.service
nginx.service
vncserver@1.service
Volumes-MediaJ.mount
```

**Detection:**

| Condition | Severity | Dedup Key |
|-----------|----------|-----------|
| Unexpected failed unit | WARNING | `systemd-failed-<unit>` |

WARNING not CRITICAL — a failed systemd unit is rarely an emergency on this server. Docker check handles critical services.

**Cron:** Every 15 minutes.

**Freshness stamp:** `/var/tmp/willflix-monitors/willflix-check-systemd`

---

## willflix-check-backups

**Config:** `etc/willflix-check-backups.conf` — each line: `<name> <max_stale_hours> <stamp_file>`

```
backup_plex          36  /var/tmp/willflix-monitors/backup_plex
backup_calibre       36  /var/tmp/willflix-monitors/backup_calibre
backup_google_photos 36  /var/tmp/willflix-monitors/backup_google_photos
backup_gmail         36  /var/tmp/willflix-monitors/backup_gmail
backup_home          36  /var/tmp/willflix-monitors/backup_home
plex_db_backup       36  /var/tmp/willflix-monitors/plex_db_backup
restic_backup        36  /var/tmp/willflix-monitors/restic_backup
```

36 hours = daily job + 12-hour grace period.

**Detection:**

| Condition | Severity | Dedup Key |
|-----------|----------|-----------|
| Stamp file missing (never ran) | WARNING | `backup-stale-<name>` |
| Stamp older than max_stale_hours | WARNING | `backup-stale-<name>` |

**Cron:** Once daily at 9:15am (after heartbeat).

**Freshness stamp:** `/var/tmp/willflix-monitors/willflix-check-backups`

---

## Stamp File Integration

**Backup jobs in will's crontab** need `&& touch /var/tmp/willflix-monitors/<name>` appended. Lightest touch — no modifying scripts outside this repo.

**restic-backup (Docker container):** Runs inside a container on schedule. Needs a post-backup hook or wrapper to touch the stamp file on the host. Addressed during implementation.

**root's backup_plex:** Already in this repo, can add stamp directly like Phase 1 migrations.

---

## Cron Schedule

```
# Service health checks (every 15 min)
*/15 * * * * /home/will/bin/cron/willflix-check-docker
*/15 * * * * /home/will/bin/cron/willflix-check-systemd

# Backup freshness (daily, after heartbeat)
15 9 * * * /home/will/bin/cron/willflix-check-backups
```

---

## Heartbeat Updates

Add to freshness monitors in `willflix-heartbeat`:
```
willflix-check-docker 45
willflix-check-systemd 45
willflix-check-backups 2880
```

---

## File Layout

**In repo:**
```
willflix/
├── bin/cron/
│   ├── willflix-check-docker
│   ├── willflix-check-systemd
│   └── willflix-check-backups
├── etc/
│   ├── willflix-check-docker.ignore
│   ├── willflix-check-systemd.ignore
│   └── willflix-check-backups.conf
```
