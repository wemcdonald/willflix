# Phase 2a: Comprehensive Monitoring — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Docker container health monitoring, systemd unit monitoring, and backup freshness monitoring — all as independent cron scripts using willflix-notify.

**Architecture:** Three independent bash scripts with config files. Docker check auto-discovers services from compose. Systemd and backup checks use config-driven ignore/threshold files. All touch freshness stamps for heartbeat monitoring.

**Tech Stack:** Bash, docker ps, systemctl, python3 (YAML parsing for compose), willflix-notify

**Design doc:** `docs/plans/2026-03-04-phase2a-monitoring-design.md`

---

### Task 1: Docker ignore list config

**Files:**
- Create: `etc/willflix-check-docker.ignore`

**Step 1: Create the ignore file**

```
# Containers to ignore in health checks.
# One container name per line. Comments start with #.
# These are intentionally stopped or known-problematic.
whoami
confident_agnesi
```

`whoami` is a Traefik test container (exited 3 months ago). `confident_agnesi` appears to be a stray container.

**Step 2: Commit**

```bash
git add etc/willflix-check-docker.ignore
git commit -m "Add Docker health check ignore list"
```

---

### Task 2: willflix-check-docker

**Files:**
- Create: `bin/cron/willflix-check-docker`

**Step 1: Write the script**

```bash
#!/bin/bash
# willflix-check-docker — monitor Docker container health.
# Auto-discovers expected services from docker-compose.yml.
# Detects: not running, unhealthy, crash-looping containers.
# Run every 15 minutes via cron.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"
MONITOR_STAMP="/var/tmp/willflix-monitors/willflix-check-docker"
COMPOSE_FILE="/docker/config/docker-compose.yml"
IGNORE_FILE="$(cd "$SCRIPT_DIR/../../etc" && pwd)/willflix-check-docker.ignore"

# --- Load ignore list ---

declare -A IGNORED
if [[ -f "$IGNORE_FILE" ]]; then
    while IFS= read -r line; do
        line="${line%%#*}"       # strip comments
        line="${line// /}"       # strip whitespace
        [[ -n "$line" ]] && IGNORED["$line"]=1
    done < "$IGNORE_FILE"
fi

is_ignored() {
    [[ -n "${IGNORED[$1]:-}" ]]
}

# --- Discover expected containers from compose ---

# Extract service names and their container_name (if set) from compose YAML.
# Services without container_name get the default: config-<service>-1
get_expected_containers() {
    python3 -c "
import yaml, sys
with open('$COMPOSE_FILE') as f:
    data = yaml.safe_load(f)
for name, svc in data.get('services', {}).items():
    cname = svc.get('container_name', 'config-' + name + '-1')
    print(cname)
"
}

mapfile -t EXPECTED < <(get_expected_containers)

# --- Get current container states ---

# docker ps -a gives: name, status (e.g., "Up 2 hours", "Up 2 hours (healthy)", "Exited (0) 3 days ago", "Restarting (1) 2 seconds ago")
declare -A CONTAINER_STATUS
while IFS=$'\t' read -r name status; do
    CONTAINER_STATUS["$name"]="$status"
done < <(docker ps -a --format '{{.Names}}\t{{.Status}}')

# --- Check each expected container ---

for container in "${EXPECTED[@]}"; do
    is_ignored "$container" && continue

    status="${CONTAINER_STATUS[$container]:-}"

    if [[ -z "$status" ]]; then
        # Container doesn't exist at all
        "$NOTIFY" --severity CRITICAL --key "docker-stopped-${container}" \
            --subject "Docker: ${container} not found on $(hostname)" \
            --body "Expected container '${container}' does not exist.
It may have been removed or never started.

Check:
  cd /docker/config && docker compose ps ${container}
  docker compose up -d ${container}"
        continue
    fi

    if [[ "$status" == Restarting* ]]; then
        "$NOTIFY" --severity CRITICAL --key "docker-crashloop-${container}" \
            --subject "Docker: ${container} crash-looping on $(hostname)" \
            --body "Container '${container}' is restarting (crash loop).
Status: ${status}

Check logs:
  docker logs ${container} --tail 30"
        continue
    fi

    if [[ "$status" != Up* ]]; then
        # Exited, Created, Dead, etc.
        "$NOTIFY" --severity CRITICAL --key "docker-stopped-${container}" \
            --subject "Docker: ${container} not running on $(hostname)" \
            --body "Container '${container}' is not running.
Status: ${status}

Check:
  docker logs ${container} --tail 30
  cd /docker/config && docker compose up -d ${container}"
        continue
    fi

    # Container is Up — check if unhealthy
    if [[ "$status" == *"(unhealthy)"* ]]; then
        "$NOTIFY" --severity WARNING --key "docker-unhealthy-${container}" \
            --subject "Docker: ${container} unhealthy on $(hostname)" \
            --body "Container '${container}' is running but failing its healthcheck.
Status: ${status}

Check:
  docker inspect ${container} --format '{{json .State.Health}}' | python3 -m json.tool
  docker logs ${container} --tail 30"
    fi
done

# Touch freshness stamp
mkdir -p "$(dirname "$MONITOR_STAMP")"
touch "$MONITOR_STAMP"
```

