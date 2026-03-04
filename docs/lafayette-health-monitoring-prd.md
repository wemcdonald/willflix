# Lafayette Server Health Monitoring System — PRD

**Priority**: P1
**Author**: Will McDonald
**Date**: 2026-03-03
**Context**: Written during MediaJ drive failure recovery. This server runs headless for years at a time. Every failure mode in this incident was detectable but undetected.

---

## Vision

A holistic monitoring system for a personal headless server that ensures no failure — drive, service, backup, or infrastructure — goes unnoticed for more than hours. The system should be:

- **Self-healing where possible**: restart crashed services, retry failed backups
- **Redundantly alerting**: no single notification channel failure should cause silence
- **Low-maintenance**: runs for years without attention, alerts only when something needs human action
- **Honest about its own health**: monitors its own monitoring, alerts if alerting is broken

---

## 1. Multi-Channel Notification System

### Problem
During the MediaJ incident, smartd was detecting problems and sending emails, but the alerts may have been missed (spam, inbox noise, email fatigue). A headless server that runs for years needs notifications that are impossible to ignore.

### Requirements

**Channels** (minimum two, independent infrastructure):
- **Email**: Already works via `sendmail-system` → `smtp-relay` → Gmail. Keep as baseline.
- **Push notifications**: ntfy.sh (self-hostable, simple HTTP POST, mobile app with persistent notifications). Primary alert channel for urgent issues.
- **SMS** (critical only): For drive failures, pool degradation, backup system failure. Via ntfy upstream SMS, Twilio, or similar. Reserved for things that need same-day response.

**Channel routing by severity**:
| Severity | Email | Push (ntfy) | SMS |
|----------|-------|-------------|-----|
| INFO (weekly digest, backup OK) | yes | no | no |
| WARNING (stale sync, high temps) | yes | yes | no |
| CRITICAL (drive failure, pool degraded, backup failing) | yes | yes | yes |
| META (alerting system itself broken) | cross-channel: if email fails → ntfy, if ntfy fails → email | | |

**Notification deduplication**:
- Same alert: suppress repeats for 6 hours (configurable per check)
- Escalation: if WARNING not acknowledged in 24h, escalate to CRITICAL

**Implementation**: `lafayette-notify` — a small CLI/library that all monitoring scripts call instead of raw sendmail. Single point of configuration for channels, routing, dedup.

### Depends on
- ntfy server (self-hosted or ntfy.sh SaaS)
- SMS gateway account (or ntfy upstream SMS)

---

## 2. Drive & Storage Health Monitoring

### Problem
MediaJ failed over weeks with 814+ kernel warnings, 488 SMART errors, and a filesystem remount-ro — all unnoticed. MediaC is now showing early signs too. With 11+ spinning drives (several >5 years old), drive failure is not an exception, it's a regular event.

### Requirements

**SMART monitoring** (improve existing smartd):
- Pin drives by `/dev/disk/by-id/` paths (survive device re-enumeration)
- Schedule regular self-tests (short weekly, long monthly)
- Alert on: pending sectors > 0, uncorrectable > 0, reallocated growth, temperature > threshold
- Route through `lafayette-notify` at WARNING (early signs) and CRITICAL (active failure)

**Filesystem monitoring**:
- Detect read-only remounts within minutes (watch `/proc/mounts` or use inotify)
- Detect I/O errors on any mount point (periodic read test)
- Alert immediately — a read-only remount is always urgent

**MergerFS pool monitoring**:
- Verify all expected member drives are mounted, writable, and readable
- Run every 15 minutes
- Alert on any degradation

**SnapRAID monitoring**:
- Staleness check: alert if content file > 3 days old
- Process check: alert if snapraid has been running > 6 hours (likely hung)
- Sync result check: parse sync output for errors, alert on any drive issues
- Parity validation: periodic scrub results should be checked

**Disk space monitoring**:
- Alert when any drive < 50GB free (mergerfs create policy needs headroom)
- Alert when root drive < 10GB free

### Implementation notes
- Most checks are simple bash scripts calling `lafayette-notify`
- Could be unified into a single `lafayette-healthcheck` daemon or kept as independent cron jobs
- Independent cron jobs are more resilient (no single daemon to crash) but harder to manage

---

## 3. Service Health Monitoring

### Problem
During investigation, we found: `ofelia` is crash-looping, `authentik-worker` has been unhealthy for 25+ days, 6 systemd units are failed (including `Volumes-MediaJ.mount`). Nobody noticed any of this.

