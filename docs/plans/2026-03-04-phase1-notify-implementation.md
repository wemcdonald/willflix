# Phase 1: Notification Foundation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a multi-channel notification system (email + Pushover) with dedup, severity routing, heartbeat monitoring, and migrate all P0 scripts to use it.

**Architecture:** Two bash scripts — `willflix-notify` (routing/dedup) calls `willflix-notify-send` (delivery). A third script `willflix-heartbeat` does weekly channel testing and daily monitor-freshness checks. All scripts live in `bin/` or `bin/cron/`, config in `~/.config/willflix-notify/config`.

**Tech Stack:** Bash, curl (Pushover API), sendmail (email), syslog (logging), cron

**Design doc:** `docs/plans/2026-03-04-phase1-notify-design.md`

---

### Task 1: Example config file

**Files:**
- Create: `etc/willflix-notify.config.example`

**Step 1: Create the example config**

```bash
# willflix-notify configuration
# Copy to ~/.config/willflix-notify/config and fill in values.

# Pushover credentials — get these from https://pushover.net
# Create an application at https://pushover.net/apps/build
PUSHOVER_APP_TOKEN=""
PUSHOVER_USER_KEY=""

# Email recipient for alerts
NOTIFY_EMAIL="wemcdonald@gmail.com"

# Dedup: suppress repeat alerts with the same --key for this many seconds
DEDUP_DIR="/var/tmp/willflix-notify"
DEDUP_WINDOW=21600  # 6 hours

# UptimeRobot heartbeat URL (get from UptimeRobot dashboard)
UPTIMEROBOT_HEARTBEAT_URL=""

# Monitor freshness — monitoring scripts touch files here on success
MONITOR_FRESHNESS_DIR="/var/tmp/willflix-monitors"
```

**Step 2: Commit**

```bash
git add etc/willflix-notify.config.example
git commit -m "Add willflix-notify example config"
```

---

### Task 2: willflix-notify-send (channel delivery)

**Files:**
- Create: `bin/willflix-notify-send`

This is the low-level delivery script. It knows how to send via each channel. It does NOT know about severity routing or dedup — that's `willflix-notify`'s job.

**Step 1: Write willflix-notify-send**

```bash
#!/bin/bash
# willflix-notify-send — deliver a notification via a specific channel.
# Internal script called by willflix-notify. Not intended for direct use.
#
# Usage:
#   willflix-notify-send --channel email --subject "..." [--body "..."]
#   willflix-notify-send --channel pushover --subject "..." [--body "..."] [--priority 0]

set -euo pipefail

CHANNEL=""
SUBJECT=""
BODY=""
PRIORITY=0

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --channel)  CHANNEL="$2";  shift 2 ;;
        --subject)  SUBJECT="$2";  shift 2 ;;
        --body)     BODY="$2";     shift 2 ;;
        --priority) PRIORITY="$2"; shift 2 ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$CHANNEL" || -z "$SUBJECT" ]]; then
    echo "Usage: willflix-notify-send --channel <email|pushover> --subject <text> [--body <text>] [--priority <n>]" >&2
    exit 1
fi

# Load config
CONFIG_FILE="${HOME}/.config/willflix-notify/config"
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Config not found: $CONFIG_FILE" >&2
    exit 1
fi
# shellcheck source=/dev/null
source "$CONFIG_FILE"

send_email() {
    local to="${NOTIFY_EMAIL:?NOTIFY_EMAIL not set in config}"
    cat << EOF | /usr/sbin/sendmail -t
To: ${to}
Subject: ${SUBJECT}
From: root@willflix.org

${BODY}
EOF
}

send_pushover() {
    local token="${PUSHOVER_APP_TOKEN:?PUSHOVER_APP_TOKEN not set in config}"
    local user="${PUSHOVER_USER_KEY:?PUSHOVER_USER_KEY not set in config}"

    local -a curl_args=(
        -s -o /dev/null -w "%{http_code}"
        --form-string "token=${token}"
        --form-string "user=${user}"
        --form-string "title=${SUBJECT}"
        --form-string "message=${BODY:-$SUBJECT}"
        --form-string "priority=${PRIORITY}"
    )

    # Emergency priority (2) requires retry and expire params
    if [[ "$PRIORITY" == "2" ]]; then
        curl_args+=(--form-string "retry=300" --form-string "expire=3600")
    fi

    local http_code
    http_code=$(curl "${curl_args[@]}" https://api.pushover.net/1/messages.json)

    if [[ "$http_code" != "200" ]]; then
        echo "Pushover API returned HTTP $http_code" >&2
        return 1
    fi
}

case "$CHANNEL" in
    email)    send_email    ;;
    pushover) send_pushover ;;
    *)
        echo "Unknown channel: $CHANNEL" >&2
        exit 1
        ;;
esac
```

