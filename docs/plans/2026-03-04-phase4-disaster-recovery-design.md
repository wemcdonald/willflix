# Phase 4: Disaster Recovery — Design

**Date**: 2026-03-04
**Status**: Complete
**PRD**: `docs/lafayette-health-monitoring-prd.md`, Phase 4 (hardening subset)
**Depends on**: Repo consolidation (complete), Phase 2b (complete)

---

## Goals

Enable full server rebuild from a fresh Ubuntu 22.04 install using only the git repo, a git-crypt key, and an SSH key. Guided automation — not fully hands-off, but no 50-command manual process either.

**Deliverables:**
- `bin/rebuild-lafayette` — guided rebuild script with staged confirmation
- `docs/disaster-recovery.md` — runbook documenting what the script does and edge cases
- Offsite key backup — git-crypt key + SSH key in LastPass

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Script style | Guided (pause between stages) | Rebuild is rare; you want to see what's happening. Full auto risks opaque failures. |
| Format | Single bash script with stages | Simple, portable, no dependencies beyond base Ubuntu. |
| Key backup | LastPass secure notes | Already used for everything else. |
| Scope | Root SSD failure only | Data drive failures covered by existing mediaj docs + snapraid. |
| Restore testing | Deferred | The rebuild script itself is the test. Automated restore verification is a future phase. |
| Drive lifecycle | Deferred | Separate concern from disaster recovery. |

---

## Rebuild Script Stages

| Stage | What it does | Human input |
|-------|-------------|-------------|
| 1. Prerequisites | Checks Ubuntu version, internet, sudo access | None |
| 2. Packages | Installs Docker, git-crypt, smartmontools, mergerfs, snapraid, etc. | Confirm |
| 3. Clone repo | Clones `/willflix` from GitHub | Needs SSH key or HTTPS token |
| 4. Unlock secrets | `git-crypt unlock <keyfile>` | Needs key file (from LastPass) |
| 5. Mount drives | Copies fstab entries (LABEL= mounts), creates mount points, mounts drives, sets up mergerfs pool | Confirm — shows expected vs present labels, warns on missing |
| 6. System configs | Installs smartd.conf, snapraid.conf, root crontab, systemd units, sendmail wrapper | Confirm |
| 7. Docker services | `docker compose -p config up -d` | Confirm |
| 8. Restore postgres | Loads latest pg_dump files from /Volumes/Bonus1/postgres-backup/ | Confirm — shows which dumps will be loaded |
| 9. Verify | Checks: services running, drives mounted, mergerfs healthy, backups exist, alerting works | None (report only) |

### Stage details

**Stage 5 (Mount drives):**
- Uses `LABEL=` mounts from tracked `etc/fstab` — device paths don't matter
- Shows which labels are expected vs. which are detected on the system
- Warns about missing drives (expected during drive-failure rebuilds)
- Creates mount points under `/Volumes/`
- Mounts member drives first, then mergerfs pool last
- Does NOT touch partitioning or formatting — drives must already have filesystems

**Stage 8 (Restore postgres):**
- Default path: load dumps from `/Volumes/Bonus1/postgres-backup/` (latest dated files)
- Fallback: if Bonus1 unavailable, prompt to restore dumps from restic first
- Loads globals first (`globals-*.sql.gz`), then per-database dumps
- Waits for postgres container to be healthy before loading

---

## Runbook (docs/disaster-recovery.md)

Documents:
- Prerequisites (what you need before starting)
- What each rebuild stage does and why
- How to skip a stage (e.g., `--skip-mounts` or just answer 'n' at the prompt)
- How to do a partial rebuild (just Docker, just postgres, just crontab)
- Where all critical files live and what they do
- How to retrieve keys from LastPass
- "Break glass" manual instructions if the script doesn't work
- How to verify the rebuild succeeded

---

## Offsite Key Backup

**Before running the rebuild script, you need:**
1. Git-crypt symmetric key (base64-encoded secure note in LastPass)
2. SSH private key for GitHub (secure note in LastPass)
3. Network access to GitHub and the internet

**Setup (one-time):**
- Export git-crypt key: `git-crypt export-key /tmp/key && base64 /tmp/key`
- Store the base64 output as a LastPass secure note titled "lafayette git-crypt key"
- Verify SSH key is in LastPass (or add it)
- Delete `/tmp/key`

**To use during rebuild:**
- Copy base64 from LastPass, decode: `echo '<base64>' | base64 -d > /tmp/git-crypt-key`
- Pass to script or run `git-crypt unlock /tmp/git-crypt-key`

---

## What this does NOT cover

- **Ubuntu installation**: Manual — boot USB, install, create `will` user
- **Data drive recovery**: Covered by `docs/mediaj-recovery-plan.md` and snapraid
- **Recreating appdata from scratch**: `restic restore` from `/Volumes/Bonus1/lafayette`
- **Automated restore testing**: Future phase
- **Drive lifecycle tracking**: Future phase (separate concern)

---

## File Changes

**New:**
- `bin/rebuild-lafayette`
- `docs/disaster-recovery.md`

**Modified:**
- None (script reads existing repo files, doesn't change them)
