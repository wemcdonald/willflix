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
    output = 'See {"not": "summary"} for details.\n{"fixed": true, "actions_taken": [], "diagnosis": "ok", "recommendation": ""}'
    result = parse_summary(output)
    assert result["fixed"] is True


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_contains_risk_and_goal(tmp_path, monkeypatch):
    from bin.willflix_remediate import build_prompt
    monkeypatch.setattr("bin.willflix_remediate.AGENTS_MD", tmp_path / "AGENTS.md")
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