**Step 2: Make executable and commit**

```bash
chmod +x bin/willflix-notify-send
git add bin/willflix-notify-send
git commit -m "Add willflix-notify-send channel delivery script"
```

**Step 3: Test email delivery manually**

Requires config file to exist with NOTIFY_EMAIL set.

```bash
mkdir -p ~/.config/willflix-notify
cp etc/willflix-notify.config.example ~/.config/willflix-notify/config
# Edit config: set NOTIFY_EMAIL=wemcdonald@gmail.com (already default)
```

```bash
bin/willflix-notify-send --channel email --subject "Test from willflix-notify-send" --body "If you see this, email delivery works."
```

Verify: `docker logs smtp-relay --tail 5` should show `status=sent`.

**Step 4: Test Pushover delivery manually**

Requires Pushover app token and user key in config.

```bash
# Edit ~/.config/willflix-notify/config — fill in PUSHOVER_APP_TOKEN and PUSHOVER_USER_KEY
bin/willflix-notify-send --channel pushover --subject "Test from willflix-notify-send" --body "If you see this, Pushover delivery works."
```

Verify: push notification appears on iPhone.

**Step 5: Test Pushover emergency priority**

```bash
bin/willflix-notify-send --channel pushover --subject "Emergency test" --body "This should repeat until acknowledged." --priority 2
```

Verify: push notification appears, repeats every 5 minutes until acknowledged in app.

---

### Task 3: willflix-notify (routing and dedup)

**Files:**
- Create: `bin/willflix-notify`

**Step 1: Write willflix-notify**

