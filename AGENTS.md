# AGENTS.md — Conventions for AI agents working on this repo

For full system reference (architecture, drive layout, services, common operations), see [.claude/CLAUDE.md](.claude/CLAUDE.md).

## What This Repo Is
Ops repo for a personal headless media server (hostname: lafayette). Contains monitoring scripts, system documentation, runbooks, and PRDs for server health tooling.

## Principles

1. **This server runs unattended for years.** Every script must handle failures gracefully — log, alert, and exit cleanly. Never hang indefinitely.
2. **Silent failure is the worst failure.** If something breaks, it must make noise. Use `willflix-notify` for all alerts. Every cron job should have an independent staleness monitor.
3. **Simple beats clever.** Bash scripts in cron are preferred over daemons that can crash. Dependencies should be minimal.
4. **Two notification channels minimum.** Email + Pushover via `willflix-notify`. See `docs/lafayette-health-monitoring-prd.md`.
5. **Test the fix.** After writing a monitoring script, run it and verify the alert actually arrives in Gmail. Check `docker logs smtp-relay --tail 5` to confirm delivery.

## Conventions

### Scripts
- Cron scripts live in `bin/cron/` (symlinked from `~/bin/cron`)
- Use `#!/bin/bash` with `set -euo pipefail` where appropriate (but beware: `grep -q` returns 1 on no match, which kills `set -e`)
- Long-running operations must have `timeout` wrappers
- Send alerts via `willflix-notify` — never call sendmail directly
- Never use `/usr/bin/mail` — it's broken on this system
- Log to `/var/log/<scriptname>.log` for anything that runs from cron
- Touch `/var/tmp/willflix-monitors/<script-name>` on successful completion (for freshness monitoring)

### Alerting
- Use `willflix-notify` for all alerts — never call sendmail directly
- Usage: `willflix-notify --severity CRITICAL --key "unique-key" --subject "..." --body "..."`
- Severity levels: INFO (email only), WARNING (email + push), CRITICAL (email + emergency push), META (cross-channel failover)
- Config: `etc/willflix-notify.config` (defaults), `~/.config/willflix-notify/config` (optional overrides for credentials)
- Dedup: same `--key` suppressed until next 8am reset (configurable via DEDUP_RESET_HOUR)
- Always include diagnostic commands in the `--body` so the user knows what to run
- Test delivery: `willflix-notify --test --subject "Test"`

### Documentation
- Postmortems and PRDs go in `docs/`
- Runbooks (step-by-step procedures) go in `docs/runbooks/`
- Keep docs actionable — include the exact commands to run

### Drive References
- Always use stable paths (`/dev/disk/by-id/ata-*`) in config files, never `/dev/sdX`
- In scripts, resolving `/dev/sdX` at runtime is fine for display purposes
- Reference drives by label (MediaA, MediaB, etc.) in documentation

### Docker
- Docker config lives in `/docker/` (separate repo), not here
- Service management: always specify names, never bare `docker compose up -d`
- See `/docker/.claude/CLAUDE.md` for Docker-specific conventions
