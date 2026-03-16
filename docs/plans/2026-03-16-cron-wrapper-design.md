# Cron Wrapper & Notify Debounce Design

Date: 2026-03-16

## Problem

Cron scripts produce stdout that cron emails to the user via MAILTO, even when everything is healthy. Combined with willflix-notify alerts, this creates duplicate/spammy emails. The daily-reset dedup in willflix-notify is also coarse — alerts repeat at the 8am boundary regardless of severity.

## Design

Two changes working together:

1. **`willflix-cron`** — a Python wrapper that every crontab entry uses
2. **Severity-based debounce** — enhance willflix-notify with per-severity default windows

### willflix-cron wrapper

Location: `/willflix/bin/willflix-cron`
Language: Python 3

**Crontab usage:**
```
*/15 * * * * /willflix/bin/willflix-cron check_mergerfs_health
0 */6 * * *  /willflix/bin/willflix-cron check_media_apps
30 3 * * *   /willflix/bin/willflix-cron update_containers
```

Resolves script name from `/willflix/bin/cron/` (basename) or accepts a full path.

**Behavior:**
1. Creates/appends to `/willflix/log/<script-name>.log` with a timestamped run header
2. Runs the script, capturing stdout and stderr to the log file
3. On **success (exit 0)**: touches `/var/tmp/willflix-monitors/<script-name>` freshness stamp. Cron sees no output, sends no email.
4. On **failure (non-zero exit)**: writes stdout+stderr to cron's stderr so cron emails the user. This catches broken monitors — syntax errors, missing deps, unhandled exceptions.

**Exit code contract for scripts:**
- Exit 0: "I ran successfully" — even if the thing I monitor is unhealthy (alerts sent via willflix-notify)
- Exit non-zero: "I myself broke" — the monitor failed, not just its subject

### willflix-notify debounce enhancement

Replace the daily-reset-at-8am dedup with severity-based fixed debounce windows:

| Severity | Default debounce | Rationale |
|----------|-----------------|-----------|
| CRITICAL | 1h | Needs attention, but not every 15 min |
| WARNING | 4h | Nudge a few times per day |
| INFO | 24h | Once a day is plenty |

- `--dedup-window` override still works for custom timing per call
- If no override, severity determines the window
- Drop the `DEDUP_RESET_HOUR` / `last_reset_epoch` daily-reset logic entirely
- Dedup state stays in `/var/tmp/willflix-notify/` (file mtime per key)

Config in `/willflix/etc/willflix-notify.config`:
```bash
DEDUP_WINDOW_CRITICAL=1h
DEDUP_WINDOW_WARNING=4h
DEDUP_WINDOW_INFO=24h
```

### Log format

Each run appended to `/willflix/log/<script-name>.log`:
```
=== 2026-03-16 14:15:00 ===
[stdout and stderr from the script, interleaved]

=== 2026-03-16 14:30:00 ===
[next run's output]
```

Empty runs still get the header to confirm the script ran.

### Logrotate

Config at `/willflix/etc/logrotate.d/willflix`, symlinked to `/etc/logrotate.d/willflix`:

```
/willflix/log/*.log {
    weekly
    rotate 4
    compress
    delaycompress
    missingok
    notifempty
}
```

### Script migration

| Script | Changes needed |
|--------|---------------|
| `willflix-check-services` | Remove stdout summary, remove freshness stamp touch |
| `update_containers` | Keep stdout (goes to log now), remove maintenance.log write, keep willflix-notify call |
| `check_mergerfs_health` | Remove freshness stamp touch |
| `check_snapraid_freshness` | Remove freshness stamp touch |
| All other cron scripts | Remove freshness stamp touching |
| Root crontab | Wrap all entries with `willflix-cron` |

### What doesn't change

- `willflix-notify-send` (channel handler)
- Severity routing (INFO/WARNING/CRITICAL/META)
- Pushover emergency retries
- META cross-channel failover
- `MAILTO=will` in crontab (still delivers broken-script alerts)

## User experience after implementation

- Drive unmounted? One willflix-notify alert. Another in 1 hour if still broken. No cron spam.
- update_containers runs fine? Silence. Details in `/willflix/log/update_containers.log`.
- Script itself crashes? Cron emails immediately — the monitor is broken.
- Want to check what happened? `cat /willflix/log/<script>.log`