```bash
#!/bin/bash
# willflix-notify — multi-channel notification with severity routing and dedup.
#
# Usage:
#   willflix-notify --severity CRITICAL --key "mergerfs-degraded" \
#     --subject "MergerFS pool degraded" --body "Details..."
#
#   echo "body from stdin" | willflix-notify --severity WARNING \
#     --key "snapraid-stale" --subject "SnapRAID sync stale"
#
#   willflix-notify --test --subject "Test all channels"
#
# Severity routing:
#   INFO     → email only
#   WARNING  → email + pushover (normal)
#   CRITICAL → email + pushover (emergency, repeats until ack'd)
#   META     → cross-channel failover (if one fails, alert via other)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEND="${SCRIPT_DIR}/willflix-notify-send"

SEVERITY=""
KEY=""
SUBJECT=""
BODY=""
TEST_MODE=false

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --severity) SEVERITY="$2"; shift 2 ;;
        --key)      KEY="$2";      shift 2 ;;
        --subject)  SUBJECT="$2";  shift 2 ;;
        --body)     BODY="$2";     shift 2 ;;
        --test)     TEST_MODE=true; shift ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Read body from stdin if not provided and stdin is not a terminal
if [[ -z "$BODY" && ! -t 0 ]]; then
    BODY=$(cat)
fi

# Validate required args
if [[ -z "$SUBJECT" ]]; then
    echo "Usage: willflix-notify --severity <level> --key <dedup-key> --subject <text> [--body <text>]" >&2
    exit 1
fi

if [[ "$TEST_MODE" == "false" && ( -z "$SEVERITY" || -z "$KEY" ) ]]; then
    echo "--severity and --key are required (unless using --test)" >&2
    exit 1
fi

# Load config (for dedup settings)
CONFIG_FILE="${HOME}/.config/willflix-notify/config"
if [[ ! -f "$CONFIG_FILE" ]]; then
    # First-run: create config from example
    EXAMPLE="$(cd "$(dirname "$0")/../etc" && pwd)/willflix-notify.config.example"
    mkdir -p "$(dirname "$CONFIG_FILE")"
    if [[ -f "$EXAMPLE" ]]; then
        cp "$EXAMPLE" "$CONFIG_FILE"
        echo "Created config at $CONFIG_FILE — please fill in Pushover credentials and re-run." >&2
    else
        echo "No config found at $CONFIG_FILE and no example to copy." >&2
    fi
    exit 1
fi
# shellcheck source=/dev/null
source "$CONFIG_FILE"

DEDUP_DIR="${DEDUP_DIR:-/var/tmp/willflix-notify}"
DEDUP_WINDOW="${DEDUP_WINDOW:-21600}"

# --- Dedup check ---

is_deduped() {
    [[ "$TEST_MODE" == "true" ]] && return 1  # --test bypasses dedup

    local keyfile="${DEDUP_DIR}/${KEY}"
    if [[ -f "$keyfile" ]]; then
        local age=$(( $(date +%s) - $(stat -c %Y "$keyfile") ))
        if [[ "$age" -lt "$DEDUP_WINDOW" ]]; then
            return 0  # suppress
        fi
    fi
    return 1  # not deduped, send it
}

touch_dedup() {
    mkdir -p "$DEDUP_DIR"
    touch "${DEDUP_DIR}/${KEY}"
}

# --- Logging ---

log() {
    logger -t willflix-notify "$*"
}

# --- Send helpers ---

send_email() {
    if "$SEND" --channel email --subject "$SUBJECT" --body "$BODY"; then
        log "OK channel=email severity=$SEVERITY key=$KEY"
        return 0
    else
        log "FAIL channel=email severity=$SEVERITY key=$KEY"
        echo "willflix-notify: email send failed for key=$KEY" >&2
        return 1
    fi
}

send_pushover() {
    local priority="${1:-0}"
    if "$SEND" --channel pushover --subject "$SUBJECT" --body "$BODY" --priority "$priority"; then
        log "OK channel=pushover severity=$SEVERITY key=$KEY priority=$priority"
        return 0
    else
        log "FAIL channel=pushover severity=$SEVERITY key=$KEY priority=$priority"
        echo "willflix-notify: pushover send failed for key=$KEY" >&2
        return 1
    fi
}

# --- Routing ---

if is_deduped; then
    log "DEDUP severity=$SEVERITY key=$KEY (suppressed)"
    exit 0
fi

if [[ "$TEST_MODE" == "true" ]]; then
    echo "willflix-notify: test mode — sending via all channels"
    send_email || true
    send_pushover 0 || true
    exit 0
fi

case "$SEVERITY" in
    INFO)
        send_email || true
        ;;
    WARNING)
        send_email || true
        send_pushover 0 || true
        ;;
    CRITICAL)
        send_email || true
        send_pushover 2 || true
        ;;
    META)
        # Cross-channel failover
        email_ok=true
        pushover_ok=true
        send_email    || email_ok=false
        send_pushover 0 || pushover_ok=false

        if [[ "$email_ok" == "false" && "$pushover_ok" == "true" ]]; then
            "$SEND" --channel pushover --subject "META: Email alerting is broken on $(hostname)" \
                --body "willflix-notify failed to send email. Check smtp-relay container." --priority 0 || true
        fi
        if [[ "$pushover_ok" == "false" && "$email_ok" == "true" ]]; then
            "$SEND" --channel email --subject "META: Pushover alerting is broken on $(hostname)" \
                --body "willflix-notify failed to send via Pushover. Check API credentials and network." || true
        fi
        if [[ "$email_ok" == "false" && "$pushover_ok" == "false" ]]; then
            echo "$(date): BOTH channels failed for key=$KEY" >> /var/log/willflix-notify-failures.log
        fi
        ;;
    *)
        echo "Unknown severity: $SEVERITY (use INFO, WARNING, CRITICAL, META)" >&2
        exit 1
        ;;
esac

touch_dedup
```