### Current state discovered during investigation

**Docker containers**:
| Service | Status | Issue |
|---------|--------|-------|
| ofelia | Restarting (crash loop) | "unable to start a empty scheduler" — misconfigured |
| authentik-worker | unhealthy | Worker heartbeat stale for 25+ days |
| All others | Up | OK |

**Systemd units failed**:
| Unit | Issue |
|------|-------|
| Volumes-MediaJ.mount | Expected — dead drive |
| certbot.service | Legacy? Traefik handles certs now |
| courier-imap-ssl.service | Legacy service, probably not needed |
| mount-all.service | Failed at boot (because MediaJ was dead) |
| nginx.service | Legacy — Docker nginx-public/private replaced this |
| vncserver@1.service | Legacy — Docker VNC replaced this |

### Requirements

**Docker container monitoring**:
- Check all expected containers are running
- Detect unhealthy containers (Docker healthcheck failures)
- Detect crash-looping containers (restarting status)
- Detect containers that disappeared entirely
- Route through `lafayette-notify`: unhealthy = WARNING, stopped/crash-loop = CRITICAL

**Systemd service monitoring**:
- Check all Docker-related systemd units in `/docker/systemd/`
- Detect failed units
- Ignore known-legacy units (or clean them up)
- Alert on new failures

**Service dependency monitoring**:
- PostgreSQL down → authentik, nextcloud affected
- Redis down → authentik affected
- Traefik down → all web services unreachable
- VPN down → qbittorrent should stop (kill switch)
- smtp-relay down → all alerting via email broken (alert via ntfy!)

### Implementation notes
- Simple: cron-based checks every 5 minutes
- Advanced: integrate with Docker events API for real-time detection

---

## 4. Backup Integrity Monitoring

### Problem
During investigation, we found:
- SnapRAID last synced May 2025 (10 months stale, nobody noticed)
- Restic backs up only `server-config` (12MB) — no databases, no appdata
- PostgreSQL (authentik, nextcloud, healthdata) has NO backup at all, no `pg_dump` anywhere
- Plex DB backup script exists but destination unclear
- Calibre metadata backup exists but goes to mergerfs (vulnerable to same pool issues)
- `server-config` is not a git repo (no version history, just file snapshots)
- `/docker/` is git-tracked with git-crypt, pushed to GitHub — this is the best backup in the stack

### Requirements

**Backup existence checks** — every critical data store must have a backup:
| Data | Current backup | Gap |
|------|---------------|-----|
| `/docker/` (all config) | Git + GitHub | OK (but verify git-crypt keys are backed up offsite) |
| PostgreSQL (authentik, nextcloud) | **NONE** | CRITICAL: need pg_dump cron |
| Plex database | Script exists, runs daily | Verify destination exists and files are fresh |
| Calibre metadata | Daily to mergerfs | Should also go offsite or to separate drive |
| Audiobookshelf DB | **NONE** | Need backup script |
| Radarr/Sonarr/Prowlarr DBs | **NONE** (in appdata, not backed up) | Need backup or verify re-downloadable |
| Root drive (`/`) | `server-config` snapshot (stale Jul 2025) + restic (12MB) | `server-config` is 8 months stale |
| Media files | SnapRAID triple parity | OK when syncing (currently broken) |
| Secrets (git-crypt keys, SSH keys) | ? | Verify offsite backup exists |

**Backup freshness monitoring**:
- Each backup job should touch a timestamp file on success
- A separate monitor checks all timestamps daily
- Alert if any backup is stale beyond its expected interval

**Backup integrity testing**:
- Periodic restore test (even partial) to verify backups actually work
- SnapRAID scrub validates parity integrity
- Restic `check` validates backup repository integrity
- pg_dump restore test to `/dev/null` validates SQL dumps

**Root drive disaster recovery plan**:
- Document: "if the root SSD dies, here's how to rebuild"
- The `/docker/` git repo + GitHub is the core of this
- But also need: fstab, crontabs, systemd units, `/etc/` customizations, SSH keys
- `server-config` was meant to be this but is 8 months stale

### Implementation notes
- `lafayette-backup-monitor`: checks freshness of all backup timestamp files
- New cron jobs needed: `backup_postgres`, `backup_appdata`
- Update `server-config` or replace with a better mechanism (e.g., etckeeper, or just ensure `/docker/` repo captures everything)

---

