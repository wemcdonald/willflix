"""Load willflix configuration from shell-style config files and secrets."""

import os
from pathlib import Path

REPO_DIR = Path("/willflix")
CONFIG_FILE = REPO_DIR / "etc" / "willflix-notify.config"
HOME_CONFIG = Path.home() / ".config" / "willflix-notify" / "config"
SECRETS_DIR = REPO_DIR / "secrets"


def load_config() -> dict:
    """Load config from repo default, then overlay home-dir overrides."""
    cfg = {}
    for path in [CONFIG_FILE, HOME_CONFIG]:
        if path.exists():
            cfg.update(_parse_shell_config(path))
    return cfg


def _parse_shell_config(path: Path) -> dict:
    """Parse KEY=VALUE lines from a shell config file."""
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip inline comments (but not inside quotes)
        if value and value[0] in ('"', "'"):
            quote = value[0]
            end = value.find(quote, 1)
            if end > 0:
                value = value[1:end]
        else:
            # Strip inline comment
            if "  #" in value:
                value = value[:value.index("  #")]
            elif "\t#" in value:
                value = value[:value.index("\t#")]
            value = value.strip()
        result[key] = value
    return result


def read_secret(name: str) -> str:
    """Read a secret file by name."""
    path = SECRETS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Secret not found: {path}")
    return path.read_text().strip()


def get(key: str, default: str = "") -> str:
    """Get a config value with optional default."""
    return load_config().get(key, default)