**Step 2: Make executable and commit**

```bash
chmod +x bin/willflix-notify
git add bin/willflix-notify
git commit -m "Add willflix-notify routing and dedup script"
```

**Step 3: Test severity routing**

```bash
# Test INFO (email only — no push notification should appear):
bin/willflix-notify --severity INFO --key "test-info" --subject "INFO test" --body "Email only"

# Test WARNING (email + pushover normal):
bin/willflix-notify --severity WARNING --key "test-warning" --subject "WARNING test" --body "Email and push"

# Test CRITICAL (email + pushover emergency):
bin/willflix-notify --severity CRITICAL --key "test-critical" --subject "CRITICAL test" --body "Email and emergency push"

# Test --test mode:
bin/willflix-notify --test --subject "Full test" --body "All channels, no dedup"
```

**Step 4: Test dedup**

```bash
# Send once:
bin/willflix-notify --severity WARNING --key "dedup-test" --subject "Dedup test" --body "First send"
# Send again immediately — should be suppressed:
bin/willflix-notify --severity WARNING --key "dedup-test" --subject "Dedup test" --body "Should not send"
# Check syslog for DEDUP entry:
journalctl -t willflix-notify --no-pager | tail -5
```

---

### Task 4: willflix-heartbeat

**Files:**
- Create: `bin/cron/willflix-heartbeat`

**Step 1: Write willflix-heartbeat**

```bash
#!/bin/bash
# willflix-heartbeat — weekly channel test + daily monitor freshness checks.
#
# Usage:
#   willflix-heartbeat --full     # Sunday: test both channels + freshness + watchdog
#   willflix-heartbeat --silent   # Mon-Sat: freshness + watchdog only, alert on failures
#
# Cron:
#   0 9 * * 0   /willflix/bin/cron/willflix-heartbeat --full
#   0 9 * * 1-6 /willflix/bin/cron/willflix-heartbeat --silent

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"

MODE="${1:---silent}"

# Load config
CONFIG_FILE="${HOME}/.config/willflix-notify/config"
# shellcheck source=/dev/null
source "$CONFIG_FILE"

MONITOR_FRESHNESS_DIR="${MONITOR_FRESHNESS_DIR:-/var/tmp/willflix-monitors}"

# --- Channel test (--full only) ---

if [[ "$MODE" == "--full" ]]; then
    "$NOTIFY" --severity META --key "heartbeat-weekly" \
        --subject "lafayette weekly heartbeat" \
        --body "$(hostname) is alive. Both notification channels working. $(date)"
fi

# --- Monitor freshness checks ---

# Each entry: "script_name max_age_minutes"
MONITORS=(
    "check_mergerfs_health 45"
    "check_snapraid_freshness 2880"
    "snapraid_daily 4320"
)

STALE=""
for entry in "${MONITORS[@]}"; do
    name="${entry%% *}"
    max_age_min="${entry##* }"
    stamp="${MONITOR_FRESHNESS_DIR}/${name}"

    if [[ ! -f "$stamp" ]]; then
        STALE="${STALE}  ${name}: never ran (no timestamp file)\n"
        continue
    fi

    age_min=$(( ($(date +%s) - $(stat -c %Y "$stamp")) / 60 ))
    if [[ "$age_min" -gt "$max_age_min" ]]; then
        STALE="${STALE}  ${name}: last ran ${age_min}min ago (threshold: ${max_age_min}min)\n"
    fi
done

if [[ -n "$STALE" ]]; then
    "$NOTIFY" --severity WARNING --key "monitor-stale" \
        --subject "Monitor freshness check failed on $(hostname)" \
        --body "$(echo -e "The following monitors are stale:\n\n${STALE}\nCheck that cron jobs are running:\n  sudo crontab -l\n  journalctl -u cron --since '1 hour ago'")"
fi

# --- External watchdog ping ---

if [[ -n "${UPTIMEROBOT_HEARTBEAT_URL:-}" ]]; then
    curl -fsS --max-time 10 "$UPTIMEROBOT_HEARTBEAT_URL" >/dev/null 2>&1 || {
        "$NOTIFY" --severity WARNING --key "watchdog-ping-fail" \
            --subject "UptimeRobot ping failed on $(hostname)" \
            --body "Failed to ping UptimeRobot heartbeat URL. Check network connectivity."
    }
fi
```

