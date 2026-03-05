# Phase 1: Notification Foundation — Design

**Date**: 2026-03-04
**Status**: Complete
**PRD**: `docs/lafayette-health-monitoring-prd.md`, Phase 1

---

## Goals

Establish a multi-channel notification system so no monitoring alert depends on a single delivery path. Replace all raw `sendmail` calls in P0 scripts with a unified notification interface.

**Deliverables:**
- `willflix-notify` — routing, dedup, severity logic
- `willflix-notify-send` — channel-specific delivery (email, Pushover)
- `willflix-heartbeat` — weekly channel test + daily monitor freshness checks
- External watchdog via UptimeRobot
- All P0 scripts migrated to `willflix-notify`

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Push notifications | Pushover ($5 one-time) | Ultra-reliable, 14-year track record, simple curl API, native iOS app. No self-hosting to maintain. |
| SMS | Skipped | Pushover emergency priority bypasses DND and repeats until acknowledged. Two channels (email + Pushover) satisfies redundancy requirement. |
| Language | Bash | Matches all existing P0 scripts. No runtime dependencies. Fits "simple beats clever" principle. |
| Architecture | Two scripts (dispatch + channels) | Clean separation between routing logic and delivery. Easy to add channels later. |
| Dedup | File-based in /var/tmp | Simple, survives reboots, auto-cleaned by OS. No database needed. |
| External watchdog | UptimeRobot | Free tier, heartbeat mode, independent infrastructure. |

---

## Component Architecture

### Scripts

| Script | Purpose | Location |
|--------|---------|----------|
| `willflix-notify` | Public API. Routing, dedup, severity logic. All monitoring scripts call this. | `bin/willflix-notify` |
| `willflix-notify-send` | Internal. Channel-specific delivery. Called only by `willflix-notify`. | `bin/willflix-notify-send` |
| `willflix-heartbeat` | Weekly channel test + daily freshness/watchdog checks. | `bin/cron/willflix-heartbeat` |

### Flow

```
monitoring script
  → willflix-notify (parse args, check dedup, determine channels by severity)
    → willflix-notify-send --channel email --subject "..." --body "..."
    → willflix-notify-send --channel pushover --priority 2 --subject "..." --body "..."
```

---

## CLI Interface

### willflix-notify (public API)

```bash
# Standard usage:
willflix-notify --severity CRITICAL --key "mergerfs-degraded" \
  --subject "MergerFS pool degraded" \
  --body "MediaC missing from /Volumes/Media pool"

# Pipe body from stdin:
snapraid_output | willflix-notify --severity WARNING --key "snapraid-errors" \
  --subject "SnapRAID sync had errors"

# Test mode (all channels, bypass dedup):
willflix-notify --test --subject "Test notification"
```

| Arg | Required | Description |
|-----|----------|-------------|
| `--severity` | yes | `INFO`, `WARNING`, `CRITICAL`, `META` |
| `--key` | yes | Dedup key (e.g., `mergerfs-degraded`). Same key suppressed within window. |
| `--subject` | yes | Short summary (email subject / push title) |
| `--body` | no | Detail text. If omitted, reads stdin. If neither, subject-only. |
| `--test` | no | Bypass severity routing and dedup, send via all channels |

### willflix-notify-send (internal)

| Arg | Required | Description |
|-----|----------|-------------|
| `--channel` | yes | `email` or `pushover` |
| `--subject` | yes | Message title |
| `--body` | no | Message body |
| `--priority` | no | Pushover priority: `-1` (silent), `0` (normal), `2` (emergency) |

---

## Severity Routing

| Severity | Email | Pushover | Pushover Priority |
|----------|-------|----------|-------------------|
| INFO | yes | no | — |
| WARNING | yes | yes | normal (0) |
| CRITICAL | yes | yes | emergency (2) — repeats until acknowledged |
| META | cross-channel failover (see Error Handling) | | |

---

## Configuration

**Config file**: `~/.config/willflix-notify/config`

**Example config** (shipped as `etc/willflix-notify.config.example`):

```bash
# Pushover credentials (https://pushover.net)
PUSHOVER_APP_TOKEN=""
PUSHOVER_USER_KEY=""

# Email recipient
NOTIFY_EMAIL="wemcdonald@gmail.com"

# Dedup settings
DEDUP_DIR="/var/tmp/willflix-notify"
DEDUP_WINDOW=21600  # 6 hours in seconds

# UptimeRobot heartbeat URL
UPTIMEROBOT_HEARTBEAT_URL=""

# Monitor freshness directory
MONITOR_FRESHNESS_DIR="/var/tmp/willflix-monitors"
```

