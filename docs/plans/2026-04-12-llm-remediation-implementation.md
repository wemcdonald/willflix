# LLM Auto-Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `willflix-remediate` — a tool that intercepts cron alerts, calls Claude Code with a constrained allowedTools settings file, and suppresses low-risk alerts when fixes are verified.

**Architecture:** A new `bin/willflix-remediate` Python script reads per-script config from `etc/willflix-remediation.conf`, writes an ephemeral Claude Code `settings.json` with the allowed tools, invokes Claude non-interactively, verifies the fix, and exits 0 (suppressed) or 1 (alert normally). Existing scripts opt in by calling it before `willflix-notify`.

**Tech Stack:** Python 3.11+, pyyaml, pytest, Claude Code CLI (`/home/will/.local/bin/claude`), existing `willflix-notify` / `willflix-cron` infrastructure.

---

## Important Context

- **Repo root:** `/willflix/` — all paths below are relative to this
- **Claude binary:** `/home/will/.local/bin/claude` — this is the real binary, NOT the shell alias `claude --dangerously-skip-permissions`. Using the binary directly means normal permissions apply — `allowedTools` is enforced.
- **Cron environment:** cron has a minimal PATH. Always use the absolute binary path for `claude` in subprocess calls.
- **ANTHROPIC_API_KEY:** must be present in the environment when Claude runs. Verify it's set in cron context (e.g. `/etc/environment` or the user's crontab `MAILTO`/env block) before wiring scripts into production.
- **Venv:** `willflix-cron` prepends `.venv/bin` to PATH. `willflix-remediate` should use the same venv python.
- **Exit code contract:** exit 0 = "fixed and verified". exit 1 = "anything else". Callers must treat non-zero as "send alert normally" — never as a script failure.
- **Design doc:** `docs/plans/2026-04-12-llm-remediation-design.md`

---

## Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Add pyyaml and pytest to requirements.txt**

```
mempalace
pyyaml
pytest
```

**Step 2: Install into venv**

```bash
cd /willflix
.venv/bin/pip install pyyaml pytest
```

Expected: both install cleanly.

**Step 3: Verify**

```bash
.venv/bin/python -c "import yaml; print('ok')"
.venv/bin/pytest --version
```

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add pyyaml and pytest"
```

---

## Task 2: Create remediation config

**Files:**
- Create: `etc/willflix-remediation.conf`

**Step 1: Create the config**

```yaml
# willflix-remediation.conf — per-script LLM remediation config
#
# risk:
#   low    — LLM attempts fix; alert suppressed if verified fixed
#   medium — LLM attempts fix; alert ALWAYS sent with fix status appended
#   high   — LLM diagnoses only; diagnosis appended to alert; no changes made
#
# allowed_tools: Claude Code allowedTools syntax — enforced by the permission system.
#   Each entry is a glob pattern, e.g. "Bash(docker compose * restart sonarr)"
#   Reference: https://docs.anthropic.com/en/docs/claude-code/settings#permissions
#
# verify_cmd: optional shell command to verify fix (default: re-run original script)

scripts:
  check_media_apps:
    risk: low
    goal: >
      Remove stuck or failed queue items from Sonarr, Radarr, and NZBGet
      that are blocking downloads. Restart apps if they appear stuck.
      Do not remove items that are still actively downloading.
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
      Restart stopped or crash-looping containers. Check logs before restarting
      to distinguish a transient crash from a config/upgrade issue.
    allowed_tools:
      - "Bash(docker compose -f /willflix/docker/compose.yml restart *)"
      - "Bash(docker compose -f /willflix/docker/compose.yml logs --tail=50 *)"
      - "Bash(docker inspect *)"

  update_containers:
    risk: medium
    goal: >
      If a container failed to start after an image update, check its logs
      and attempt a restart. If a config migration appears needed, diagnose
      and report — do not edit config files.
    allowed_tools:
      - "Bash(docker compose -f /willflix/docker/compose.yml restart *)"
      - "Bash(docker compose -f /willflix/docker/compose.yml logs --tail=100 *)"
      - "Bash(docker inspect *)"

  check_mergerfs_health:
    risk: high
    goal: >
      Diagnose drive mount failures. Check dmesg, smartctl, and mount table.
      Do not attempt to remount, fsck, or modify anything.
    allowed_tools:
      - "Bash(df -h /Volumes/Media*)"
      - "Bash(dmesg | tail -30)"
      - "Bash(cat /proc/mounts)"
      - "Bash(sudo smartctl -H /dev/disk/by-id/*)"

  check_snapraid_freshness:
    risk: high
    goal: >
      Diagnose why SnapRAID sync has not run recently.
      Check cron logs and snapraid status. Do not run sync.
    allowed_tools:
      - "Bash(sudo snapraid status)"
      - "Bash(cat /willflix/log/snapraid_daily.log)"
      - "Bash(cat /willflix/log/snapraid_weekly.log)"