## 5. Intelligent Media Change Detection

### Problem
When MediaJ went read-only, hundreds of movies and TV shows silently disappeared from the mergerfs pool. Radarr/sonarr/plex had no way to detect or report this. Users discovered the problem before any system did.

Beyond drive failures, there are other scenarios where media can unexpectedly change:
- Accidental deletion
- Radarr/sonarr replacing a file with a different quality/version
- Disk space pressure causing automated cleanup
- Corrupt downloads replacing good files

### Requirements

This is a new piece of software that needs its own detailed PRD (P2). High-level requirements:

**Core capability**: Maintain a catalog of known media and detect unexpected changes.

**Detection types**:
| Change | Expected? | Alert? |
|--------|-----------|--------|
| Movie file replaced with same movie, different quality | Yes (radarr upgrade) | No |
| Movie file disappeared entirely | No | Yes (CRITICAL) |
| Many files disappeared at once | No (likely drive issue) | Yes (CRITICAL + SMS) |
| TV episode replaced with same episode | Yes (sonarr upgrade) | No |
| TV episode disappeared | Maybe (cleanup?) | Yes (WARNING) |
| New content added | Yes | No |
| Bulk disappearance from one drive path | No (drive failure) | Yes (CRITICAL) |

**AI/judgment component**:
- Use filename/metadata parsing to determine if a replacement is the "same content" in different quality
- Distinguish between "radarr upgraded my copy" and "something went wrong"
- Configurable thresholds: alert if >N movies disappear in a day, don't alert for individual TV episode churn
- Daily digest of changes for awareness (not urgent alerts)

**Integration**:
- Could query radarr/sonarr APIs to correlate changes with intentional actions
- Could use snapraid diff output as a data source
- Could maintain its own file inventory via periodic filesystem scan

**Non-requirements** (keep it simple):
- Does not need to prevent changes, only detect and report
- Does not need real-time detection — hourly or daily scan is fine
- Does not need to track non-media files (config, databases, etc. — covered by backup monitoring)

### Implementation notes
- P2 PRD needed — this is the most complex component
- Likely a Python service with a SQLite inventory database
- Runs as a cron job or lightweight daemon
- Calls `lafayette-notify` for alerts

---

## 6. Meta-Monitoring (Monitor the Monitors)

### Problem
The entire alerting pipeline can fail silently. If `smtp-relay` goes down, email alerts stop. If the monitoring cron jobs crash, nothing checks anything. The MediaJ incident proved that silent failures compound.

### Requirements

**Cross-channel heartbeat**:
- Every 24 hours, send a "still alive" message via EACH notification channel
- If you don't receive the daily heartbeat on any channel, that channel is broken
- Implementation: `lafayette-heartbeat` cron job that sends via email AND ntfy
- If email send fails → alert via ntfy that email is broken
- If ntfy send fails → alert via email that ntfy is broken

**Monitor process health**:
- Verify all monitoring cron jobs actually ran (check their timestamp files)
- Alert if any monitor hasn't run in 2x its expected interval

**Watchdog timer**:
- External service (e.g., healthchecks.io, uptimerobot, or a simple ping from another machine) that expects a regular ping
- If the server stops pinging entirely (total crash, network failure), the external service alerts

### Implementation notes
- `lafayette-heartbeat`: simple script, sends test via all channels daily
- Healthchecks.io free tier: up to 20 checks, simple curl ping, alerts on missed pings
- This is the "who watches the watchmen" layer — keep it dead simple

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Monitoring Checks                     │
│                                                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐  │
│  │  Drive    │ │ Service  │ │  Backup  │ │   Media   │  │
│  │  Health   │ │  Health  │ │ Freshness│ │  Changes  │  │
│  │ (smartd,  │ │ (docker, │ │ (snap,   │ │ (catalog  │  │
│  │  mergerfs,│ │  systemd)│ │  restic, │ │  diffing) │  │
│  │  fscheck) │ │          │ │  pg_dump)│ │           │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └─────┬─────┘  │
│       │            │            │              │         │
│       └────────────┴─────┬──────┴──────────────┘         │
│                          │                               │
│                 ┌────────▼────────┐                      │
│                 │ lafayette-notify │                      │
│                 │ (routing, dedup, │                      │
│                 │  severity)       │                      │
│                 └──┬─────┬─────┬──┘                      │
│                    │     │     │                          │
│              ┌─────▼┐ ┌─▼───┐ ├──▼──┐                    │
│              │Email │ │ntfy │ │ SMS │                    │
│              │(smtp)│ │(push│ │(crit │                    │
│              │      │ │ app)│ │only) │                    │
│              └──────┘ └─────┘ └─────┘                    │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Meta-Monitoring                      │   │
│  │  - Daily heartbeat via ALL channels               │   │
│  │  - External watchdog (healthchecks.io)            │   │
│  │  - Monitor-freshness checks                       │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Phases

