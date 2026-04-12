# LLM Auto-Remediation Design

**Date:** 2026-04-12  
**Status:** Approved

## Problem

Monitoring cron scripts produce noisy alerts. Many issues are transient and fixable automatically (stuck queue items, stopped containers after upgrades). Currently every detection triggers a notification requiring manual intervention.

## Goals

- Reduce alert noise for low-risk, auto-fixable issues
- For medium-risk issues: attempt a fix, always alert, but include fix status
- For high-risk issues: LLM diagnoses only, include diagnosis in alert
- LLM failures must never prevent alerts from firing or scripts from completing

## Non-Goals

- Full agentic autonomy (no free-form shell access)
- Retrofitting all scripts immediately (opt-in, incremental)

## Architecture

Three new artifacts:

```
bin/willflix-remediate          — tool called by cron scripts before willflix-notify
etc/willflix-remediation.conf   — per-script config (risk + goal + allowedTools)
log/willflix-remediate.log      — all LLM activity logged here
```

No existing scripts or infrastructure changes are required to adopt this. Each script opts in explicitly.

### Risk Levels

| Risk | LLM action | Alert behaviour |
|------|-----------|-----------------|
| `low` | Attempt fix | Suppressed if fix verified; otherwise sent normally |
| `medium` | Attempt fix | Always sent; body includes fix status |
| `high` | Diagnose only | Always sent; body includes diagnosis |

### Flow

```
LOW:
  detect issues
  → willflix-remediate (attempt fix)
    → success + verified: log "auto-fixed", exit 0
    → failure / timeout:  exit 1
  → exit 0: script exits silently (alert suppressed)
  → exit 1: script calls willflix-notify as normal

MEDIUM:
  detect issues
  → willflix-remediate (attempt fix)
  → always call willflix-notify
  → append LLM output to alert body (fix status or failure reason)

HIGH:
  detect issues
  → willflix-remediate (diagnose only, read-only tools)
  → always call willflix-notify
  → append LLM diagnosis to alert body
```

## Config Format

`etc/willflix-remediation.conf` (YAML):

```yaml
scripts:
  check_media_apps:
    risk: low
    goal: >
      Remove stuck or failed queue items from Sonarr, Radarr, and NZBGet
      blocking downloads. Restart apps if they appear stuck.
    allowed_tools:
      - "Bash(curl -s http://localhost:8989/api/v3/queue*)"
      - "Bash(curl -s -X DELETE http://localhost:8989/api/v3/queue/*)"
      - "Bash(curl -s http://localhost:7878/api/v3/queue*)"
      - "Bash(curl -s -X DELETE http://localhost:7878/api/v3/queue/*)"
      - "Bash(docker compose -f /willflix/docker/compose.yml restart sonarr)"
      - "Bash(docker compose -f /willflix/docker/compose.yml restart radarr)"
      - "Bash(docker compose -f /willflix/docker/compose.yml restart nzbget)"

  willflix-check-services:
    risk: medium
    goal: >
      Restart stopped or crash-looping containers. Check logs to understand
      why before restarting.
    allowed_tools:
      - "Bash(docker compose -f /willflix/docker/compose.yml restart *)"
      - "Bash(docker compose -f /willflix/docker/compose.yml logs --tail=50 *)"
      - "Bash(docker inspect *)"

  update_containers:
    risk: medium
    goal: >
      If a container failed to start after an update, check its logs and
      attempt a restart. If a config migration is needed, diagnose and report.
    allowed_tools:
      - "Bash(docker compose -f /willflix/docker/compose.yml restart *)"
      - "Bash(docker compose -f /willflix/docker/compose.yml logs --tail=100 *)"
      - "Bash(docker inspect *)"

  check_mergerfs_health:
    risk: high
    goal: >
      Diagnose drive mount failures. Check dmesg, smartctl status, and mount
      table. Do not attempt to remount or modify anything.
    allowed_tools:
      - "Bash(df -h /Volumes/Media*)"
      - "Bash(dmesg | tail -30)"
      - "Bash(cat /proc/mounts)"
      - "Bash(sudo smartctl -H /dev/disk/by-id/*)"

  check_snapraid_freshness:
    risk: high
    goal: >
      Diagnose why SnapRAID sync has not run recently. Check cron logs and
      snapraid status. Do not run sync.
    allowed_tools:
      - "Bash(sudo snapraid status)"
      - "Bash(cat /willflix/log/snapraid_daily.log)"
      - "Bash(cat /willflix/log/snapraid_weekly.log)"
```

`verify_cmd` is an optional per-script override for verification. Default is to re-run the original detection script.

## `willflix-remediate` Implementation

`bin/willflix-remediate` — Python, ~150 lines.

### Interface

```
willflix-remediate --script <name> --findings <text> [--verify-cmd <cmd>]

Exit codes:
  0 — issue fixed and verified (caller may suppress alert)
  1 — not fixed, timed out, or errored (caller sends alert)
```

### Execution model

