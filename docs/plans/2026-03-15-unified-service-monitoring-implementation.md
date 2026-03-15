# Unified Service Monitoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the separate docker/systemd check scripts with a single unified service monitor driven by a YAML allowlist config with severity tiers.

**Architecture:** Single Python script (`bin/cron/willflix-check-services`) reads a YAML config (`etc/willflix-services.conf`), checks each service based on type (docker/systemd/both), and alerts via `willflix-notify` at the configured tier severity. Unknown services get low-priority INFO alerts with extended dedup. The `willflix-notify` script gains a `--dedup-window` flag.

**Tech Stack:** Python 3, PyYAML (already available on system), bash (willflix-notify changes)

---

### Task 1: Create the YAML service config

**Files:**
- Create: `etc/willflix-services.conf`

**Step 1: Write the config file**

```yaml
# willflix-services.conf — unified service monitoring allowlist.
# Used by bin/cron/willflix-check-services.
#
# type: docker | systemd | both
# tier: critical | warning | info | ignore
#
# Optional:
#   systemd: <unit-name>   (override when unit name differs from <name>.service)

services:
  # --- critical: pushover emergency ---
  traefik:
    type: docker
    tier: critical
  authentik-server:
    type: docker
    tier: critical
  authentik-worker:
    type: docker
    tier: critical
  smtp-relay:
    type: docker
    tier: critical
  plex:
    type: docker
    tier: critical

  # --- warning: pushover normal ---
  ddclient:
    type: docker
    tier: warning
  vpn:
    type: docker
    tier: warning
  qbittorrent:
    type: docker
    tier: warning
  plex-autoscan:
    type: docker
    tier: warning
  nzbget:
    type: docker
    tier: warning
  sonarr:
    type: docker
    tier: warning
  radarr:
    type: docker
    tier: warning
  lidarr:
    type: docker
    tier: warning
  prowlarr:
    type: docker
    tier: warning
  calibre-web-automated:
    type: docker
    tier: warning
  shelfmark:
    type: docker
    tier: warning
  jdownloader:
    type: docker
    tier: warning
  audiobookshelf:
    type: docker
    tier: warning
  openclaw-node:
    type: docker
    tier: warning
  redis:
    type: docker
    tier: warning
  postgres:
    type: docker
    tier: warning

  # --- info: email only ---
  healthbot:
    type: docker
    tier: info
  nextcloud:
    type: docker
    tier: info
  nginx-public:
    type: docker
    tier: info
  nginx-private:
    type: docker
    tier: info
  tautulli:
    type: docker
    tier: info
  samba:
    type: docker
    tier: info
  health-server:
    type: docker
    tier: info

  # --- ignore: documented but not checked ---
  calibre:
    type: docker
    tier: ignore
  whoami:
    type: docker
    tier: ignore
  adminer:
    type: docker
    tier: ignore
  webhook-handler:
    type: docker
    tier: ignore
  lazylibrarian:
    type: docker
    tier: ignore
  homarr:
    type: docker
    tier: ignore
  grocerybot:
    type: docker
    tier: ignore
  homebot:
    type: docker
    tier: ignore
  gastown:
    type: docker
    tier: ignore
  guildmaster:
    type: docker
    tier: ignore
  overseerr:
    type: docker
    tier: ignore
  copyparty:
    type: docker
    tier: ignore
  byparr:
    type: docker
    tier: ignore
```

**Step 2: Commit**

```bash
git add etc/willflix-services.conf
git commit -m "Add unified service monitoring config (willflix-services.conf)"
```

---

### Task 2: Add `--dedup-window` to `willflix-notify`

**Files:**
- Modify: `bin/willflix-notify` (lines 24-117, dedup logic)

**Step 1: Add the `--dedup-window` argument parsing**

In the arg parsing block (after the `--body` case, around line 37), add:

```bash
        --dedup-window) DEDUP_WINDOW_OVERRIDE="$2"; shift 2 ;;
```

Initialize `DEDUP_WINDOW_OVERRIDE=""` with the other vars near line 24.

**Step 2: Add duration-to-seconds helper function**

After the `last_reset_epoch` function (after line 94), add:

```bash
# Convert duration string (e.g. "3d", "12h", "1w") to seconds.
parse_duration() {
    local input="$1"
    local num="${input%[dhwm]}"
    local unit="${input##*[0-9]}"
    case "$unit" in
        m) echo $(( num * 60 )) ;;
        h) echo $(( num * 3600 )) ;;
        d) echo $(( num * 86400 )) ;;
        w) echo $(( num * 604800 )) ;;
        *) echo "$num" ;;  # assume seconds
    esac
}
```

**Step 3: Modify `is_deduped` to use the override window**

Replace the `is_deduped` function with:

```bash
is_deduped() {
    [[ "$TEST_MODE" == "true" ]] && return 1  # --test bypasses dedup

    local keyfile="${DEDUP_DIR}/${KEY}"
    if [[ -f "$keyfile" ]]; then
        local sent_at age
        sent_at=$(stat -c %Y "$keyfile")
        age=$(( $(date +%s) - sent_at ))

        if [[ -n "$DEDUP_WINDOW_OVERRIDE" ]]; then
            # Fixed window: suppress if sent less than N seconds ago
            local window
            window=$(parse_duration "$DEDUP_WINDOW_OVERRIDE")
            if [[ "$age" -lt "$window" ]]; then
                return 0  # suppress
            fi
        else
            # Default: daily reset boundary
            local reset_boundary
            reset_boundary=$(last_reset_epoch)
            if [[ "$sent_at" -ge "$reset_boundary" && "$age" -lt "$DEDUP_MAX_WINDOW" ]]; then
                return 0  # suppress
            fi
        fi
    fi
    return 1  # not deduped, send it
}
```

**Step 4: Test manually**

```bash
# Test that normal dedup still works (should send first, suppress second)
/willflix/bin/willflix-notify --severity INFO --key "test-dedup-normal" \
    --subject "Test normal dedup" --body "test"
/willflix/bin/willflix-notify --severity INFO --key "test-dedup-normal" \
    --subject "Test normal dedup" --body "test"
# Second call should log DEDUP in syslog

# Test that --dedup-window works (1-second window, wait, should send again)
/willflix/bin/willflix-notify --severity INFO --key "test-dedup-window" \
    --dedup-window 1s --subject "Test window dedup" --body "test"
sleep 2
/willflix/bin/willflix-notify --severity INFO --key "test-dedup-window" \
    --dedup-window 1s --subject "Test window dedup" --body "test"
# Second call should send (window expired)

# Clean up test dedup files
rm -f /var/tmp/willflix-notify/test-dedup-*
```

**Step 5: Commit**

```bash
git add bin/willflix-notify
git commit -m "Add --dedup-window flag to willflix-notify for extended suppression"
```

---

### Task 3: Write the unified check script

**Files:**
- Create: `bin/cron/willflix-check-services`

**Step 1: Write the script**

