"""willflix-remediate — LLM-assisted auto-remediation for cron alerts.

Architecture: two-phase.
  1. Call Claude with stdin=DEVNULL, no tool use — it outputs a JSON plan.
  2. willflix-remediate validates and executes commands from the plan,
     then re-runs the original check to verify.

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
from pathlib import Path

import yaml

REPO_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = REPO_DIR / "etc" / "willflix-remediation.conf"
LOG_FILE = REPO_DIR / "log" / "willflix-remediate.log"
CRON_DIR = REPO_DIR / "bin" / "cron"
AGENTS_MD = REPO_DIR / "AGENTS.md"

# Absolute path — avoids shell alias `claude --dangerously-skip-permissions`
CLAUDE_BIN = "/home/will/.local/bin/claude"

LLM_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", 120))
VERIFY_TIMEOUT = 300
CMD_TIMEOUT = 60


def _get_claude_env() -> dict:
    """Return env dict for the Claude subprocess.

    Cron has a minimal environment. /etc/environment holds ANTHROPIC_API_KEY
    at the system level but cron doesn't source it automatically.
    """
    env = os.environ.copy()
    if "ANTHROPIC_API_KEY" not in env:
        try:
            with open("/etc/environment") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            pass
    return env


def setup_logging(script_name: str) -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("willflix-remediate")
    logger.setLevel(logging.DEBUG)
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


def build_prompt(risk: str, goal: str, findings: str, allowed_tools: list[str]) -> str:
    """Build the planning prompt for Claude."""
    agents_context = ""
    if AGENTS_MD.exists():
        agents_context = AGENTS_MD.read_text()

    instructions = {
        "low": (
            "Plan commands to fix the issue. Choose only from the ALLOWED COMMANDS list. "
            "Include them in your JSON summary."
        ),
        "medium": (
            "Plan commands to attempt a fix. Choose only from the ALLOWED COMMANDS list. "
            "This alert will always be sent regardless of outcome."
        ),
        "high": (
            "Diagnose only — do NOT suggest any commands that make changes. "
            "Use your knowledge and the findings to provide a clear diagnosis."
        ),
    }[risk]

    # Strip Bash(...) wrapper for display
    def _display(t: str) -> str:
        if t.startswith("Bash(") and t.endswith(")"):
            return t[5:-1]
        return t

    allowed_list = "\n".join(f"  - {_display(t)}" for t in allowed_tools)

    return f"""You are an automated remediation planner for the Willflix server (lafayette).
You analyse findings and produce a fix plan. You do NOT run commands yourself.

SYSTEM CONTEXT:
{agents_context}

RISK LEVEL: {risk.upper()}
{instructions}

GOAL: {goal}

ALLOWED COMMANDS (suggest ONLY exact commands that match these patterns):
{allowed_list or "  (none — diagnose only)"}

FINDINGS:
{findings}

Respond with a brief analysis, then end your response with EXACTLY ONE JSON object on its own line:
{{"commands": [{{"cmd": "exact shell command", "reason": "why"}}], "diagnosis": "root cause", "recommendation": "next steps"}}

For HIGH risk or when no fix is possible: use an empty commands array [].
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


def _normalize_cmd(cmd: str) -> str:
    """Strip surrounding quotes from URL arguments for allowlist matching.

    Claude often quotes URLs ('http://...' or "http://...") but allowlist
    patterns are written without quotes. Normalise before comparing.
    Execution always uses the original quoted command — this is matching only.
    """
    import re
    cmd = re.sub(r'"(https?://[^"]*)"', r'\1', cmd)
    cmd = re.sub(r"'(https?://[^']*)'", r'\1', cmd)
    return cmd


def is_command_allowed(cmd: str, allowed_tools: list[str]) -> bool:
    """Check if a command matches any entry in the allowlist.

    Allowlist entries may be bare commands or Bash(...) wrapped patterns.
    Patterns are matched using fnmatch glob rules: * matches any sequence
    of characters including spaces, so patterns like
    "curl * http://localhost:8989/api/v3/queue*" match any curl command
    with any flags going to that endpoint, regardless of flag order.

    Commands containing <placeholder> markers or shell metacharacters
    are always rejected.
    """
    import fnmatch
    import re

    cmd = cmd.strip()

    # Reject unfilled template placeholders (e.g. <ID_FROM_ABOVE>)
    if re.search(r'<[^>]+>', cmd):
        return False

    # Reject dangerous shell metacharacters (pipe, semicolon, backtick, subshell,
    # shell AND/OR operators, path traversal).
    # Single & is allowed: appears in URL query strings (?a=1&b=2).
    if re.search(r'[|;`]|\$\(|\.\.|&&|\|\|', cmd):
        return False

    normalized = _normalize_cmd(cmd)

    for pattern in allowed_tools:
        p = pattern.strip()
        if p.startswith("Bash(") and p.endswith(")"):
            p = p[5:-1]
        if fnmatch.fnmatch(normalized, p):
            return True
    return False