**Step 2: Make executable and commit**

```bash
chmod +x bin/cron/willflix-check-docker
git add bin/cron/willflix-check-docker
git commit -m "Add willflix-check-docker container health monitor"
```

**Step 3: Test (will produce alerts for ofelia crash-loop and authentik-worker unhealthy)**

```bash
sudo bin/cron/willflix-check-docker
```

Expected: CRITICAL alert for ofelia (restarting), WARNING for authentik-worker (unhealthy). Verify with `journalctl -t willflix-notify --no-pager | tail -10`.

---

### Task 3: Systemd ignore list config

**Files:**
- Create: `etc/willflix-check-systemd.ignore`

**Step 1: Create the ignore file**

```
# Systemd units to ignore in health checks.
# One unit name per line. Comments start with #.
# These are known-legacy or expected failures.
certbot.service
courier-imap-ssl.service
mount-all.service
nginx.service
vncserver@1.service
Volumes-MediaJ.mount
```

**Step 2: Commit**

```bash
git add etc/willflix-check-systemd.ignore
git commit -m "Add systemd health check ignore list"
```

---

### Task 4: willflix-check-systemd

**Files:**
- Create: `bin/cron/willflix-check-systemd`

**Step 1: Write the script**

```bash
#!/bin/bash
# willflix-check-systemd — monitor for failed systemd units.
# Filters out known-legacy units from ignore list.
# Run every 15 minutes via cron.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"
MONITOR_STAMP="/var/tmp/willflix-monitors/willflix-check-systemd"
IGNORE_FILE="$(cd "$SCRIPT_DIR/../../etc" && pwd)/willflix-check-systemd.ignore"

# --- Load ignore list ---

declare -A IGNORED
if [[ -f "$IGNORE_FILE" ]]; then
    while IFS= read -r line; do
        line="${line%%#*}"
        line="${line// /}"
        [[ -n "$line" ]] && IGNORED["$line"]=1
    done < "$IGNORE_FILE"
fi

# --- Check for failed units ---

while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    # Format: "unit.service loaded failed failed Description..."
    unit=$(echo "$line" | awk '{print $1}')
    [[ -n "${IGNORED[$unit]:-}" ]] && continue

    "$NOTIFY" --severity WARNING --key "systemd-failed-${unit}" \
        --subject "Systemd: ${unit} failed on $(hostname)" \
        --body "Systemd unit '${unit}' is in failed state.

Check:
  systemctl status ${unit}
  journalctl -u ${unit} --no-pager -n 30"
done < <(systemctl --failed --no-legend 2>/dev/null)

# Touch freshness stamp
mkdir -p "$(dirname "$MONITOR_STAMP")"
touch "$MONITOR_STAMP"
```

**Step 2: Make executable and commit**

```bash
chmod +x bin/cron/willflix-check-systemd
git add bin/cron/willflix-check-systemd
git commit -m "Add willflix-check-systemd unit failure monitor"
```

**Step 3: Test**

```bash
sudo bin/cron/willflix-check-systemd
```

Expected: No alerts (all 6 failed units are in the ignore list). Verify stamp: `ls -la /var/tmp/willflix-monitors/willflix-check-systemd`.

---

### Task 5: Backup freshness config

**Files:**
- Create: `etc/willflix-check-backups.conf`

**Step 1: Create the config**