**Step 2: Make executable and commit**

```bash
chmod +x bin/cron/willflix-heartbeat
git add bin/cron/willflix-heartbeat
git commit -m "Add willflix-heartbeat weekly/daily monitor script"
```

**Step 3: Test --full mode**

```bash
bin/cron/willflix-heartbeat --full
```

Verify: email + push notification with "lafayette weekly heartbeat" message.

**Step 4: Test --silent mode with no timestamp files**

```bash
# Make sure freshness dir is empty/missing:
rm -rf /var/tmp/willflix-monitors
bin/cron/willflix-heartbeat --silent
```

Verify: WARNING alert about stale monitors (all show "never ran").

---

### Task 5: Migrate check_mergerfs_health

**Files:**
- Modify: `bin/cron/check_mergerfs_health`

**Step 1: Update the script**

Replace the sendmail block at the end and add a freshness touch. The full updated script:

```bash
#!/bin/bash
# check_mergerfs_health - verify all mergerfs pool drives are healthy
# Detects: unmounted drives, I/O errors, read-only remounts.
# Run every 15 minutes via cron.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"
MONITOR_STAMP="/var/tmp/willflix-monitors/check_mergerfs_health"

EXPECTED_DRIVES="MediaA MediaB MediaC MediaD MediaE MediaF MediaG MediaH MediaI MediaJ MediaK"
ERRORS=""

for drive in $EXPECTED_DRIVES; do
    MOUNT="/Volumes/$drive"

    # Check if mounted
    if ! mountpoint -q "$MOUNT" 2>/dev/null; then
        ERRORS="${ERRORS}  $drive: NOT MOUNTED\n"
        continue
    fi

    # Check if readable (try listing the directory)
    if ! ls "$MOUNT/" >/dev/null 2>&1; then
        ERRORS="${ERRORS}  $drive: MOUNTED BUT UNREADABLE (I/O error)\n"
        continue
    fi

    # Check if read-only (remounted due to errors)
    if awk -v mp="$MOUNT" '$2 == mp { print $4 }' /proc/mounts | grep -q '\bro\b' 2>/dev/null; then
        ERRORS="${ERRORS}  $drive: REMOUNTED READ-ONLY (filesystem errors)\n"
        continue
    fi
done

# Also check that the mergerfs mount itself exists
if ! mountpoint -q /Volumes/Media 2>/dev/null; then
    ERRORS="${ERRORS}  MergerFS: /Volumes/Media NOT MOUNTED\n"
fi

if [ -n "$ERRORS" ]; then
    "$NOTIFY" --severity CRITICAL --key "mergerfs-degraded" \
        --subject "MergerFS pool degraded on $(hostname)" \
        --body "$(echo -e "One or more drives in the mergerfs pool have problems:\n\n${ERRORS}\nImmediate action required.\n\nQuick diagnostics:\n  df -h /Volumes/Media*\n  dmesg | grep -i error | tail -20\n  sudo smartctl -H /dev/sdX")"
fi

# Touch freshness stamp on successful check (even if errors found — the check itself ran)
mkdir -p "$(dirname "$MONITOR_STAMP")"
touch "$MONITOR_STAMP"
```