### Phase 0: Immediate fixes (see mediaj-p0-immediate-fixes.md)
Already defined. Fix the snapraid scripts, add timeouts, basic health checks. Bash scripts, direct sendmail calls. Gets us from "completely unmonitored" to "basic monitoring" this week.

### Phase 1: Notification foundation
- Deploy ntfy (self-hosted or SaaS)
- Build `lafayette-notify` CLI
- Migrate P0 scripts from raw sendmail to `lafayette-notify`
- Set up daily heartbeat
- Set up external watchdog (healthchecks.io)
- **Deliverable**: Two independent notification channels, self-monitoring

### Phase 2: Comprehensive monitoring
- Service health monitoring (Docker + systemd)
- Backup freshness monitoring
- Fill backup gaps (PostgreSQL, appdata)
- Update/replace `server-config` disaster recovery
- Clean up legacy failed systemd units
- Fix ofelia and authentik-worker
- **Deliverable**: All services and backups monitored with alerts

### Phase 3: Media intelligence
- Design and build media change detection (P2 PRD)
- Integration with radarr/sonarr APIs
- AI-assisted change classification
- **Deliverable**: Unexpected media changes detected and reported

### Phase 4: Hardening
- Root drive disaster recovery documentation and testing
- Periodic backup restore testing
- Runbook for common failure scenarios
- Drive lifecycle tracking (age, hours, warranty)
- **Deliverable**: Confidence that any single failure is recoverable

---

## P2 PRDs Needed

| PRD | Component | Description |
|-----|-----------|-------------|
| P2-A | `lafayette-notify` | Multi-channel notification library/CLI with routing, dedup, severity, and self-monitoring |
| P2-B | `lafayette-media-monitor` | Media catalog and change detection with AI-assisted classification |
| P2-C | `lafayette-backup-monitor` | Backup freshness and integrity monitoring across all backup systems |
| P2-D | `lafayette-service-monitor` | Docker and systemd service health monitoring |
| P2-E | Root drive disaster recovery plan | Document + scripts for rebuilding the server from scratch |

---

## Principles

1. **Silent failure is the worst failure.** Every component must either work or scream.
2. **Two channels minimum.** No notification path should be a single point of failure.
3. **Simple beats clever.** Bash scripts in cron are more reliable than a complex monitoring daemon that can crash.
4. **Alert fatigue is real.** Only alert when human action is needed. Use daily digests for awareness.
5. **Test the backups.** A backup that has never been restored is a hypothesis, not a backup.
6. **Document the recovery.** When a drive fails at 2am, you shouldn't need to figure out the procedure.
7. **Drives die. Plan for it.** With 11+ spinning drives at 5-6 years old, a drive failure every 1-2 years is expected. Make it routine, not an emergency.

---

## Current Infrastructure Issues Found During Investigation

These should be addressed during Phase 2 regardless of the monitoring system:

| Issue | Severity | Notes |
|-------|----------|-------|
| MediaC (sdb): 6 pending sectors | WARNING | Early-stage failure, monitor closely |
| ofelia: crash-looping | LOW | Misconfigured, "empty scheduler" |
| authentik-worker: unhealthy 25+ days | MEDIUM | Stale heartbeat, may affect auth flows |
| PostgreSQL: collation version mismatch | LOW | Warning on queries, needs `REFRESH COLLATION VERSION` |
| PostgreSQL: no backup (pg_dump) | CRITICAL | authentik + nextcloud data at risk |
| 5 legacy systemd units failed | LOW | Clean up: certbot, courier-imap, nginx, vncserver, mount-all |
| `server-config`: 8 months stale | MEDIUM | Disaster recovery plan is outdated |
| No hot spare drive after recovery | MEDIUM | Next failure has no quick replacement |
| `/usr/bin/mail` broken | LOW | `sendmail` works, but `mail` command fails |
| Root crontab `MAILTO=""` at top | MEDIUM | First MAILTO wins — may suppress all cron error mail |
