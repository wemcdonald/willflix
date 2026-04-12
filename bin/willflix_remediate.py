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

LLM_TIMEOUT = int(os.environ.get("CLAUDE_TIMEOUT", 120))  # env override for testing
VERIFY_TIMEOUT = 300


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


def build_prompt(risk: str, goal: str, findings: str) -> str:
    """Build the prompt for Claude."""
    agents_context = ""
    if AGENTS_MD.exists():
        agents_context = AGENTS_MD.read_text()

    instructions = {
        "low": (
            "Attempt to fix the issue using your allowed tools. "
            'If successful, output {"fixed": true} in your summary.'
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
    # High-risk: enforce read-only by removing any tools not explicitly safe.
    # Config should only list read-only commands for high-risk scripts, but
    # we enforce it in code as a safety net.
    if risk == "high":
        allowed_tools = [t for t in allowed_tools
                         if any(t.startswith(safe) for safe in (
                             "Bash(df ", "Bash(dmesg", "Bash(cat ", "Bash(sudo smartctl",
                             "Bash(sudo snapraid status)", "Bash(mountpoint",
                             "Read", "Glob", "Grep",
                         ))]
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
    parser.add_argument("--script", required=True)
    parser.add_argument("--findings", required=True)
    parser.add_argument("--verify-cmd", default=None)
    args = parser.parse_args()
    sys.exit(run(args.script, args.findings, args.verify_cmd))


if __name__ == "__main__":
    main()