**Step 2: Commit**

```bash
git add bin/cron/check_mergerfs_health
git commit -m "Migrate check_mergerfs_health to willflix-notify"
```

---

### Task 6: Migrate check_snapraid_freshness

**Files:**
- Modify: `bin/cron/check_snapraid_freshness`

**Step 1: Update the script**

```bash
#!/bin/bash
# check_snapraid_freshness - independent staleness monitor
# Alerts if snapraid hasn't synced recently.
# Run via separate cron entry so it works even if sync cron is broken.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"
MONITOR_STAMP="/var/tmp/willflix-monitors/check_snapraid_freshness"

MAX_AGE_DAYS=3
CONTENT_FILE="/Volumes/MediaB/snapraid.content"

if [ ! -f "$CONTENT_FILE" ]; then
    "$NOTIFY" --severity CRITICAL --key "snapraid-content-missing" \
        --subject "SnapRAID content file missing on $(hostname)" \
        --body "The snapraid content file $CONTENT_FILE does not exist.
This means snapraid cannot sync or recover data."
    exit 1
fi

FILE_AGE_DAYS=$(( ($(date +%s) - $(stat -c %Y "$CONTENT_FILE")) / 86400 ))

if [ "$FILE_AGE_DAYS" -gt "$MAX_AGE_DAYS" ]; then
    # Also check if snapraid is currently running (might just be slow)
    SNAPRAID_RUNNING=$(pgrep -c snapraid || true)
    RUNNING_NOTE=""
    if [ "$SNAPRAID_RUNNING" -gt 0 ]; then
        RUNNING_NOTE="Note: snapraid is currently running ($(pgrep -a snapraid | head -1))"
    fi

    "$NOTIFY" --severity WARNING --key "snapraid-stale" \
        --subject "SnapRAID sync is ${FILE_AGE_DAYS} days stale on $(hostname)" \
        --body "The snapraid content file hasn't been updated in $FILE_AGE_DAYS days.
Last modified: $(stat -c %y "$CONTENT_FILE")
Threshold: $MAX_AGE_DAYS days
$RUNNING_NOTE

Check if snapraid cron is running:
  ps aux | grep snapraid

Check the log:
  tail -50 /var/log/snapraid-daily.log"
fi

# Touch freshness stamp
mkdir -p "$(dirname "$MONITOR_STAMP")"
touch "$MONITOR_STAMP"
```

**Step 2: Commit**

```bash
git add bin/cron/check_snapraid_freshness
git commit -m "Migrate check_snapraid_freshness to willflix-notify"
```

---

### Task 7: Migrate snapraid_daily

**Files:**
- Modify: `bin/cron/snapraid_daily`

**Step 1: Update the script**

Replace the `notify_failure` function to use `willflix-notify`. Add freshness stamp.

```bash
#!/bin/bash
# snapraid_daily - daily sync with timeout and alerting
# MediaJ post-mortem fix: timeouts prevent indefinite hangs,
# failures are logged and emailed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"
MONITOR_STAMP="/var/tmp/willflix-monitors/snapraid_daily"

SYNC_TIMEOUT=21600  # 6 hours max for sync
LOGFILE="/var/log/snapraid-daily.log"

notify_failure() {
    local msg="$1"
    echo "$(date): FAILURE: $msg" >> "$LOGFILE"
    "$NOTIFY" --severity CRITICAL --key "snapraid-daily-fail" \
        --subject "snapraid daily failed on $(hostname)" \
        --body "$msg

Check the log:
  tail -50 $LOGFILE
  ps aux | grep snapraid"
}

echo "$(date): Starting snapraid daily" >> "$LOGFILE"

# check_for_deletes (has its own 1hr timeout)
if ! /willflix/bin/cron/check_for_deletes >> "$LOGFILE" 2>&1; then
    notify_failure "check_for_deletes failed or timed out"
    exit 1
fi

echo "$(date): check_for_deletes passed, starting sync" >> "$LOGFILE"

# sync with timeout
if ! timeout "$SYNC_TIMEOUT" /usr/local/bin/snapraid --force-zero sync >> "$LOGFILE" 2>&1; then
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 124 ]; then
        notify_failure "snapraid sync timed out after ${SYNC_TIMEOUT}s"
    else
        notify_failure "snapraid sync failed with exit code $EXIT_CODE"
    fi
    exit 1
fi

echo "$(date): snapraid daily completed successfully" >> "$LOGFILE"

# Touch freshness stamp on success
mkdir -p "$(dirname "$MONITOR_STAMP")"
touch "$MONITOR_STAMP"
```

