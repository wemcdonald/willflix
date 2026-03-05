# Phase 2b: PostgreSQL Backup & System Cleanup — Design

**Date**: 2026-03-04
**Status**: Approved
**PRD**: `docs/lafayette-health-monitoring-prd.md`, Phase 2 (backup + cleanup subset)
**Depends on**: Phase 1 (willflix-notify), Phase 2a (monitoring)

---

## Goals

Close the critical PostgreSQL backup gap and clean up system cruft (ofelia, legacy systemd units).

**Deliverables:**
- `backup_postgres` — daily per-database pg_dump with auto-discovery
- Ofelia disabled (commented out in compose)
- Legacy systemd units disabled and cleaned up

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Dump method | Per-database pg_dump + globals-only | Easy single-database restore (common case). `pg_dumpall` makes restoring one DB painful. |
| Database list | Auto-discover from pg_database | Future databases get backed up automatically. |
| Destination | /Volumes/Bonus1/postgres-backup/ | Off root SSD, same drive as restic and Plex backups. |
| Compression | gzip | Simple, good ratio for SQL. ~30MB total for all DBs. |
| Retention | 14 daily dumps | ~1.3GB total. Trivial. |
| Ofelia | Comment out in compose, stop container | No active jobs. Cron handles everything. |
| Systemd | Disable courier + vncserver, purge courier packages | Remove zombie services causing boot failures. |
| Server-config | Defer to Phase 4 | Disaster recovery docs are a separate scope. |

---

## backup_postgres

**Auto-discovery:** Queries `pg_database` for all non-template, non-system databases. Currently returns: authentik, nextcloud, healthdata, will. Any future databases included automatically.

**Per run:**
1. `pg_dumpall --globals-only` → `globals-YYYY-MM-DD.sql.gz`
2. For each discovered database: `pg_dump <db>` → `<db>-YYYY-MM-DD.sql.gz`
3. Delete dumps older than 14 days
4. Alert via willflix-notify on any failure
5. Touch freshness stamp

**Restore a single database:**
```bash
gunzip -c authentik-2026-03-04.sql.gz | docker exec -i config-postgres-1 psql -U will authentik
```

**Schedule:** Daily 2:30am (after other backups, before restic at 3:30am).

**Directory:**
```
/Volumes/Bonus1/postgres-backup/
├── globals-2026-03-04.sql.gz
├── authentik-2026-03-04.sql.gz
├── nextcloud-2026-03-04.sql.gz
├── healthdata-2026-03-04.sql.gz
└── will-2026-03-04.sql.gz
```

---

## Ofelia

Comment out the entire ofelia service in `/willflix/docker/compose.yml`. Run `docker compose stop ofelia`. Since it's no longer a defined service, the Docker health check won't look for it.

---

## Legacy Systemd Cleanup

**Disable:**
- `sudo systemctl disable courier-imap-ssl.service`
- `sudo systemctl disable vncserver@1.service`

**Purge courier remnants:**
- `sudo dpkg --purge courier-imap courier-base courier-authdaemon courier-authlib`

**Update ignore list:** Remove cleaned-up units from `etc/willflix-check-systemd.ignore`.

---

## File Changes

**New:** `bin/cron/backup_postgres`

**Modified:**
- `etc/willflix-check-backups.conf` — add backup_postgres entry
- `etc/root-crontab` — add backup_postgres at 2:30am
- `etc/willflix-check-systemd.ignore` — remove cleaned-up units

**Manual (outside this repo):**
- `/willflix/docker/compose.yml` — comment out ofelia
- `docker compose stop ofelia`
- `systemctl disable` + `dpkg --purge` for legacy units
- `sudo crontab etc/root-crontab`
