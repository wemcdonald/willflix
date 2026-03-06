# Offsite & Expanded Local Backup — Design

**Date**: 2026-03-05
**Status**: Complete
**Depends on**: Phase 2b (backup_postgres), repo consolidation

---

## Goals

Close the offsite backup gap. Ensure that fire, theft, or multi-drive failure doesn't cause permanent data loss. Expand local backups to cover the entire root SSD.

**Deliverables:**
- `bin/cron/backup_restic` — host-based restic backup of root SSD → Bonus1 + B2
- Irreplaceable media pool data → B2
- Plex database → B2 (via root SSD backup, since Plex is on `/Volumes/Plex`)
- Retire the Docker-based restic container

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Offsite provider | Backblaze B2 | Cheapest per-GB, native restic support, no egress fees to Cloudflare |
| Restic execution | Host cron, not Docker container | Need to back up `/`, not just `/willflix`. Simpler to run restic natively. |
| Root SSD backup | Whole drive with exclusions | Catches everything — ~/bin, ~/tmp, ~/code, /var/www, anything forgotten |
| Pool irreplaceables | Separate restic paths in same B2 repo | Photos, personal data. Weekly cadence since it rarely changes. |
| Plex local backup | Already done (backup_plex rsync) | No changes needed |
| Plex DB offsite | Included in root SSD backup → B2 | The Plex SSD mounts at /Volumes/Plex, add to restic sources |
| Docker restic container | Retire | Replaced by host-based restic |

---

## Architecture

```
Host cron (backup_restic)
  └─ restic backup
       ├─ Sources: /, /Volumes/Plex, /Volumes/Media/{Photos,Google Photos,...}
       ├─ Local repo:  /Volumes/Bonus1/lafayette
       └─ Remote repo: b2:willflix-backup:lafayette
```

Single restic invocation, two repositories. Restic supports `--repo` and `--repo2` for copying between repos, but the simplest approach is two sequential backups: local first, then B2.

---

## `bin/cron/backup_restic`

Replaces the Docker-based restic-backup container.

**Sources:**
- `/` (root SSD — everything)
- `/Volumes/Plex` (Plex SSD — database + metadata)
- `/Volumes/Media/Photos` (irreplaceable personal photos)
- `/Volumes/Media/Google Photos` (backup of Google, but canonical is Google)
- `/Volumes/Media/Code` (old code backups)

**Exclusions:**
- `/var/lib/docker` — container layers, images, volumes (appdata is in /willflix)
- `/var/log` — regenerable
- `/var/cache` — regenerable
- `/snap` — regenerable
- `/proc`, `/sys`, `/dev`, `/run`, `/tmp`, `/mnt` — virtual/transient
- `/Volumes` — handled explicitly (Plex + selected Media dirs only)
- `/docker.old` — dead, pending deletion
- `/willflix/.git` — repo is on GitHub
- `**/node_modules`, `**/.next`, `**/__pycache__`, `**/.cache` — regenerable
- `/Volumes/Plex/Plex Media Server/Cache/Transcode` — transient transcodes

**Schedule:** Daily 3:30am (same as current restic container)

**Flow:**
1. Backup to local repo (`/Volumes/Bonus1/lafayette`)
2. Backup to B2 repo (`b2:willflix-backup:lafayette`)
3. Apply retention policy to both repos
4. Touch freshness stamp
5. Alert on failure

**Retention:**
- Keep last 10 snapshots
- Keep daily for 14 days
- Keep weekly for 8 weeks
- Keep monthly for 24 months

---

## B2 Setup (one-time)

1. Create Backblaze B2 account
2. Create bucket: `willflix-backup` (private)
3. Create application key (read/write to that bucket only)
4. Store credentials:
   - `secrets/b2_account_id`
   - `secrets/b2_application_key`
5. Initialize restic repo: `restic -r b2:willflix-backup:lafayette init`

---

## Retire Docker restic container

Remove the `backup` service from `docker/compose.yml`. The `drestic` alias in `~/` can be updated to point at the host restic with the local repo path.

---

## Monitoring

- `backup_restic` touches `/var/tmp/willflix-monitors/backup_restic`
- Add to `willflix-heartbeat` freshness monitors
- Add to `willflix-check-backups` config
- Alerts via willflix-notify on any failure

---

## Config

New in `etc/willflix-notify.config`:
```bash
# Restic backup
RESTIC_LOCAL_REPO="/Volumes/Bonus1/lafayette"
RESTIC_REMOTE_REPO="b2:willflix-backup:lafayette"
RESTIC_PASSWORD_FILE="/willflix/secrets/restic_password"
```

New secrets:
- `secrets/b2_account_id`
- `secrets/b2_application_key`

---

## File changes

**New:**
- `bin/cron/backup_restic`
- `secrets/b2_account_id`
- `secrets/b2_application_key`

**Modified:**
- `docker/compose.yml` — remove `backup` service
- `etc/root-crontab` — replace Docker restic with `backup_restic`
- `etc/willflix-notify.config` — add restic/B2 config
- `bin/cron/willflix-heartbeat` — add `backup_restic` to freshness monitors
- `etc/willflix-check-backups.conf` — add `backup_restic` entry

**Prerequisite (manual):**
- Install restic on host: `sudo apt install restic`
- Create B2 account and bucket
- Initialize both restic repos