```
# Backup freshness monitoring.
# Format: <name> <max_stale_hours> <stamp_file>
# Lines starting with # are comments.

backup_plex          36  /var/tmp/willflix-monitors/backup_plex
backup_calibre       36  /var/tmp/willflix-monitors/backup_calibre
backup_google_photos 36  /var/tmp/willflix-monitors/backup_google_photos
backup_gmail         36  /var/tmp/willflix-monitors/backup_gmail
backup_home          36  /var/tmp/willflix-monitors/backup_home
plex_db_backup       36  /var/tmp/willflix-monitors/plex_db_backup
restic_backup        36  /Volumes/Bonus1/lafayette/snapshots
```

Note: `restic_backup` uses the restic repo's `snapshots/` directory mtime directly — no stamp file needed. The restic container updates this directory on every successful backup.

**Step 2: Commit**

```bash
git add etc/willflix-check-backups.conf
git commit -m "Add backup freshness monitoring config"
```

---

### Task 6: willflix-check-backups

**Files:**
- Create: `bin/cron/willflix-check-backups`

**Step 1: Write the script**

```bash
#!/bin/bash
# willflix-check-backups — monitor backup freshness via timestamp files.
# Reads config file for expected backup jobs and their freshness thresholds.
# Run daily at 9:15am via cron.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTIFY="$(cd "$SCRIPT_DIR/.." && pwd)/willflix-notify"
MONITOR_STAMP="/var/tmp/willflix-monitors/willflix-check-backups"
CONFIG_FILE="$(cd "$SCRIPT_DIR/../../etc" && pwd)/willflix-check-backups.conf"

if [[ ! -f "$CONFIG_FILE" ]]; then
    "$NOTIFY" --severity WARNING --key "backup-config-missing" \
        --subject "Backup monitor config missing on $(hostname)" \
        --body "Expected config at $CONFIG_FILE"
    exit 1
fi

STALE=""

while IFS= read -r line; do
    # Skip comments and blank lines
    line="${line%%#*}"
    [[ -z "${line// /}" ]] && continue

    read -r name max_hours stamp_path <<< "$line"

    if [[ ! -e "$stamp_path" ]]; then
        STALE="${STALE}  ${name}: never ran (${stamp_path} not found)\n"
        continue
    fi

    age_hours=$(( ($(date +%s) - $(stat -c %Y "$stamp_path")) / 3600 ))
    if [[ "$age_hours" -gt "$max_hours" ]]; then
        STALE="${STALE}  ${name}: last ran ${age_hours}h ago (threshold: ${max_hours}h)\n"
    fi
done < "$CONFIG_FILE"

if [[ -n "$STALE" ]]; then
    "$NOTIFY" --severity WARNING --key "backup-freshness-fail" \
        --subject "Backup freshness check failed on $(hostname)" \
        --body "$(echo -e "The following backups are stale or missing:\n\n${STALE}\nCheck that backup cron jobs are running:\n  crontab -l\n  sudo crontab -l\n  docker logs restic-backup --tail 10")"
fi

# Touch freshness stamp
mkdir -p "$(dirname "$MONITOR_STAMP")"
touch "$MONITOR_STAMP"
```

**Step 2: Make executable and commit**

```bash
chmod +x bin/cron/willflix-check-backups
git add bin/cron/willflix-check-backups
git commit -m "Add willflix-check-backups freshness monitor"
```

**Step 3: Test (will alert about missing stamp files for most backups)**

```bash
sudo bin/cron/willflix-check-backups
```

Expected: WARNING alert listing backup jobs with no stamp files yet. The restic_backup entry should be OK (snapshots/ dir exists and is fresh).

---

### Task 7: Add stamp touches to backup_plex

**Files:**
- Modify: `bin/cron/backup_plex`

The only backup script in this repo. Add a freshness stamp touch on success.

**Step 1: Read the current script and add stamp**

Add these lines at the end of the script (before the final line or after the last command):

```bash
# Touch freshness stamp
mkdir -p /var/tmp/willflix-monitors
touch /var/tmp/willflix-monitors/backup_plex
```

**Step 2: Commit**

```bash
git add bin/cron/backup_plex
git commit -m "Add freshness stamp to backup_plex"
```

---

### Task 8: Update will's crontab with stamp touches