**First-run behavior**: If config file doesn't exist, `willflix-notify` creates `~/.config/willflix-notify/`, copies the example config there, prints a message telling the user to fill in the keys, and exits 1.

---

## Dedup Mechanics

- **State dir**: `/var/tmp/willflix-notify/`
- **Key file**: `/var/tmp/willflix-notify/<key>` (plain filename — keys are short readable strings like `mergerfs-degraded`)
- **On send**: touch the key file
- **Before send**: if key file exists and age < `DEDUP_WINDOW` (default 6h), skip silently
- **`--test`**: bypasses dedup entirely

---

## Error Handling

### Channel failures in willflix-notify-send
- Email fails (sendmail exit code != 0): log to stderr, exit 1
- Pushover fails (curl HTTP status != 200): log to stderr, exit 1

### META severity (cross-channel failover)
- Send via both channels
- If email fails → send Pushover message: "Email alerting is broken"
- If Pushover fails → send email: "Pushover alerting is broken"
- If both fail → log to `/var/log/willflix-notify-failures.log`

### Logging
- All sends logged to syslog via `logger -t willflix-notify` (one line per send: timestamp, severity, key, channels, success/fail)
- Failures additionally written to stderr (so cron's MAILTO captures them)

---

## Heartbeat & External Watchdog

### willflix-heartbeat

**Two modes:**

| Mode | Schedule | Actions |
|------|----------|---------|
| `--full` | Sunday 9am | Send test via both channels + freshness checks + UptimeRobot ping |
| `--silent` | Mon-Sat 9am | Freshness checks + UptimeRobot ping only. Alert only on failures. |

**Cron entries:**
```
0 9 * * 0   /willflix/bin/cron/willflix-heartbeat --full
0 9 * * 1-6 /willflix/bin/cron/willflix-heartbeat --silent
```

### Monitor freshness checks

Each monitoring script touches `/var/tmp/willflix-monitors/<script-name>` on successful run. Heartbeat checks timestamps:

| Monitor | Expected interval | Alert if stale |
|---------|------------------|----------------|
| `check_mergerfs_health` | 15 min | > 45 min |
| `check_snapraid_freshness` | daily | > 2 days |
| `snapraid_daily/weekly` | daily | > 3 days |

### UptimeRobot
- Daily `curl` ping to configured heartbeat URL
- If lafayette stops pinging, UptimeRobot alerts independently

---

## P0 Script Migration

Replace raw `sendmail` calls with `willflix-notify`. Add monitor freshness touch files.

| Script | Severity | Dedup Key |
|--------|----------|-----------|
| `check_mergerfs_health` | CRITICAL | `mergerfs-degraded` |
| `check_snapraid_freshness` | WARNING / CRITICAL | `snapraid-stale` |
| `snapraid_daily` | CRITICAL (on failure) | `snapraid-daily-fail` |
| `snapraid_weekly` | CRITICAL (on failure) | `snapraid-weekly-fail` |
| `check_for_deletes` | CRITICAL (excess deletes) | `snapraid-excess-deletes` |

Each script also touches `/var/tmp/willflix-monitors/<script-name>` on successful completion.

---

## File Layout

**In repo:**
```
willflix/
├── bin/
│   ├── willflix-notify              # Routing, dedup, severity
│   ├── willflix-notify-send         # Channel delivery
│   └── cron/
│       ├── willflix-heartbeat       # Weekly heartbeat + daily freshness
│       ├── check_mergerfs_health    # (migrated)
│       ├── check_snapraid_freshness # (migrated)
│       ├── snapraid_daily           # (migrated)
│       ├── snapraid_weekly          # (migrated)
│       └── check_for_deletes        # (migrated)
├── etc/
│   └── willflix-notify.config.example
└── docs/
    └── plans/
        └── 2026-03-04-phase1-notify-design.md
```

**Runtime state (not in repo):**
```
~/.config/willflix-notify/config        # API keys, email address
/var/tmp/willflix-notify/<key>           # Dedup state files
/var/tmp/willflix-monitors/<script>      # Monitor freshness timestamps
```