```

**Step 2: Verify it parses**

```bash
.venv/bin/python -c "
import yaml
with open('etc/willflix-remediation.conf') as f:
    d = yaml.safe_load(f)
for name, cfg in d['scripts'].items():
    print(name, cfg['risk'], len(cfg.get('allowed_tools', [])), 'tools')
"
```

Expected output:
```
check_media_apps low 7 tools
willflix-check-services medium 3 tools
update_containers medium 3 tools
check_mergerfs_health high 4 tools
check_snapraid_freshness high 3 tools
```

**Step 3: Commit**

```bash
git add etc/willflix-remediation.conf
git commit -m "feat: add willflix-remediation.conf"
```

---

## Task 3: Tests for pure functions

**Files:**
- Create: `tests/test_willflix_remediate.py`

These tests cover the two pure functions that are straightforward to unit-test. They run without network or Claude.

**Step 1: Create test file**

```python
"""Tests for willflix-remediate pure functions."""
import json
import textwrap
from pathlib import Path

import pytest
import yaml


# ── helpers ──────────────────────────────────────────────────────────────────

def make_config(tmp_path: Path, entries: dict) -> Path:
    """Write a minimal remediation config and return its path."""
    cfg = {"scripts": entries}
    p = tmp_path / "willflix-remediation.conf"
    p.write_text(yaml.dump(cfg))
    return p


# ── load_config ───────────────────────────────────────────────────────────────

def test_load_config_returns_entry(tmp_path, monkeypatch):
    from bin.willflix_remediate import load_config
    cfg_path = make_config(tmp_path, {
        "my_script": {"risk": "low", "goal": "do stuff", "allowed_tools": ["Bash(ls)"]}
    })
    monkeypatch.setattr("bin.willflix_remediate.CONFIG_FILE", cfg_path)
    result = load_config("my_script")
    assert result["risk"] == "low"
    assert result["allowed_tools"] == ["Bash(ls)"]


def test_load_config_returns_none_for_missing_script(tmp_path, monkeypatch):
    from bin.willflix_remediate import load_config
    cfg_path = make_config(tmp_path, {"other_script": {"risk": "high", "goal": "x"}})
    monkeypatch.setattr("bin.willflix_remediate.CONFIG_FILE", cfg_path)
    assert load_config("nonexistent") is None


def test_load_config_returns_none_when_file_missing(tmp_path, monkeypatch):
    from bin.willflix_remediate import load_config
    monkeypatch.setattr("bin.willflix_remediate.CONFIG_FILE", tmp_path / "nope.conf")
    assert load_config("anything") is None


# ── parse_summary ─────────────────────────────────────────────────────────────

def test_parse_summary_extracts_last_json():
    from bin.willflix_remediate import parse_summary
    output = textwrap.dedent("""
        I tried restarting sonarr.
        It appears to be working now.
        {"fixed": true, "actions_taken": ["restart sonarr"], "diagnosis": "stuck", "recommendation": "monitor"}
    """)
    result = parse_summary(output)
    assert result["fixed"] is True
    assert "restart sonarr" in result["actions_taken"]


def test_parse_summary_fixed_false():
    from bin.willflix_remediate import parse_summary
    output = 'Some explanation\n{"fixed": false, "diagnosis": "unknown error", "actions_taken": [], "recommendation": "check logs"}'
    result = parse_summary(output)
    assert result["fixed"] is False


def test_parse_summary_returns_empty_on_no_json():
    from bin.willflix_remediate import parse_summary
    assert parse_summary("No JSON here at all.") == {}