def execute_plan(commands: list[dict], allowed_tools: list[str], logger: logging.Logger) -> bool:
    """Execute validated commands from Claude's plan. Returns True if any ran."""
    if not commands:
        return False
    ran_any = False
    for item in commands:
        cmd = item.get("cmd", "").strip()
        reason = item.get("reason", "")
        if not cmd:
            continue
        if not is_command_allowed(cmd, allowed_tools):
            logger.warning("Skipping (not in allowlist): %s", cmd)
            continue
        logger.info("Running [reason: %s]: %s", reason, cmd)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=CMD_TIMEOUT
            )
            logger.info("  exit=%d stdout=%s", result.returncode, result.stdout[:300])
            if result.stderr:
                logger.info("  stderr=%s", result.stderr[:200])
            ran_any = True
        except subprocess.TimeoutExpired:
            logger.error("  timed out after %ds: %s", CMD_TIMEOUT, cmd)
        except Exception as e:
            logger.error("  failed: %s: %s", cmd, e)
    return ran_any


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
    # Recursion guard: verification re-runs the original script, which would
    # call willflix-remediate again. Break the cycle by refusing re-entry.
    if os.environ.get("WILLFLIX_REMEDIATE_ACTIVE"):
        sys.exit(1)
    os.environ["WILLFLIX_REMEDIATE_ACTIVE"] = "1"

    logger = setup_logging(script_name)

    config = load_config(script_name)
    if not config:
        logger.error("No remediation config for script: %s", script_name)
        return 1

    risk = config["risk"]
    goal = config["goal"]
    allowed_tools = config.get("allowed_tools", [])
    verify_cmd = verify_cmd_override or config.get("verify_cmd")

    # High-risk: only read-only commands allowed regardless of config
    if risk == "high":
        allowed_tools = [t for t in allowed_tools
                         if any(t.startswith(safe) for safe in (
                             "Bash(df ", "Bash(dmesg", "Bash(cat ", "Bash(sudo smartctl",
                             "Bash(sudo snapraid status)", "Bash(mountpoint",
                             "Read", "Glob", "Grep",
                         ))]

    prompt = build_prompt(risk, goal, findings, allowed_tools)
    logger.info("Starting: risk=%s tools=%d", risk, len(allowed_tools))

    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--bare", "--print", "-p", prompt],
            stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=LLM_TIMEOUT,
            env=_get_claude_env(),
        )
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        logger.error("Claude call timed out after %ds", LLM_TIMEOUT)
        return 1
    except Exception as e:
        logger.error("Claude call failed: %s", e)
        return 1

    logger.info("Claude output:\n%s", output)

    # High risk: always print diagnosis, never suppress
    if risk == "high":
        print(output)
        return 1

    plan = parse_summary(output)
    commands = plan.get("commands", [])
    logger.info("Plan: %d commands, diagnosis: %s", len(commands), plan.get("diagnosis", ""))

    if commands:
        ran_any = execute_plan(commands, allowed_tools, logger)
        if ran_any and verify(script_name, verify_cmd):
            logger.info("VERIFIED FIXED: %s", [c.get("cmd") for c in commands])
            return 0
        if ran_any:
            logger.warning("Commands ran but verification failed")
        else:
            logger.warning("All %d planned commands were outside the allowlist", len(commands))

    # Print output so callers can append to alert body
    print(output)
    return 1


def main():
    parser = argparse.ArgumentParser(
        description="LLM-assisted auto-remediation for cron alerts."
    )
    parser.add_argument("--script", required=True)
    parser.add_argument("--findings", required=True)
    parser.add_argument("--verify-cmd", default=None)
    args = parser.parse_args()
    sys.exit(run(args.script, args.findings, args.verify_cmd))


if __name__ == "__main__":
    main()