```python
#!/usr/bin/env python3
"""willflix-check-services — unified service health monitor.

Reads etc/willflix-services.conf and checks each service based on type
(docker/systemd/both) and alerts at the configured tier severity.

Replaces willflix-check-docker and willflix-check-systemd.
"""

import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_DIR = Path(__file__).resolve().parents[2]
CONFIG_FILE = REPO_DIR / "etc" / "willflix-services.conf"
NOTIFY_BIN = REPO_DIR / "bin" / "willflix-notify"
MONITOR_STAMP = Path("/var/tmp/willflix-monitors/willflix-check-services")
HOSTNAME = subprocess.check_output(["hostname"], text=True).strip()

TIER_SEVERITY = {
    "critical": "CRITICAL",
    "warning": "WARNING",
    "info": "INFO",
}


def load_config():
    """Load and validate the service config."""
    with open(CONFIG_FILE) as f:
        data = yaml.safe_load(f)
    return data.get("services", {})


def get_docker_containers():
    """Return dict of {container_name: status_string} for all containers."""
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
        capture_output=True, text=True, timeout=30,
    )
    containers = {}
    for line in result.stdout.strip().splitlines():
        if "\t" in line:
            name, status = line.split("\t", 1)
            containers[name] = status
    return containers


def match_container(service_name, containers):
    """Find a container matching service_name.

    Matches exactly 'service_name' or '<prefix>-service_name-<digits>'.
    Returns (container_name, status) or (None, None).
    """
    # Exact match first
    if service_name in containers:
        return service_name, containers[service_name]

    # Pattern match: <prefix>-<name>-<digits>
    pattern = re.compile(r"^.+-" + re.escape(service_name) + r"-\d+$")
    for cname, status in containers.items():
        if pattern.match(cname):
            return cname, status

    return None, None


def check_systemd_unit(unit_name):
    """Check if a systemd unit is active. Returns (is_active, status_text)."""
    result = subprocess.run(
        ["systemctl", "is-active", unit_name],
        capture_output=True, text=True,
    )
    status = result.stdout.strip()
    return status == "active", status


def notify(severity, key, subject, body, dedup_window=None):
    """Send alert via willflix-notify."""
    cmd = [
        str(NOTIFY_BIN),
        "--severity", severity,
        "--key", key,
        "--subject", subject,
        "--body", body,
    ]
    if dedup_window:
        cmd.extend(["--dedup-window", dedup_window])
    subprocess.run(cmd, check=False)


def check_docker_service(service_name, tier, containers):
    """Check a docker service. Returns list of issues."""
    severity = TIER_SEVERITY[tier]
    cname, status = match_container(service_name, containers)

    if cname is None:
        notify(severity, f"svc-missing-{service_name}",
               f"Service: {service_name} not found on {HOSTNAME}",
               f"No container matching '{service_name}' exists.\n\n"
               f"Check:\n  cd /willflix/docker && docker compose ps {service_name}\n"
               f"  docker compose up -d {service_name}")
        return [f"{service_name}: container not found"]

    if status.startswith("Restarting"):
        # Crash loops are always CRITICAL regardless of tier
        notify("CRITICAL", f"svc-crashloop-{service_name}",
               f"Service: {service_name} crash-looping on {HOSTNAME}",
               f"Container '{cname}' is restarting (crash loop).\n"
               f"Status: {status}\n\n"
               f"Check:\n  docker logs {cname} --tail 30")
        return [f"{service_name}: crash-looping"]

    if not status.startswith("Up"):
        notify(severity, f"svc-down-{service_name}",
               f"Service: {service_name} not running on {HOSTNAME}",
               f"Container '{cname}' is not running.\n"
               f"Status: {status}\n\n"
               f"Check:\n  docker logs {cname} --tail 30\n"
               f"  cd /willflix/docker && docker compose up -d {service_name}")
        return [f"{service_name}: not running ({status})"]

    if "(unhealthy)" in status:
        notify(severity, f"svc-unhealthy-{service_name}",
               f"Service: {service_name} unhealthy on {HOSTNAME}",
               f"Container '{cname}' is running but failing its healthcheck.\n"
               f"Status: {status}\n\n"
               f"Check:\n  docker inspect {cname} --format '{{{{json .State.Health}}}}' | python3 -m json.tool\n"
               f"  docker logs {cname} --tail 30")
        return [f"{service_name}: unhealthy"]

    return []


def check_systemd_service(service_name, tier, unit_override=None):
    """Check a systemd service. Returns list of issues."""
    severity = TIER_SEVERITY[tier]
    unit = unit_override or f"{service_name}.service"
    is_active, status = check_systemd_unit(unit)

    if not is_active:
        notify(severity, f"svc-systemd-{service_name}",
               f"Service: {unit} not active on {HOSTNAME}",
               f"Systemd unit '{unit}' is {status}.\n\n"
               f"Check:\n  systemctl status {unit}\n"
               f"  journalctl -u {unit} --no-pager -n 30")
        return [f"{service_name}: systemd {status}"]

    return []


def check_unknown_containers(services, containers):
    """Alert on containers not matched by any config entry."""
    # Build set of all container names claimed by config
    matched_names = set()
    for svc_name in services:
        cname, _ = match_container(svc_name, containers)
        if cname:
            matched_names.add(cname)

    for cname, status in containers.items():
        if cname in matched_names:
            continue
        # Only alert on containers that are running or crash-looping
        # (stopped unknown containers are not interesting)
        if status.startswith("Up") or status.startswith("Restarting"):
            notify("INFO", f"svc-unknown-container-{cname}",
                   f"Unknown container: {cname} on {HOSTNAME}",
                   f"Container '{cname}' is running but not listed in willflix-services.conf.\n"
                   f"Status: {status}\n\n"
                   f"Add it to etc/willflix-services.conf to monitor it,\n"
                   f"or add it with 'tier: ignore' to suppress this alert.",
                   dedup_window="3d")


def check_unknown_systemd(services):
    """Alert on failed systemd units not matched by any config entry."""
    result = subprocess.run(
        ["systemctl", "--failed", "--no-legend"],
        capture_output=True, text=True,
    )
    # Collect known systemd unit names from config
    known_units = set()
    for svc_name, svc_cfg in services.items():
        svc_type = svc_cfg.get("type", "docker")
        if svc_type in ("systemd", "both"):
            unit = svc_cfg.get("systemd", f"{svc_name}.service")
            known_units.add(unit)

    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        # Format: "● unit.service loaded failed failed Description..."
        parts = line.split()
        if len(parts) < 2:
            continue
        unit = parts[1]
        if unit in known_units:
            continue
        notify("INFO", f"svc-unknown-systemd-{unit}",
               f"Unknown failed unit: {unit} on {HOSTNAME}",
               f"Systemd unit '{unit}' is in failed state but not in willflix-services.conf.\n\n"
               f"Check:\n  systemctl status {unit}\n"
               f"  journalctl -u {unit} --no-pager -n 30\n\n"
               f"Add it to etc/willflix-services.conf to monitor it,\n"
               f"or add it with 'tier: ignore' to suppress this alert.",
               dedup_window="3d")


def main():
    services = load_config()
    containers = get_docker_containers()
    issues = []

    for svc_name, svc_cfg in services.items():
        tier = svc_cfg.get("tier", "warning")
        svc_type = svc_cfg.get("type", "docker")

        if tier == "ignore":
            continue

        if tier not in TIER_SEVERITY:
            print(f"Unknown tier '{tier}' for service '{svc_name}', skipping", file=sys.stderr)
            continue

        if svc_type in ("docker", "both"):
            issues.extend(check_docker_service(svc_name, tier, containers))

        if svc_type in ("systemd", "both"):
            unit_override = svc_cfg.get("systemd")
            issues.extend(check_systemd_service(svc_name, tier, unit_override))

    # Check for unknown services
    check_unknown_containers(services, containers)
    check_unknown_systemd(services)

    # Summary to stdout (for cron email)
    if issues:
        print(f"willflix-check-services: {len(issues)} issue(s) found")
        for issue in issues:
            print(f"  - {issue}")

    # Touch freshness stamp
    MONITOR_STAMP.parent.mkdir(parents=True, exist_ok=True)
    MONITOR_STAMP.touch()


if __name__ == "__main__":
    main()
```