**Step 2: Commit**

```bash
git add bin/cron/snapraid_daily
git commit -m "Migrate snapraid_daily to willflix-notify"
```

---

### Task 8: Migrate snapraid_weekly

**Files:**
- Modify: `bin/cron/snapraid_weekly`

**Step 1: Update the script**

```bash
#!/bin/bash
# snapraid_weekly - daily sync + scrub
# Scrub validates parity data integrity.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"

SCRUB_TIMEOUT=43200  # 12 hours max for scrub
LOGFILE="/var/log/snapraid-daily.log"

/willflix/bin/cron/snapraid_daily

echo "$(date): Starting snapraid scrub" >> "$LOGFILE"

if ! timeout "$SCRUB_TIMEOUT" /usr/local/bin/snapraid scrub >> "$LOGFILE" 2>&1; then
    EXIT_CODE=$?
    echo "$(date): snapraid scrub failed (exit $EXIT_CODE)" >> "$LOGFILE"
    "$NOTIFY" --severity CRITICAL --key "snapraid-weekly-fail" \
        --subject "snapraid scrub failed on $(hostname)" \
        --body "snapraid scrub failed with exit code $EXIT_CODE.

Check the log:
  tail -50 $LOGFILE"
    exit 1
fi

echo "$(date): snapraid scrub completed successfully" >> "$LOGFILE"
```

**Step 2: Commit**

```bash
git add bin/cron/snapraid_weekly
git commit -m "Migrate snapraid_weekly to willflix-notify"
```

---

### Task 9: Migrate check_for_deletes

**Files:**
- Modify: `bin/cron/check_for_deletes`

**Step 1: Update the script**

`check_for_deletes` currently exits non-zero on excess deletes, and `snapraid_daily` catches that. It doesn't send its own alert — `snapraid_daily` does via `notify_failure`. So this script just needs a freshness stamp but no notification changes.

However, the excess-deletes case should get its own specific alert rather than being lumped into "snapraid daily failed":

```bash
#!/bin/bash
# check_for_deletes - safety check before snapraid sync
# Prevents sync if unexpected mass deletes detected.
# Has timeout to prevent hanging on I/O errors (MediaJ post-mortem fix).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"

TIMEOUT=3600  # 1 hour max for diff
IGNORE_PATTERN="^removed (Backups|Plex)"

DIFF_OUTPUT=$(timeout "$TIMEOUT" snapraid diff 2>&1) || {
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 124 ]; then
        echo "snapraid diff timed out after ${TIMEOUT}s — possible drive I/O issue" >&2
    else
        echo "snapraid diff failed with exit code $EXIT_CODE" >&2
        echo "$DIFF_OUTPUT" >&2
    fi
    exit 1
}

# Check for unexpected deletes (replaces old Ruby version)
DELETED_LINES=$(echo "$DIFF_OUTPUT" | grep "^removed " | grep -v -E "$IGNORE_PATTERN" || true)
DELETED_COUNT=0
if [ -n "$DELETED_LINES" ]; then
    DELETED_COUNT=$(echo "$DELETED_LINES" | wc -l)
fi

if [ "$DELETED_COUNT" -gt 0 ]; then
    "$NOTIFY" --severity CRITICAL --key "snapraid-excess-deletes" \
        --subject "SnapRAID: $DELETED_COUNT unexpected deletes on $(hostname)" \
        --body "snapraid sync blocked — $DELETED_COUNT files were deleted unexpectedly.

Deleted files:
$(echo "$DELETED_LINES" | head -20)
$([ "$DELETED_COUNT" -gt 20 ] && echo "... and $((DELETED_COUNT - 20)) more")

This could indicate a drive failure or accidental deletion.
Sync has been blocked to protect parity.

To investigate:
  snapraid diff | grep '^removed'
  dmesg | grep -i error | tail -20"
    exit 1
fi
```

