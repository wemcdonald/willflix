# MediaJ Drive Failure — Post-Mortem Log

**Date**: 2026-03-03
**Drive**: WDC WD120EMAZ-11BLFA0, 12TB, Serial: 8CGR2NSE, Label: MediaJ
**Power-On Hours at Failure**: 53,132 (~6 years)

## Problems Identified

### P1: SnapRAID daily cron hung for 2.5 months with no alerting
- `check_for_deletes` runs `snapraid diff` before sync
- `snapraid diff` hung trying to read failing drive (since Dec 19, 2025)
- This silently blocked ALL syncs — last successful sync was May 1, 2025
- No monitoring/alerting detected the stuck process or stale sync
- **Impact**: ~10 months of new media has zero parity protection

### P2: Drive developed bad sectors over weeks with no proactive detection
- First kernel `critical medium error` on sdh: Feb 9, 2026
- 814+ kernel warnings, 488 ATA errors, 10+ distinct bad sector regions
- SMART: 896 current pending sectors, 480 offline uncorrectable
- No SMART monitoring/alerting (smartd or similar) caught the degradation
- Drive SMART self-test still reports "PASSED" despite obvious failure

### P3: ext4 remounted read-only but mergerfs kept serving the dead mount
- Feb 27: ext4 detected aborted journal, remounted sdh1 read-only
- mergerfs continued including `/Volumes/MediaJ` in the pool
- Files on MediaJ silently disappeared from the merged `/Volumes/Media` view
- No alerting on filesystem remount-ro events

### P4: Device node shifted (sdh → sdu) creating a zombie mount
- Original mount was `/dev/sdh1` on `/Volumes/MediaJ`
- Drive re-enumerated as `/dev/sdu` at some point (possibly after bus reset)
- Stale mount still shows `sdh1` but the device no longer exists
- fstab uses LABEL= which is correct, but the already-mounted zombie persists

### P5: No health checks on the mergerfs pool
- No periodic validation that all member drives are readable
- Radarr/sonarr/plex had no way to detect or report missing media
- Users discovered the problem before any automated system did

### P6: check_for_deletes script design flaw
- `check_for_deletes` runs `snapraid diff` and exits non-zero if any non-ignored deletes are found
- But `snapraid diff` hangs when a drive has I/O errors — it never exits at all
- The script was meant as a safety check but became the single point of failure
- It blocked syncs for 2.5 months while the drive degraded further

### P7: snapraid cron script has no timeout or staleness detection
- `check_for_deletes` + `snapraid_daily` can hang indefinitely
- No wrapper timeout (e.g., `timeout` command)
- No external check for "has snapraid synced recently?"
- The `cronic` wrapper suppresses output unless exit code is non-zero — but a hung process never exits

### P8: MediaC (sdb) also showing early failure — discovered during investigation
- 6 current pending sectors, 6 offline uncorrectable
- smartd IS detecting and alerting on this (emails sent today)
- Second drive in early-stage failure while first is being recovered
- No proactive replacement process for drives showing early warning signs

### P9: smartd lost track of MediaJ after device node shift
- smartd uses `DEVICESCAN -d removable` which scans at startup
- When sdh re-enumerated as sdu, smartd likely lost the drive
- smartd IS capable of detecting bad sectors (proves it with sdb alerts today)
- Using stable paths (/dev/disk/by-id/) would prevent this

### P10: sendmail-system was silently failing ALL email delivery
- `sendmail-system` used netcat to blast entire SMTP conversation at once
- Postfix rejected every message: "improper command pipelining after CONNECT"
- The script logged "Successfully sent" based on netcat's TCP connection, not SMTP response
- **ALL email alerts were silently dropped** — smartd SMART alerts, cron errors, everything
- This means the smartd alerts about MediaC (sdb) that appeared in the mail log were never delivered
- Fixed 2026-03-04: replaced netcat with curl for proper SMTP protocol handling

### P10b: `/usr/bin/mail` command is also broken
- `mail` command fails entirely (separate from sendmail-system issue)
- Any scripts using `mail` directly would fail to alert

### P11: PostgreSQL has no backup at all
- authentik, nextcloud, healthdata databases have zero backup
- No pg_dump script exists anywhere on the system
- If the postgres container's volume is lost, all auth config and nextcloud data is gone

### P12: Multiple Docker services failing silently
- `ofelia`: crash-looping with "unable to start a empty scheduler" — nobody noticed
- `authentik-worker`: unhealthy for 25+ days (stale heartbeat) — nobody noticed
- No monitoring of Docker container health status

### P13: Root crontab MAILTO suppression
- Root crontab has `MAILTO=""` as the FIRST line, before `MAILTO=will`
- First `MAILTO` wins in cron — this may suppress all cron error output
- Even if cron jobs fail, error mail may never be sent

### P14: server-config disaster recovery is 8 months stale
- `/home/will/server-config/` last modified Jul 2025
- This is the documented recovery plan for rebuilding the server
- Restic backs it up daily but the content itself is outdated
- Many changes since then (new services, config changes) not captured

### P15: Single notification channel (email only)
- All alerting goes through one path: sendmail → smtp-relay → Gmail
- If any link in that chain breaks (or Gmail filters it), alerts are lost
- No push notifications, no SMS, no fallback channel
- smartd DID send emails about MediaC today — unclear if they were actually seen

### P16: No spare drive rotation plan
- MediaSpare existed and was labeled with a note: "this_should_be_parity2_when_new_drive_needed"
- But no documented procedure for when/how to use it in a failure scenario
- No replacement spare was planned for after MediaSpare gets consumed
- After this recovery, the array will have zero spare drives until a new one is acquired

### P17: snapraid sync gap grew to 10 months unnoticed
- Last successful sync: May 1, 2025
- `check_for_deletes` began blocking syncs Dec 19, 2025 (7 months of syncs already missed before that)
- Drive errors began Feb 9, 2026
- Gap discovered Mar 3, 2026
- All media added in that 10-month window has no parity protection

**Root cause of May→Dec gap (E3 investigation, 2026-03-04):**
- `/snapraid/snapraid.content.tmp` exists, dated Apr 26, only 1.9GB of expected 5.8GB — interrupted write
- The Apr 26 sync was interrupted mid-content-file-write (power event? OOM kill? unknown)
- May 1 sync ran and wrote to the 5 drive-based content files successfully (all show May 1 date, 5.99GB)
- But `/snapraid/snapraid.content` was never updated past Apr 26 — likely the stale .tmp caused issues
- After May 1, every subsequent `snapraid diff` (called by `check_for_deletes`) printed WARNING about mismatched content files
- These WARNINGs went to stderr, which cronic treats as "error output"
- cronic outputs error reports to stdout, which cron pipes to `sendmail`
- BUT `MAILTO=""` was the first line in root crontab — suppressing ALL cron output
- **Result**: cronic detected failures every single night for 7 months, tried to report them, and every report was silently discarded by cron's empty MAILTO
- The Dec 19 hang was a separate failure (I/O errors caused `snapraid diff` to hang instead of just warn)

**Contributing factors**:
1. Interrupted sync left stale .tmp file (original cause)
2. Mismatched content files caused warnings on every subsequent run
3. cronic correctly detected the errors but output went to MAILTO=""
4. `MAILTO=""` as first line in crontab suppressed all error reporting
5. No independent staleness monitoring existed to catch the gap