1. Load per-script config from `etc/willflix-remediation.conf`. If script not found, exit 1.
2. Write an ephemeral `settings.json` to a temp file:
   ```json
   {
     "allowedTools": ["<entries from config>"],
     "permissions": { "deny": ["Write", "Edit", "MultiEdit"] }
   }
   ```
3. Build prompt (see Prompt section below).
4. Run with hard timeout:
   ```
   claude --settings <tmpfile> --print -p "<prompt>"
   timeout: 120s
   ```
5. On `TimeoutExpired` or any exception: log it, exit 1.
6. Log all Claude output to `/willflix/log/willflix-remediate.log`.
7. For `high` risk: print Claude output (caller appends to alert), exit 1.
8. Parse the last JSON line from Claude output for `{"fixed": true/false, ...}`.
9. If `fixed: true`: run verification check (re-run script or `verify_cmd`).
10. If verification passes: log success, exit 0.
11. Otherwise: print Claude output, exit 1.

The temp settings file is always cleaned up in a `finally` block.

### Prompt structure

```
You are an automated remediation agent for the Willflix server (lafayette).

SYSTEM CONTEXT:
<key sections from AGENTS.md: alerting contract, docker conventions, storage layout>

RISK LEVEL: {low|medium|high}
- low/medium: attempt to fix using your allowed tools
- high: diagnose only — do not make any changes

GOAL: {goal from config}

FINDINGS:
{findings text passed by caller}

End your response with a JSON summary on the last line:
{"fixed": true/false, "actions_taken": ["..."], "diagnosis": "...", "recommendation": "..."}
```

### Verification

```python
def verify(script_name, verify_cmd=None):
    if verify_cmd:
        result = subprocess.run(verify_cmd, shell=True, timeout=60)
        return result.returncode == 0
    # Default: re-run the original detection script
    script = CRON_DIR / script_name
    result = subprocess.run([str(script)], capture_output=True, timeout=300)
    return result.returncode == 0
```

## Script Integration Pattern

### Python scripts (check_media_apps, willflix-check-services, update_containers)

```python
if issues:
    subject, body = build_report(issues)

    try:
        remediate = subprocess.run(
            ["willflix-remediate", "--script", SCRIPT_NAME, "--findings", body],
            capture_output=True, text=True, timeout=180
        )
    except Exception:
        remediate = None  # fail safe

    if remediate and remediate.returncode == 0:
        log("Auto-remediated by LLM — alert suppressed")
        return

    final_body = body
    if remediate and remediate.stdout.strip():
        final_body += f"\n\n--- Auto-remediation attempt ---\n{remediate.stdout}"

    notify(SEVERITY, KEY, subject, final_body)
```

For `medium` risk, replace the early `return` with a status note appended to body — notify always fires.

### Bash scripts (check_mergerfs_health)

```bash
LLM_DIAGNOSIS=$(willflix-remediate --script check_mergerfs_health \
    --findings "$ERRORS" 2>/dev/null || true)

"$NOTIFY" --severity CRITICAL --key "mergerfs-degraded" \
    --subject "MergerFS pool degraded on $(hostname)" \
    --body "$(printf '%s\n\n--- LLM Diagnosis ---\n%s' "$ERRORS" "$LLM_DIAGNOSIS")"
```

`willflix-remediate` is always wrapped in `|| true` — it must never prevent the alert from firing.

## Safety Properties

1. **Hard timeout (120s)** — `willflix-remediate` cannot hang indefinitely
2. **Outer timeout (180s)** — each calling script wraps the call in its own timeout
3. **Fail-open** — any error in `willflix-remediate` exits 1, script alerts normally
4. **Ephemeral permissions** — temp settings.json written and deleted per-invocation
5. **Enforcement by Claude Code** — `allowedTools` is enforced by the Claude Code permission system, not custom validation code
6. **Deny list** — `Write`/`Edit`/`MultiEdit` always denied as a safety net
7. **Independent verification** — `fixed: true` from LLM is never trusted; original check re-runs
8. **HIGH always alerts** — `willflix-remediate` exits 1 unconditionally for high-risk scripts
9. **Full audit log** — all LLM output written to `log/willflix-remediate.log` with timestamp and script name

## Rollout Order

1. Implement `willflix-remediate` (no scripts changed yet, can test standalone)
2. Wire up `check_media_apps` (low risk, highest alert noise)
3. Wire up `willflix-check-services` (medium risk)
4. Wire up `update_containers` (medium risk)
5. Wire up `check_mergerfs_health` and `check_snapraid_freshness` (high risk, diagnosis only)
6. Remaining scripts as needed

## Files Changed

| File | Change |
|------|--------|
| `bin/willflix-remediate` | New |
| `etc/willflix-remediation.conf` | New |
| `bin/cron/check_media_apps` | Add remediate call |
| `bin/cron/willflix-check-services` | Add remediate call |
| `bin/cron/update_containers` | Add remediate call |
| `bin/cron/check_mergerfs_health` | Add remediate call (diagnosis) |
| `bin/cron/check_snapraid_freshness` | Add remediate call (diagnosis) |
| `AGENTS.md` | Document willflix-remediate usage |