**Step 2: Make it executable**

```bash
chmod +x bin/cron/willflix-check-services
```

**Step 3: Dry run (inspect output without sending alerts)**

Temporarily test by reading the config and checking container matching logic:

```bash
cd /willflix && python3 -c "
import yaml, re, subprocess
with open('etc/willflix-services.conf') as f:
    services = yaml.safe_load(f).get('services', {})
result = subprocess.run(['docker', 'ps', '-a', '--format', '{{.Names}}\t{{.Status}}'],
                        capture_output=True, text=True)
containers = {}
for line in result.stdout.strip().splitlines():
    if '\t' in line:
        name, status = line.split('\t', 1)
        containers[name] = status

for svc_name, cfg in services.items():
    if cfg.get('tier') == 'ignore':
        continue
    if cfg.get('type', 'docker') in ('docker', 'both'):
        # Try exact match
        if svc_name in containers:
            print(f'  {svc_name} -> {svc_name}: {containers[svc_name]}')
            continue
        # Try pattern match
        pattern = re.compile(r'^.+-' + re.escape(svc_name) + r'-\d+$')
        found = False
        for cname, status in containers.items():
            if pattern.match(cname):
                print(f'  {svc_name} -> {cname}: {status}')
                found = True
                break
        if not found:
            print(f'  {svc_name} -> NOT FOUND')
"
```

Verify every configured service resolves to a container. Fix any mismatches before proceeding.

**Step 4: Commit**

```bash
git add bin/cron/willflix-check-services
git commit -m "Add unified service check script (willflix-check-services)"
```

---

### Task 4: Update cron, heartbeat, and AGENTS.md

**Files:**
- Modify: `etc/root-crontab` (lines 17-19)
- Modify: `bin/cron/willflix-heartbeat` (lines 43-44)
- Modify: `etc/AGENTS.md` (lines 14-15)

**Step 1: Update root-crontab**

Replace lines 17-19:
```
# Service health checks (every 15 min)
*/15 * * * * /willflix/bin/cron/willflix-check-docker
*/15 * * * * /willflix/bin/cron/willflix-check-systemd
```

