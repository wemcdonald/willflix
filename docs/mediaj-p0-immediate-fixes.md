# MediaJ Drive Failure — Post-Mortem & Prevention Plan

**Date**: 2026-03-03
**Incident**: MediaJ (WDC WD120EMAZ, 12TB, 53K hours) developed bad sectors, causing silent data unavailability in mergerfs pool and blocking snapraid syncs for 10 months.

---

## What Happened

| Date | Event |
|------|-------|
| **May 1, 2025** | Last successful snapraid sync |
| **May 2025 – Dec 2025** | 7-month sync gap — cause unknown, needs investigation |
| **Dec 19, 2025** | `check_for_deletes` → `snapraid diff` hangs on I/O errors. Blocks all future syncs. |
| **Feb 9, 2026** | First kernel `critical medium error` on sdh (MediaJ) |
| **Feb 9 – Feb 27** | 814+ kernel warnings, 488 ATA errors, 10+ bad sector regions |
| **Feb 27** | ext4 detects aborted journal, remounts MediaJ read-only. Files silently vanish from mergerfs. |
| **~Feb 27** | Device re-enumerates from sdh → sdu. Zombie mount remains. |
| **Mar 3** | User reports missing media. Diagnosis and recovery begins. |

**Impact**: ~292 movies, ~246 TV shows (6849 episodes), audiobooks, ebooks temporarily unavailable. 10 months of new media (~20 movies, ~1146 TV episodes, 488 audiobooks, 3174 ebooks) has no parity protection.

---

## Problems Identified

### 1. SnapRAID sync gap: 10 months unprotected

The last sync was May 1, 2025. Everything added since then has zero parity. Two separate causes:

- **May → Dec 2025 (7 months)**: Unknown cause. Needs investigation. The cron job ran but something silently prevented syncs from completing.
- **Dec 2025 → Mar 2026 (2.5 months)**: `check_for_deletes` ran `snapraid diff` which hung on I/O errors from the failing drive. The hung process held the lock, blocking all future syncs.

### 2. No staleness alerting on snapraid

Nobody noticed syncs weren't happening for 10 months. The `cronic` wrapper only reports errors on non-zero exit — a hung process never exits, so nothing was reported.

### 3. Drive failure with no proactive warning

