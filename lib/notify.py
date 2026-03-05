"""Python wrapper around willflix-notify."""

import subprocess
from pathlib import Path

NOTIFY_BIN = Path("/willflix/bin/willflix-notify")


def send(severity: str, key: str, subject: str, body: str) -> bool:
    """Send a notification via willflix-notify.

    Returns True if the notification was sent (or suppressed by dedup).
    Returns False if sending failed.
    """
    try:
        subprocess.run(
            [str(NOTIFY_BIN),
             "--severity", severity,
             "--key", key,
             "--subject", subject,
             "--body", body],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False
