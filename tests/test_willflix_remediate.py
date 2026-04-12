"""Tests for willflix-remediate pure functions."""
import textwrap
from pathlib import Path

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
        I'll restart sonarr to clear the stuck queue.
        {"commands": [{"cmd": "docker compose restart sonarr", "reason": "stuck"}], "diagnosis": "queue stuck", "recommendation": "monitor"}
    """)
    result = parse_summary(output)
    assert result["commands"][0]["cmd"] == "docker compose restart sonarr"
    assert result["diagnosis"] == "queue stuck"


def test_parse_summary_empty_commands():
    from bin.willflix_remediate import parse_summary
    output = 'Analysis done.\n{"commands": [], "diagnosis": "unknown error", "recommendation": "check logs"}'
    result = parse_summary(output)
    assert result["commands"] == []


def test_parse_summary_returns_empty_on_no_json():
    from bin.willflix_remediate import parse_summary
    assert parse_summary("No JSON here at all.") == {}


def test_parse_summary_ignores_mid_output_json():
    from bin.willflix_remediate import parse_summary
    output = 'See {"not": "summary"} for details.\n{"commands": [], "diagnosis": "ok", "recommendation": ""}'
    result = parse_summary(output)
    assert "commands" in result
    assert result["diagnosis"] == "ok"


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_contains_risk_and_goal(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", tmp_path / "AGENTS.md")
    result = build_prompt("low", "Fix stuck queue items", "sonarr queue has 3 failed items", [])
    assert "LOW" in result
    assert "Fix stuck queue items" in result
    assert "sonarr queue has 3 failed items" in result


def test_build_prompt_high_risk_says_diagnose_only(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", tmp_path / "AGENTS.md")
    result = build_prompt("high", "Diagnose drive failure", "MediaA not mounted", [])
    assert "diagnose" in result.lower()
    assert "do not" in result.lower()


def test_build_prompt_includes_agents_md_when_present(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# System context for tests")
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", agents)
    result = build_prompt("medium", "goal", "findings", [])
    assert "System context for tests" in result


def test_build_prompt_includes_allowed_tools(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", tmp_path / "AGENTS.md")
    tools = ["Bash(docker compose restart sonarr)", "Bash(docker compose restart radarr)"]
    result = build_prompt("low", "goal", "findings", tools)
    assert "docker compose restart sonarr" in result
    assert "docker compose restart radarr" in result


# ── is_command_allowed ────────────────────────────────────────────────────────

def test_is_command_allowed_exact_match():
    from bin.willflix_remediate import is_command_allowed
    tools = ["Bash(docker compose -f /willflix/docker/compose.yml restart sonarr)"]
    assert is_command_allowed(
        "docker compose -f /willflix/docker/compose.yml restart sonarr", tools
    )


def test_is_command_allowed_wildcard_match():
    from bin.willflix_remediate import is_command_allowed
    tools = ["Bash(docker compose -f /willflix/docker/compose.yml restart *)"]
    assert is_command_allowed(
        "docker compose -f /willflix/docker/compose.yml restart radarr", tools
    )
    assert is_command_allowed(
        "docker compose -f /willflix/docker/compose.yml restart sonarr", tools
    )


def test_is_command_allowed_rejects_unlisted():
    from bin.willflix_remediate import is_command_allowed
    tools = ["Bash(docker compose -f /willflix/docker/compose.yml restart sonarr)"]
    assert not is_command_allowed("rm -rf /", tools)
    assert not is_command_allowed("docker compose down", tools)


def test_is_command_allowed_wildcard_does_not_overmatch():
    from bin.willflix_remediate import is_command_allowed
    tools = ["Bash(docker compose -f /willflix/docker/compose.yml restart *)"]
    assert not is_command_allowed("docker compose down sonarr", tools)
    assert not is_command_allowed("rm -rf / && docker compose restart sonarr", tools)


def test_is_command_allowed_bare_pattern():
    from bin.willflix_remediate import is_command_allowed
    tools = ["docker compose restart sonarr"]
    assert is_command_allowed("docker compose restart sonarr", tools)
    assert not is_command_allowed("docker compose restart radarr", tools)


def test_is_command_allowed_quoted_url():
    from bin.willflix_remediate import is_command_allowed
    # Claude quotes URLs; pattern doesn't — should still match after normalization
    tools = ["Bash(curl -s http://localhost:8989/api/v3/queue*)"]
    assert is_command_allowed(
        'curl -s "http://localhost:8989/api/v3/queue?page=1&pageSize=100"', tools
    )
    assert is_command_allowed(
        "curl -s 'http://localhost:8989/api/v3/queue?status=failed'", tools
    )


def test_is_command_allowed_rejects_placeholder():
    from bin.willflix_remediate import is_command_allowed
    # Template placeholders must never be executed
    tools = ["Bash(curl -s -X DELETE http://localhost:8989/api/v3/queue/*)"]
    assert not is_command_allowed(
        'curl -s -X DELETE "http://localhost:8989/api/v3/queue/<ID_FROM_ABOVE>"', tools
    )


def test_is_command_allowed_rejects_piped_command():
    from bin.willflix_remediate import is_command_allowed
    # Piped commands don't match URL-only patterns
    tools = ["Bash(curl -s http://localhost:8989/api/v3/queue*)"]
    assert not is_command_allowed(
        'curl -s "http://localhost:8989/api/v3/queue" | python3 -m json.tool', tools
    )