The drive accumulated 896 pending sectors and 480 offline uncorrectable sectors. smartd was running and could detect this (it's currently alerting on MediaC/sdb), but the device node shift (sdh → sdu) likely caused smartd to lose track of MediaJ.

### 4. Silent data unavailability in mergerfs

When ext4 remounted read-only, mergerfs kept the mount point in the pool but couldn't read files. From the user's perspective, content simply vanished with no error message, notification, or degraded-state indicator.

### 5. Broken `mail` command (partially)

The `/usr/bin/mail` command fails, but `/usr/sbin/sendmail` (wired to `sendmail-system`) works. smartd uses the sendmail pipeline and delivers successfully. However, any scripts using `mail` directly would silently fail to alert.

### 6. `check_for_deletes` design flaw

The script was a safety net to prevent syncing after accidental mass deletes. But `snapraid diff` hangs on I/O errors instead of erroring out, turning the safety net into a single point of failure that blocked all syncs.

### 7. Second drive (MediaC/sdb) showing early failure signs

Discovered during investigation: sdb has 6 pending sectors and 6 offline uncorrectable. This is early-stage failure on another drive.

---

## Prevention Plan

### A. SnapRAID Reliability (addresses #1, #2, #6)

**A1. Add timeout to snapraid cron scripts**

Wrap all snapraid operations with `timeout` to prevent indefinite hangs:

```bash
#!/bin/bash
# snapraid_daily - with timeout and error handling
TIMEOUT=14400  # 4 hours max
LOGFILE="/var/log/snapraid-daily.log"

echo "$(date): Starting snapraid daily" >> "$LOGFILE"

# check_for_deletes with timeout
if ! timeout "$TIMEOUT" /home/will/bin/cron/check_for_deletes 2>> "$LOGFILE"; then
    echo "$(date): check_for_deletes failed or timed out" >> "$LOGFILE"
    echo "snapraid check_for_deletes failed or timed out on $(hostname)" | \
        /usr/sbin/sendmail wemcdonald@gmail.com
    exit 1
fi

# sync with timeout
if ! timeout "$TIMEOUT" /usr/local/bin/snapraid --force-zero sync 2>> "$LOGFILE"; then
    echo "$(date): snapraid sync failed or timed out" >> "$LOGFILE"
    echo "snapraid sync failed or timed out on $(hostname)" | \
        /usr/sbin/sendmail wemcdonald@gmail.com
    exit 1
fi

echo "$(date): snapraid daily completed successfully" >> "$LOGFILE"
```

**A2. Add staleness check (independent of the sync cron)**

A separate cron job that checks when the last sync happened and alerts if it's stale:

```bash
#!/bin/bash
# check_snapraid_freshness - run daily via separate cron entry
MAX_AGE_DAYS=3
CONTENT_FILE="/Volumes/MediaB/snapraid.content"

if [ ! -f "$CONTENT_FILE" ]; then
    echo "snapraid content file missing!" | /usr/sbin/sendmail wemcdonald@gmail.com
    exit 1
fi

FILE_AGE_DAYS=$(( ($(date +%s) - $(stat -c %Y "$CONTENT_FILE")) / 86400 ))

if [ "$FILE_AGE_DAYS" -gt "$MAX_AGE_DAYS" ]; then
    cat << EOF | /usr/sbin/sendmail -t
To: wemcdonald@gmail.com
Subject: WARNING: snapraid sync is $FILE_AGE_DAYS days stale on $(hostname)
From: root@willflix.org

The snapraid content file hasn't been updated in $FILE_AGE_DAYS days.
Last modified: $(stat -c %y "$CONTENT_FILE")
Threshold: $MAX_AGE_DAYS days

Check if snapraid cron is running:
  ps aux | grep snapraid

Check the log:
  tail -50 /var/log/snapraid-daily.log
EOF
fi
```

Add to root crontab:
```
30 8 * * * /home/will/bin/cron/check_snapraid_freshness
```

**A3. Rewrite `check_for_deletes` with timeout and I/O error handling**

The current Ruby script hangs when `snapraid diff` encounters I/O errors. Add a timeout and handle the case where diff fails:

```bash
#!/bin/bash
# check_for_deletes - with timeout
TIMEOUT=3600  # 1 hour max for diff

DIFF_OUTPUT=$(timeout "$TIMEOUT" snapraid diff 2>&1)
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 124 ]; then
    echo "snapraid diff timed out after ${TIMEOUT}s — possible drive I/O issue" >&2
    exit 1
fi

if [ "$EXIT_CODE" -ne 0 ]; then
    echo "snapraid diff failed with exit code $EXIT_CODE" >&2
    echo "$DIFF_OUTPUT" >&2
    exit 1
fi

# Check for unexpected deletes (original logic)
DELETED=$(echo "$DIFF_OUTPUT" | grep "^removed " | grep -v -E "^(Backups|Plex)" | wc -l)
if [ "$DELETED" -gt 0 ]; then
    echo "$DELETED unexpected deletes found:" >&2
    echo "$DIFF_OUTPUT" | grep "^removed " | grep -v -E "^(Backups|Plex)" >&2
    exit 1
fi
```

### B. Drive Health Monitoring (addresses #3, #7)

**B1. Fix smartd configuration for reliable detection**

The current `DEVICESCAN -d removable` config can lose drives after device node changes. Pin specific drives by serial or WWN:

```
# /etc/smartd.conf - explicit drive monitoring
# Use by-id paths which are stable across device re-enumeration
/dev/disk/by-id/wwn-* -a -o on -S on -n standby,q -s (S/../.././02|L/../../6/03) -W 4,45,55 -m root -M exec /usr/share/smartmontools/smartd-runner
```

Or at minimum, remove `-d removable` and add `-W` for temperature tracking and `-s` for scheduled self-tests.

**B2. Proactive SMART attribute alerting**

smartd already detects pending sectors (it's alerting on MediaC right now). Verify you're receiving those emails in Gmail. If the alerts are landing in spam, add a filter.

**B3. Address MediaC (sdb) now**

sdb has 6 pending + 6 uncorrectable sectors. This is early-stage failure. Plan to replace this drive before it reaches the state MediaJ did:
- Monitor closely (smartd is already tracking it)
- Run `smartctl -t long /dev/sdb` to get a full surface scan
- If sector count grows, replace proactively

### C. MergerFS Health Monitoring (addresses #4)

**C1. Periodic mergerfs pool health check**

A script that verifies all expected member drives are mounted and readable:

```bash
#!/bin/bash
# check_mergerfs_health - run every 15 minutes via cron
EXPECTED_DRIVES="MediaA MediaB MediaC MediaD MediaE MediaF MediaG MediaH MediaI MediaJ MediaK"
ERRORS=""

for drive in $EXPECTED_DRIVES; do
    MOUNT="/Volumes/$drive"

    # Check if mounted
    if ! mountpoint -q "$MOUNT" 2>/dev/null; then
        ERRORS="${ERRORS}$drive: NOT MOUNTED\n"
        continue
    fi

    # Check if readable
    if ! ls "$MOUNT" >/dev/null 2>&1; then
        ERRORS="${ERRORS}$drive: MOUNTED BUT UNREADABLE (I/O error)\n"
        continue
    fi

    # Check if read-only (remounted due to errors)
    if grep -q "$MOUNT.*\bro\b" /proc/mounts 2>/dev/null; then
        ERRORS="${ERRORS}$drive: REMOUNTED READ-ONLY\n"
        continue
    fi
done

if [ -n "$ERRORS" ]; then
    cat << EOF | /usr/sbin/sendmail -t
To: wemcdonald@gmail.com
Subject: ALERT: mergerfs pool degraded on $(hostname)
From: root@willflix.org

One or more drives in the mergerfs pool have problems:

$(echo -e "$ERRORS")

Immediate action required. Check drive health:
  sudo smartctl -a /dev/sdX
  dmesg | grep -i error | tail -20
EOF
fi
```

Add to root crontab:
```
*/15 * * * * /home/will/bin/cron/check_mergerfs_health
```

### D. Mail Reliability (addresses #5)

**D1. Fix the `mail` command**

`/usr/bin/mail` doesn't work but `/usr/sbin/sendmail` does. Either:
- Configure `mail` to use the sendmail-system pipeline, or
- Replace all scripts that use `mail` with direct `sendmail` calls

**D2. Add a weekly mail delivery test**

Uncomment and update the test line in the crontab:
```
0 10 * * 1 echo "Weekly mail test from $(hostname) at $(date)" | /usr/sbin/sendmail -t <<< "To: wemcdonald@gmail.com
Subject: Weekly $(hostname) health check - mail delivery OK
From: root@willflix.org

Mail delivery is working."
```

### E. Operational Procedures (addresses remaining gaps)

**E1. Document the drive replacement procedure**

Create `/docker/docs/drive-replacement.md` with step-by-step instructions covering:
- How to identify a failing drive
- How to use the spare drive
- How to relabel and reintegrate into mergerfs + snapraid
- How to verify recovery

**E2. Maintain a hot spare**

After MediaSpare is consumed for this recovery, acquire a replacement spare. A 12-14TB drive on the shelf means recovery can start immediately instead of waiting for shipping.

**E3. Investigate the May–Dec 2025 sync gap**

The `check_for_deletes` hang explains Dec 2025 onward, but syncs weren't happening for 7 months before that. Check:
- Were there earlier hung processes that were manually killed?
- Was the cron job disabled/modified during that period?
- Check `/var/log/syslog*` or `journalctl` archives for cron entries from that period

---

## Implementation Priority

| Priority | Item | Effort | Prevents |
|----------|------|--------|----------|
| ~~**NOW**~~ | ~~B3: Address MediaC pending sectors~~ | ~~Low~~ | DONE: SMART long test running |
| ~~**This week**~~ | ~~A1: Add timeout to snapraid scripts~~ | ~~Low~~ | DONE: snapraid_daily rewritten |
| ~~**This week**~~ | ~~A2: Staleness check cron~~ | ~~Low~~ | DONE: check_snapraid_freshness installed |
| ~~**This week**~~ | ~~C1: MergerFS health check~~ | ~~Low~~ | DONE: check_mergerfs_health every 15m |
| ~~**This week**~~ | ~~D1: Fix mail delivery~~ | ~~Low~~ | DONE: sendmail-system rewritten (netcat→curl) |
| ~~**This week**~~ | ~~A3: Rewrite check_for_deletes~~ | ~~Low~~ | DONE: bash with timeout, replaces Ruby |
| ~~**Soon**~~ | ~~B1: Pin smartd by drive ID~~ | ~~Medium~~ | DONE: 18 drives pinned by ata-ID, smartd restarted |
| ~~**Soon**~~ | ~~E3: Investigate May–Dec gap~~ | ~~Medium~~ | DONE: interrupted sync → stale .tmp → cronic errors → MAILTO="" suppression. Fixed .tmp and content file. |
| **When budget allows** | E2: Buy replacement spare | $ | No spare for next failure |
| **When convenient** | E1: Document procedures | Medium | Panic during next incident |
| **When convenient** | D2: Weekly mail test | Low | Unnoticed mail breakage |

---

## Key Takeaway

The drive failure itself was survivable — triple parity meant the data was recoverable. What made this incident painful was the **cascade of silent failures**: syncs stopped for 10 months with no alert, the drive degraded for weeks with no warning, and files vanished from mergerfs with no notification. Every one of those failures had a simple, low-effort monitoring solution that wasn't in place. The prevention plan above adds those monitors so that the next drive failure (inevitable with 11+ spinning drives) is detected in hours, not months.