With:
```
# Service health checks (every 15 min)
*/15 * * * * /willflix/bin/cron/willflix-check-services
```

**Step 2: Update heartbeat monitors**

In `bin/cron/willflix-heartbeat`, replace lines 43-44:
```bash
    "willflix-check-docker 45"
    "willflix-check-systemd 45"
```

With:
```bash
    "willflix-check-services 45"
```

**Step 3: Update AGENTS.md**

Replace lines 14-15:
```
| `willflix-check-docker.ignore` | Read by `bin/cron/willflix-check-docker` | Direct (same path) |
| `willflix-check-systemd.ignore` | Read by `bin/cron/willflix-check-systemd` | Direct (same path) |
```

With:
```
| `willflix-services.conf` | Read by `bin/cron/willflix-check-services` | Direct (same path) |
```

**Step 4: Commit**

```bash
git add etc/root-crontab bin/cron/willflix-heartbeat etc/AGENTS.md
git commit -m "Update cron, heartbeat, and AGENTS.md for unified service check"
```

---

### Task 5: Delete old scripts and ignore files

**Files:**
- Delete: `bin/cron/willflix-check-docker`
- Delete: `bin/cron/willflix-check-systemd`
- Delete: `etc/willflix-check-docker.ignore`
- Delete: `etc/willflix-check-systemd.ignore`

**Step 1: Remove old files**

```bash
git rm bin/cron/willflix-check-docker bin/cron/willflix-check-systemd
git rm etc/willflix-check-docker.ignore etc/willflix-check-systemd.ignore
```

**Step 2: Commit**

```bash
git commit -m "Remove old docker/systemd check scripts and ignore files"
```

---

### Task 6: One-time cleanup of ignored services

This is a one-time manual action, not part of the script.

**Step 1: Stop docker containers for ignored services**

```bash
cd /willflix/docker
docker compose stop calibre whoami adminer webhook-handler lazylibrarian homarr grocerybot homebot gastown guildmaster overseerr copyparty byparr
```

**Step 2: Disable systemd units that exist**

From our discovery, these ignored services have systemd units:
- enabled: calibre, adminer, webhook-handler, homarr, gastown, guildmaster, overseerr, copyparty, byparr
- linked: homebot

```bash
sudo systemctl disable calibre.service adminer.service webhook-handler.service homarr.service gastown.service guildmaster.service overseerr.service copyparty.service byparr.service homebot.service
sudo systemctl stop calibre.service adminer.service webhook-handler.service homarr.service gastown.service guildmaster.service overseerr.service copyparty.service byparr.service homebot.service
```

**Step 3: Verify**

```bash
# Verify containers are stopped
docker ps --format '{{.Names}}' | grep -E 'calibre$|whoami|adminer|webhook-handler|lazylibrarian|homarr|grocerybot|homebot|gastown|guildmaster|overseerr|copyparty|byparr' && echo "STILL RUNNING" || echo "All stopped"

# Verify systemd units are disabled
for svc in calibre adminer webhook-handler homarr gastown guildmaster overseerr copyparty byparr homebot; do
    echo "$svc: $(systemctl is-enabled $svc.service 2>/dev/null || echo 'not-found')"
done
```

No git commit for this task — it's runtime state, not repo changes.

---

### Task 7: Deploy and verify

**Step 1: Install root crontab**

```bash
sudo crontab /willflix/etc/root-crontab
sudo crontab -l  # verify
```

**Step 2: Run the new script manually**

```bash
/willflix/bin/cron/willflix-check-services
```

Verify:
- No errors on stderr
- Freshness stamp updated: `stat /var/tmp/willflix-monitors/willflix-check-services`
- Check syslog for any alerts: `journalctl -t willflix-notify --since "5 min ago" --no-pager`

**Step 3: Clean up old freshness stamps**

```bash
rm -f /var/tmp/willflix-monitors/willflix-check-docker
rm -f /var/tmp/willflix-monitors/willflix-check-systemd
```

**Step 4: Wait 15 minutes, verify cron execution**

```bash
# After 15 min, check the stamp was refreshed
stat /var/tmp/willflix-monitors/willflix-check-services
# Check syslog for the cron run
journalctl -t CRON --since "20 min ago" --no-pager | grep willflix-check-services
```