**Files:**
- Document changes needed (will's crontab is not in this repo)

The will user's backup cron jobs need `&& touch /var/tmp/willflix-monitors/<name>` appended. Since these scripts live outside this repo, the safest approach is to modify the crontab lines directly.

**Step 1: Create a reference file showing the needed changes**

Create `etc/will-crontab-additions.txt` as a reference:

```
# Will's crontab backup jobs — add stamp touches for freshness monitoring.
# Apply with: crontab -e
#
# BEFORE:
#   0 0 * * * /usr/local/bin/cronic /home/will/bin/cron/backup_calibre
# AFTER:
#   0 0 * * * /usr/local/bin/cronic /home/will/bin/cron/backup_calibre && touch /var/tmp/willflix-monitors/backup_calibre

0 0 * * * /usr/local/bin/cronic /home/will/bin/cron/backup_calibre && touch /var/tmp/willflix-monitors/backup_calibre
0 0 * * * /usr/local/bin/cronic /home/will/bin/cron/backup_google_photos && touch /var/tmp/willflix-monitors/backup_google_photos
30 0 * * * /usr/local/bin/cronic /home/will/bin/cron/backup_gmail && touch /var/tmp/willflix-monitors/backup_gmail
45 0 * * * /usr/local/bin/cronic /home/will/bin/cron/backup_home && touch /var/tmp/willflix-monitors/backup_home
0 1 * * * /usr/local/bin/cronic /home/will/Dropbox/system/bin/plex_db_backup.sh && touch /var/tmp/willflix-monitors/plex_db_backup
```

**Step 2: Commit the reference file**

```bash
git add etc/will-crontab-additions.txt
git commit -m "Add reference for will crontab stamp additions"
```

**Step 3: Apply the crontab changes (manual step)**

```bash
crontab -e
# Replace each backup line with the version that includes && touch ...
```

---

### Task 9: Update crontab and heartbeat

**Files:**
- Modify: `etc/root-crontab`
- Modify: `bin/cron/willflix-heartbeat`

**Step 1: Add new cron entries to root-crontab**

Add after the heartbeat entries:

```
# Service health checks (every 15 min)
*/15 * * * * /home/will/bin/cron/willflix-check-docker
*/15 * * * * /home/will/bin/cron/willflix-check-systemd

# Backup freshness (daily after heartbeat)
15 9 * * * /home/will/bin/cron/willflix-check-backups
```

**Step 2: Update heartbeat freshness monitors**

In `bin/cron/willflix-heartbeat`, add to the MONITORS array:

```bash
MONITORS=(
    "check_mergerfs_health 45"
    "check_snapraid_freshness 2880"
    "snapraid_daily 4320"
    "willflix-check-docker 45"
    "willflix-check-systemd 45"
    "willflix-check-backups 2880"
)
```

**Step 3: Commit**

```bash
git add etc/root-crontab bin/cron/willflix-heartbeat
git commit -m "Add Phase 2a monitoring to crontab and heartbeat"
```

**Step 4: Apply crontab**

```bash
sudo crontab etc/root-crontab
sudo crontab -l  # verify
```

---

### Task 10: End-to-end verification

**Step 1: Syntax check all new scripts**

```bash
bash -n bin/cron/willflix-check-docker && echo "docker: OK"
bash -n bin/cron/willflix-check-systemd && echo "systemd: OK"
bash -n bin/cron/willflix-check-backups && echo "backups: OK"
```

**Step 2: Verify all scripts are executable**

```bash
ls -la bin/cron/willflix-check-*
```

**Step 3: Run Docker check**

```bash
sudo bin/cron/willflix-check-docker
```

Expected: CRITICAL for ofelia (crash-loop), WARNING for authentik-worker (unhealthy).

**Step 4: Run systemd check**

```bash
sudo bin/cron/willflix-check-systemd
```

Expected: No alerts (all known failures in ignore list).

**Step 5: Run backup check**

```bash
sudo bin/cron/willflix-check-backups
```

Expected: WARNING about stale/missing stamp files for backups that haven't run since adding stamps.

**Step 6: Verify freshness stamps**

```bash
ls -la /var/tmp/willflix-monitors/
```

Should show stamps for all three new check scripts.

**Step 7: Verify heartbeat sees new monitors**

```bash
bin/cron/willflix-heartbeat --silent
```

Should check freshness of all monitors including the new ones.
