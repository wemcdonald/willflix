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

### LLM Auto-Remediation

- `willflix-remediate` — calls Claude with a constrained allowedTools settings file to attempt fixes or diagnosis before alerts fire
- Config: `etc/willflix-remediation.conf` (per-script: risk level, goal, allowed tools)
- Logs: `/willflix/log/willflix-remediate.log`
- Claude binary: `/home/will/.local/bin/claude` (NOT the shell alias — normal permissions apply)

**Risk levels:**
- `low` — fix attempted; alert suppressed if fix verified
- `medium` — fix attempted; alert always sent with fix status appended
- `high` — diagnosis only; diagnosis appended to alert; no changes made

**Usage from Python scripts (low risk example):**
```python
remediate = subprocess.run(
    ["/willflix/bin/willflix-remediate", "--script", SCRIPT_NAME, "--findings", body],
    capture_output=True, text=True, timeout=180,
)
if remediate is not None and remediate.returncode == 0:
    return  # fixed and verified — suppress alert
# append remediate.stdout to alert body if non-empty
```

**Usage from bash scripts (high risk):**
```bash
LLM_DIAGNOSIS=""
if [[ -x /willflix/bin/willflix-remediate ]]; then
    LLM_DIAGNOSIS=$(timeout 150 /willflix/bin/willflix-remediate \
        --script <name> --findings "$ERRORS" 2>/dev/null || true)
fi
# append LLM_DIAGNOSIS to alert body
```

**Always** wrap in `|| true` / try-except — remediation must never prevent an alert from firing.

### Documentation
- Postmortems and PRDs go in `docs/`
- Runbooks (step-by-step procedures) go in `docs/runbooks/`
- Keep docs actionable — include the exact commands to run

### Drive References
- Always use stable paths (`/dev/disk/by-id/ata-*`) in config files, never `/dev/sdX`
- In scripts, resolving `/dev/sdX` at runtime is fine for display purposes
- Reference drives by label (MediaA, MediaB, etc.) in documentation

### Docker
- Docker config lives in `/willflix/docker/` (`/docker` is a symlink to the same)
- `docker/compose.yml` — main compose file for all ~40 services
- `docker/images/` — custom-built images (Dockerfile + vendored source); one subdirectory per image
- `docker/appdata/` — container volumes (gitignored)
- Service management: always specify names, never bare `docker compose up -d`