**Step 2: Commit**

```bash
git add bin/cron/check_for_deletes
git commit -m "Migrate check_for_deletes to willflix-notify"
```

---

### Task 10: Update crontab and AGENTS.md

**Files:**
- Modify: `etc/root-crontab`
- Modify: `AGENTS.md`

**Step 1: Add heartbeat entries to crontab**

Add to `etc/root-crontab`:

```
# Heartbeat — weekly channel test (Sun 9am), daily freshness + watchdog (Mon-Sat 9am)
0 9 * * 0 /willflix/bin/cron/willflix-heartbeat --full
0 9 * * 1-6 /willflix/bin/cron/willflix-heartbeat --silent
```

**Step 2: Update AGENTS.md alerting section**

Replace the Alerting section in `AGENTS.md`:

```markdown
### Alerting
- Use `willflix-notify` for all alerts — never call sendmail directly
- Usage: `willflix-notify --severity CRITICAL --key "unique-key" --subject "..." --body "..."`
- Severity levels: INFO (email only), WARNING (email + push), CRITICAL (email + emergency push), META (cross-channel failover)
- Config: `~/.config/willflix-notify/config` (Pushover creds, email, dedup settings)
- Dedup: same `--key` suppressed for 6 hours by default
- Always include diagnostic commands in the `--body` so the user knows what to run
- Monitor freshness: touch `/var/tmp/willflix-monitors/<script-name>` on successful completion
- Test delivery: `willflix-notify --test --subject "Test"`
```

**Step 3: Commit**

```bash
git add etc/root-crontab AGENTS.md
git commit -m "Add heartbeat cron entries, update AGENTS.md for willflix-notify"
```

**Step 4: Apply the crontab to the live system**

```bash
sudo crontab etc/root-crontab
sudo crontab -l  # verify
```

---

### Task 11: End-to-end verification

**Step 1: Verify all scripts are executable and resolve willflix-notify correctly**

```bash
ls -la bin/willflix-notify bin/willflix-notify-send bin/cron/willflix-heartbeat
# All should show -rwxr-xr-x
```

**Step 2: Run full test notification**

```bash
bin/willflix-notify --test --subject "Phase 1 complete — end-to-end test" \
  --body "If you received this via email AND Pushover, Phase 1 is working."
```

Verify:
- Email arrives in Gmail
- Push notification appears on iPhone
- Syslog entry: `journalctl -t willflix-notify --no-pager | tail -5`

**Step 3: Test dedup across scripts**

```bash
# Run mergerfs check twice — second should be deduped if first found errors:
bin/cron/check_mergerfs_health
bin/cron/check_mergerfs_health
journalctl -t willflix-notify --no-pager | tail -10
# Should see DEDUP entry on second run (if first run triggered an alert)
```

**Step 4: Test heartbeat --full**

```bash
bin/cron/willflix-heartbeat --full
```

Verify: heartbeat notification via both channels.

**Step 5: Verify freshness stamps are being created**

```bash
ls -la /var/tmp/willflix-monitors/
# Should show: check_mergerfs_health, check_snapraid_freshness (after running those scripts)
```

**Step 6: Commit any final adjustments and tag**

```bash
git tag phase1-notify-complete
```