def test_parse_summary_ignores_mid_output_json():
    from bin.willflix_remediate import parse_summary
    # JSON embedded in middle of output — should still find last one
    output = 'See {"not": "summary"} for details.\n{"fixed": true, "actions_taken": [], "diagnosis": "ok", "recommendation": ""}'
    result = parse_summary(output)
    assert result["fixed"] is True


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_contains_risk_and_goal(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", tmp_path / "AGENTS.md")  # no file
    result = build_prompt("low", "Fix stuck queue items", "sonarr queue has 3 failed items")
    assert "LOW" in result
    assert "Fix stuck queue items" in result
    assert "sonarr queue has 3 failed items" in result


def test_build_prompt_high_risk_says_diagnose_only(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", tmp_path / "AGENTS.md")
    result = build_prompt("high", "Diagnose drive failure", "MediaA not mounted")
    assert "diagnose" in result.lower() or "Diagnose" in result
    assert "do not make any changes" in result.lower() or "not make" in result.lower()


def test_build_prompt_includes_agents_md_when_present(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# System context for tests")
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", agents)
    result = build_prompt("medium", "goal", "findings")
    assert "System context for tests" in result
```

**Step 2: Run — expect import errors (module doesn't exist yet)**

```bash
cd /willflix
.venv/bin/pytest tests/test_willflix_remediate.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError` for `bin.willflix_remediate`. That's the red state.

**Step 3: Commit test file**

```bash
git add tests/test_willflix_remediate.py
git commit -m "test: add unit tests for willflix-remediate (red)"
```

---

## Task 4: Implement `willflix-remediate`

**Files:**
- Create: `bin/willflix-remediate`
- Create: `bin/willflix_remediate.py` (importable module, contains all logic)
- Modify: `tests/test_willflix_remediate.py` (fix import path if needed)

The entry point `bin/willflix-remediate` is a thin shim. All logic lives in `bin/willflix_remediate.py` so tests can import it.

**Step 1: Create `bin/willflix_remediate.py`**

```python
"""willflix-remediate — LLM-assisted auto-remediation for cron alerts.

Exit codes:
    0 — issue fixed and verified (caller may suppress alert)
    1 — not fixed, timed out, or any error (caller sends alert normally)
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_DIR / "etc" / "willflix-remediation.conf"
LOG_FILE = REPO_DIR / "log" / "willflix-remediate.log"
CRON_DIR = REPO_DIR / "bin" / "cron"
AGENTS_MD = REPO_DIR / "AGENTS.md"

# Absolute path — avoids shell alias `claude --dangerously-skip-permissions`
CLAUDE_BIN = "/home/will/.local/bin/claude"

LLM_TIMEOUT = 120    # seconds: hard ceiling on Claude call
VERIFY_TIMEOUT = 300  # seconds: re-running original check script


def setup_logging(script_name: str) -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("willflix-remediate")
    logger.setLevel(logging.DEBUG)
    # Avoid duplicate handlers if called multiple times in tests
    if not logger.handlers:
        handler = logging.FileHandler(LOG_FILE)
        handler.setFormatter(logging.Formatter(
            f"%(asctime)s [{script_name}] %(levelname)s: %(message)s"
        ))
        logger.addHandler(handler)
    return logger


def load_config(script_name: str) -> dict | None:
    """Load per-script remediation config. Returns None if not found."""
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE) as f:
        data = yaml.safe_load(f)
    return data.get("scripts", {}).get(script_name)


def build_prompt(risk: str, goal: str, findings: str) -> str:
    """Build the prompt for Claude."""
    agents_context = ""
    if AGENTS_MD.exists():
        agents_context = AGENTS_MD.read_text()

    instructions = {
        "low": (
            "Attempt to fix the issue using your allowed tools. "
            "If successful, output {\"fixed\": true} in your summary."
        ),
        "medium": (
            "Attempt to fix the issue using your allowed tools. "
            "You MUST report regardless of outcome — this alert will always be sent."
        ),
        "high": (
            "Diagnose only — do not make any changes to the system. "
            "Use your allowed tools to gather information and provide a diagnosis."
        ),
    }[risk]

    return f"""You are an automated remediation agent for the Willflix server (lafayette).

SYSTEM CONTEXT:
{agents_context}

RISK LEVEL: {risk.upper()}
{instructions}

GOAL: {goal}

FINDINGS:
{findings}

After completing your work, output a JSON summary on the final line:
{{"fixed": true/false, "actions_taken": ["..."], "diagnosis": "...", "recommendation": "..."}}
"""


def parse_summary(output: str) -> dict:
    """Extract the last JSON object from Claude output."""
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {}


def verify(script_name: str, verify_cmd: str | None) -> bool:
    """Verify the fix by re-running the detection script or a custom command."""
    try:
        if verify_cmd:
            result = subprocess.run(
                verify_cmd, shell=True, capture_output=True, timeout=60
            )
            return result.returncode == 0
        script = CRON_DIR / script_name
        if not script.exists():
            return False
        result = subprocess.run(
            [str(script)], capture_output=True, timeout=VERIFY_TIMEOUT
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def run(script_name: str, findings: str, verify_cmd_override: str | None) -> int:
    """Core logic. Returns exit code: 0 = fixed+verified, 1 = everything else."""
    logger = setup_logging(script_name)

    config = load_config(script_name)
    if not config:
        logger.error("No remediation config for script: %s", script_name)
        return 1

    risk = config["risk"]
    goal = config["goal"]
    allowed_tools = config.get("allowed_tools", [])
    verify_cmd = verify_cmd_override or config.get("verify_cmd")

    settings = {
        "allowedTools": allowed_tools,
        "permissions": {"deny": ["Write", "Edit", "MultiEdit"]},
    }
    prompt = build_prompt(risk, goal, findings)

    logger.info("Starting: risk=%s tools=%d", risk, len(allowed_tools))

    settings_fd, settings_path = tempfile.mkstemp(suffix=".json", prefix="willflix-remediate-")
    try:
        with os.fdopen(settings_fd, "w") as f:
            json.dump(settings, f)

        try:
            result = subprocess.run(
                [CLAUDE_BIN, "--settings", settings_path, "--print", "-p", prompt],
                capture_output=True, text=True, timeout=LLM_TIMEOUT,
            )
            output = result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            logger.error("Claude call timed out after %ds", LLM_TIMEOUT)
            return 1
        except Exception as e:
            logger.error("Claude call failed: %s", e)
            return 1

        logger.info("Claude output:\n%s", output)

        # HIGH risk: always print diagnosis, never suppress alert
        if risk == "high":
            print(output)
            return 1

        summary = parse_summary(output)
        logger.info("Parsed summary: %s", summary)

        if summary.get("fixed"):
            logger.info("LLM claims fixed — verifying")
            if verify(script_name, verify_cmd):
                logger.info("VERIFIED FIXED: actions=%s", summary.get("actions_taken", []))
                return 0
            logger.warning("Verification failed despite LLM claiming fix")

        # Print output so callers can append it to the alert body
        print(output)
        return 1

    finally:
        try:
            os.unlink(settings_path)
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="LLM-assisted auto-remediation for cron alerts."
    )
    parser.add_argument("--script", required=True, help="Cron script name (e.g. check_media_apps)")
    parser.add_argument("--findings", required=True, help="Description of detected issues")
    parser.add_argument("--verify-cmd", default=None, help="Override verification command")
    args = parser.parse_args()

    sys.exit(run(args.script, args.findings, args.verify_cmd))


if __name__ == "__main__":
    main()
```

**Step 2: Create `bin/willflix-remediate` entry point**

```python
#!/usr/bin/env python3
import sys
from pathlib import Path

# Allow `import bin.willflix_remediate` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bin.willflix_remediate import main

main()
```

Make it executable:

```bash
chmod +x bin/willflix-remediate
```

**Step 3: Add `tests/conftest.py` so pytest finds the bin module**

```python
import sys
from pathlib import Path

# Allow `from bin.willflix_remediate import ...` in tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

**Step 4: Run the tests — expect green**

```bash
cd /willflix
.venv/bin/pytest tests/test_willflix_remediate.py -v
```

Expected: all tests pass.

**Step 5: Smoke-test the CLI**

```bash
# Should exit 1 (script not in config yet) and log to log/willflix-remediate.log
bin/willflix-remediate --script nonexistent --findings "test"
echo "exit: $?"
cat log/willflix-remediate.log | tail -5
```

Expected: exit code 1, log entry showing "No remediation config".

**Step 6: Commit**

```bash
git add bin/willflix-remediate bin/willflix_remediate.py tests/conftest.py
git commit -m "feat: implement willflix-remediate core"
```

---

## Task 5: Verify ANTHROPIC_API_KEY in cron context

Before wiring any script, confirm Claude can actually run from cron.

**Step 1: Check where the key is set**

```bash
sudo grep -r ANTHROPIC /etc/environment /etc/cron* /var/spool/cron/crontabs/ 2>/dev/null | head -10
printenv ANTHROPIC_API_KEY | head -c 10  # just check it exists
```

**Step 2: If not in /etc/environment, add it**

```bash
# Check current value
printenv ANTHROPIC_API_KEY

# Add to /etc/environment so it's available to all cron jobs
echo "ANTHROPIC_API_KEY=$(printenv ANTHROPIC_API_KEY)" | sudo tee -a /etc/environment
```

**Step 3: Test end-to-end with real Claude (non-cron)**

```bash
cd /willflix
bin/willflix-remediate \
  --script check_media_apps \
  --findings "Test: sonarr queue has 1 stuck item - NZBGet:Failed - 'file not found'" \
  --verify-cmd "true"   # always passes, so we can test the happy path
echo "Exit: $?"
cat log/willflix-remediate.log | tail -20
```

Expected: Claude runs, attempts something, exits 0 (verify-cmd=`true` always passes).

**Step 4: Test that timeout protection works**

```bash
# Temporarily set a 1-second timeout to verify it fails safely
CLAUDE_TIMEOUT=1 bin/willflix-remediate --script check_media_apps --findings "test"
echo "Exit: $?"   # must be 1
```

(This requires a `CLAUDE_TIMEOUT` env var override — add `LLM_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", 120))` to the module if needed.)

**Step 5: No commit needed unless /etc/environment changed**

---

## Task 6: Wire up `check_media_apps` (low risk)

**Files:**
- Modify: `bin/cron/check_media_apps`

Read the current `main()` / alert-sending logic first: `bin/cron/check_media_apps` around the `notify(...)` call.

**Step 1: Find the notify call site**

```bash
grep -n "notify\|willflix-notify\|build_report" bin/cron/check_media_apps
```

**Step 2: Wrap the notify call**

In the function that calls `notify(...)` after building the report (typically at end of `main()`), add:

```python
import subprocess as _sp

SCRIPT_NAME = "check_media_apps"

# ... existing issue collection ...

if issues:
    subject, body = build_report(issues)

    # Attempt LLM remediation before alerting
    try:
        remediate = _sp.run(
            ["/willflix/bin/willflix-remediate",
             "--script", SCRIPT_NAME,
             "--findings", body],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as _e:
        _log_issues(f"willflix-remediate failed to run: {_e}")
        remediate = None

    if remediate is not None and remediate.returncode == 0:
        _log_issues("Auto-remediated by LLM — alert suppressed")
        return  # issue fixed and verified

    # Build final body — append LLM output if useful
    final_body = body
    if remediate is not None and remediate.stdout.strip():
        final_body += f"\n\n--- Auto-remediation attempt ---\n{remediate.stdout}"

    notify("WARNING", "check-media-apps", subject, final_body)
```

Note: use `/willflix/bin/willflix-remediate` (absolute path) — cron PATH is minimal.

**Step 3: Manual test — simulate a stuck item**

Trigger the script manually and confirm it runs without error:

```bash
cd /willflix && sudo bin/cron/check_media_apps
echo "Exit: $?"
cat log/check_media_apps.log | tail -20
cat log/willflix-remediate.log | tail -20
```

If there are real stuck items, check whether an alert was suppressed or sent. If no issues exist, confirm script exits 0 cleanly.

**Step 4: Commit**

```bash
git add bin/cron/check_media_apps
git commit -m "feat: wire willflix-remediate into check_media_apps (low risk)"
```

---

## Task 7: Wire up `willflix-check-services` (medium risk)

**Files:**
- Modify: `bin/cron/willflix-check-services`

Medium risk: **always notify**, but append LLM fix status to body.

**Step 1: Find the notify call sites**

```bash
grep -n "notify(" bin/cron/willflix-check-services
```

There may be multiple `notify()` calls (one per failing service). Find where the results are aggregated, or add remediation at the outermost level.

**Step 2: Add remediation before the final notify**

If issues are collected into a list and then reported in bulk, wrap the bulk report:

```python
SCRIPT_NAME = "willflix-check-services"

# ... existing detection ...

if issues_found:
    findings_text = "\n".join(issues_found)  # adjust to match actual variable

    try:
        remediate = subprocess.run(
            ["/willflix/bin/willflix-remediate",
             "--script", SCRIPT_NAME,
             "--findings", findings_text],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as e:
        remediate = None

    # Medium risk: ALWAYS notify
    llm_note = ""
    if remediate is not None and remediate.returncode == 0:
        llm_note = "\n\n--- LLM auto-fix applied and verified ---"
    elif remediate is not None and remediate.stdout.strip():
        llm_note = f"\n\n--- LLM remediation attempt ---\n{remediate.stdout}"

    for svc, severity, key, subject, body in pending_notifications:
        notify(severity, key, subject, body + llm_note)
```

Adjust variable names to match the actual script structure (read the script first).

**Step 3: Manual test**

```bash
cd /willflix && sudo bin/cron/willflix-check-services
echo "Exit: $?"
cat log/willflix-check-services.log | tail -20
```

**Step 4: Commit**

```bash
git add bin/cron/willflix-check-services
git commit -m "feat: wire willflix-remediate into willflix-check-services (medium risk)"
```

---

## Task 8: Wire up `update_containers` (medium risk)

**Files:**
- Modify: `bin/cron/update_containers`

Same medium-risk pattern as Task 7: always notify, append LLM status.

**Step 1: Find where update failures are reported**

```bash
grep -n "notify\|WARNING\|log_maintenance\|willflix-notify" bin/cron/update_containers
```

**Step 2: Add remediation around the failure-reporting block**

```python
SCRIPT_NAME = "update_containers"

# After detecting update failures:
if failed_services:
    findings_text = f"These containers failed after update: {', '.join(failed_services)}"

    try:
        remediate = subprocess.run(
            ["/willflix/bin/willflix-remediate",
             "--script", SCRIPT_NAME,
             "--findings", findings_text],
            capture_output=True, text=True, timeout=180,
        )
    except Exception:
        remediate = None

    llm_note = ""
    if remediate is not None and remediate.stdout.strip():
        status = "verified fixed" if remediate.returncode == 0 else "attempted (unresolved)"
        llm_note = f"\n\n--- LLM remediation {status} ---\n{remediate.stdout}"

    notify("WARNING", "update-containers-failure",
           f"Container update failures on {hostname}",
           existing_body + llm_note)
```

**Step 3: Manual test**

```bash
cd /willflix && sudo bin/cron/update_containers --dry-run
echo "Exit: $?"
```

**Step 4: Commit**

```bash
git add bin/cron/update_containers
git commit -m "feat: wire willflix-remediate into update_containers (medium risk)"
```

---

## Task 9: Wire up `check_mergerfs_health` (high risk, bash)

**Files:**
- Modify: `bin/cron/check_mergerfs_health`

High risk: LLM diagnoses only. Diagnosis appended to alert. `willflix-remediate` never suppresses.

**Step 1: Find the notify call**

The current notify call is near the end of the script. It looks like:

```bash
"$NOTIFY" --severity CRITICAL --key "mergerfs-degraded" \
    --subject "MergerFS pool degraded on $(hostname)" \
    --body "..."
```

**Step 2: Add diagnosis before the notify call**

```bash
# Attempt LLM diagnosis (high risk — never suppresses alert)
LLM_DIAGNOSIS=""
if command -v /willflix/bin/willflix-remediate >/dev/null 2>&1; then
    LLM_DIAGNOSIS=$(timeout 150 /willflix/bin/willflix-remediate \
        --script check_mergerfs_health \
        --findings "$ERRORS" 2>/dev/null || true)
fi

FULL_BODY="$(echo -e "One or more drives in the mergerfs pool have problems:\n\n${ERRORS}\nImmediate action required.\n\nQuick diagnostics:\n  df -h /Volumes/Media*\n  dmesg | grep -i error | tail -20\n  sudo smartctl -H /dev/sdX")"

if [ -n "$LLM_DIAGNOSIS" ]; then
    FULL_BODY="${FULL_BODY}\n\n--- LLM Diagnosis ---\n${LLM_DIAGNOSIS}"
fi

"$NOTIFY" --severity CRITICAL --key "mergerfs-degraded" \
    --subject "MergerFS pool degraded on $(hostname)" \
    --body "$(echo -e "$FULL_BODY")"
```

Note: `|| true` ensures remediate failure never blocks the alert.

**Step 3: Manual test (simulate an error)**

```bash
# Temporarily break the script to test with a fake error
ERRORS="  MediaA: NOT MOUNTED\n" bash -c '
  source bin/cron/check_mergerfs_health 2>/dev/null || true
'
# Or just run it and observe — if all drives are healthy, ERRORS will be empty
# and the notify block won't run
cd /willflix && sudo bin/cron/check_mergerfs_health
echo "Exit: $?"
```

**Step 4: Commit**

```bash
git add bin/cron/check_mergerfs_health
git commit -m "feat: wire willflix-remediate into check_mergerfs_health (high risk, diagnosis)"
```

---

## Task 10: Wire up `check_snapraid_freshness` (high risk, bash)

**Files:**
- Modify: `bin/cron/check_snapraid_freshness`

Same high-risk pattern as Task 9.

**Step 1: Read the notify call**

```bash
grep -n "NOTIFY\|notify\|willflix-notify" bin/cron/check_snapraid_freshness
```

**Step 2: Add diagnosis block before notify (same pattern as Task 9)**

```bash
LLM_DIAGNOSIS=""
if command -v /willflix/bin/willflix-remediate >/dev/null 2>&1; then
    LLM_DIAGNOSIS=$(timeout 150 /willflix/bin/willflix-remediate \
        --script check_snapraid_freshness \
        --findings "$ALERT_BODY" 2>/dev/null || true)
fi

FINAL_BODY="$ALERT_BODY"
if [ -n "$LLM_DIAGNOSIS" ]; then
    FINAL_BODY="${FINAL_BODY}\n\n--- LLM Diagnosis ---\n${LLM_DIAGNOSIS}"
fi
```

**Step 3: Test**

```bash
cd /willflix && sudo bin/cron/check_snapraid_freshness
echo "Exit: $?"
cat log/check_snapraid_freshness.log | tail -10
```

**Step 4: Commit**

```bash
git add bin/cron/check_snapraid_freshness
git commit -m "feat: wire willflix-remediate into check_snapraid_freshness (high risk, diagnosis)"
```

---

## Task 11: Update AGENTS.md

**Files:**
- Modify: `AGENTS.md`

**Step 1: Add a section after the existing "Alerting" section**

```markdown
### LLM Auto-Remediation

- `willflix-remediate` — calls Claude Code with a constrained `allowedTools` settings file to attempt fixes or diagnosis before alerts fire
- Config: `etc/willflix-remediation.conf` (per-script: risk level, goal, allowed tools)
- Usage from Python scripts:
  ```python
  remediate = subprocess.run(
      ["/willflix/bin/willflix-remediate", "--script", SCRIPT_NAME, "--findings", body],
      capture_output=True, text=True, timeout=180,
  )
  if remediate.returncode == 0:
      return  # fixed and verified — suppress alert (low risk only)
  ```
- Usage from bash scripts (high risk):
  ```bash
  LLM_DIAGNOSIS=$(timeout 150 /willflix/bin/willflix-remediate \
      --script <name> --findings "$ERRORS" 2>/dev/null || true)
  ```
- **Always** wrap in `|| true` / try-except — remediation must never prevent an alert from firing
- Risk levels: `low` (suppress if fixed), `medium` (always alert + status), `high` (diagnose only)
- Logs: `/willflix/log/willflix-remediate.log`
- Claude binary: `/home/will/.local/bin/claude` (NOT the shell alias)
```

**Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: document willflix-remediate in AGENTS.md"
```

---

## Rollout Complete

At this point:
- `check_media_apps` — low risk, alerts suppressed when LLM fixes verified
- `willflix-check-services` — medium risk, alerts always sent with fix status
- `update_containers` — medium risk, alerts always sent with fix status
- `check_mergerfs_health` — high risk, diagnosis appended to alert
- `check_snapraid_freshness` — high risk, diagnosis appended to alert

Remaining scripts (`backup_*`, etc.) can be added to `willflix-remediation.conf` and wired up following the same patterns.
