# Disaster Recovery — lafayette

What to do when the root SSD dies or you need to rebuild the server from scratch.

## What you need

1. **Fresh Ubuntu 22.04 install** — boot from USB, install, create user `will` with sudo
2. **SSH key for GitHub** — stored in LastPass as "lafayette SSH key"
3. **git-crypt symmetric key** — stored in LastPass as "lafayette git-crypt key" (base64-encoded)
4. **Network access** — wired ethernet recommended

## Quick start

```bash
# On the new machine, as root:
# 1. Set up SSH key for will
mkdir -p /home/will/.ssh
# paste SSH private key from LastPass into /home/will/.ssh/id_ed25519
chmod 600 /home/will/.ssh/id_ed25519
chown -R will:will /home/will/.ssh

# 2. Get the rebuild script (from another machine, USB, or type it)
scp user@othermachine:/willflix/bin/rebuild-lafayette /tmp/
# or: curl -o /tmp/rebuild-lafayette https://raw.githubusercontent.com/wemcdonald/willflix/master/bin/rebuild-lafayette

# 3. Run it
chmod +x /tmp/rebuild-lafayette
sudo /tmp/rebuild-lafayette
```

The script walks you through 9 stages, pausing for confirmation at each.

## Stages

### 1. Prerequisites
Checks Ubuntu version, internet connectivity, and that user `will` exists. Creates the user if missing.

### 2. Packages
Installs Docker (from official repo), git-crypt, smartmontools, mergerfs, snapraid, and utilities. Safe to re-run — skips packages already installed.

### 3. Clone repo
Clones `git@github.com:wemcdonald/willflix.git` to `/willflix`. Creates convenience symlinks (`~/willflix`, `~/bin/cron`).

### 4. Unlock secrets
Decrypts git-crypt secrets. You need the symmetric key file.

**To get the key from LastPass:**
```bash
# Copy the base64 content from LastPass secure note "lafayette git-crypt key"
echo '<paste base64 here>' | base64 -d > /tmp/git-crypt-key
# The script will ask for this path
# DELETE the key file after: rm /tmp/git-crypt-key
```

### 5. Mount drives
Shows which drives are detected by label vs. what's expected. Adds fstab entries and mounts everything. It's normal for some drives to be missing during a rebuild.

**If drives have different device paths**: doesn't matter — fstab uses `LABEL=` mounts.

**If a drive is dead**: skip it. The `nofail` mount option means the system boots fine without it. Fix it later with snapraid.

### 6. System configs
Installs:
- `/etc/smartd.conf` — SMART monitoring
- `/etc/snapraid.conf` — parity array config
- Root crontab — all monitoring and backup cron jobs
- Systemd units — symlinked from `/willflix/etc/systemd/`
- Sendmail wrapper — `/usr/sbin/sendmail` → `/willflix/bin/sendmail-system`
- Docker compat symlink — `/docker` → `/willflix/docker`
- Monitor directories — `/var/tmp/willflix-monitors`, `/var/tmp/willflix-notify`

### 7. Docker services
Starts all ~38 containers. First run pulls all images — expect 10-20 minutes depending on bandwidth.

### 8. Restore PostgreSQL
Loads the latest pg_dump files from `/Volumes/Bonus1/postgres-backup/`. Restores globals first, then each database (authentik, nextcloud, healthdata, will).

**If Bonus1 is not available**: restore the dumps from restic first:
```bash
# Install restic
apt-get install restic

# If Bonus1 is available but dumps aren't:
export RESTIC_REPOSITORY=/Volumes/Bonus1/lafayette
export RESTIC_PASSWORD_FILE=/willflix/secrets/restic_password
restic restore latest --target /tmp/restore --include "/Volumes/Bonus1/postgres-backup"
# Then point the script at /tmp/restore/Volumes/Bonus1/postgres-backup/
```

### 9. Verify
Checks that everything is working: mergerfs mounted, containers running, secrets decrypted, crontab installed. Optionally sends a test notification.

## Skipping stages

Each stage asks for confirmation. Answer `n` to skip. Useful for:
- Partial rebuilds (just need to fix Docker? Skip to stage 7)
- Drives already mounted (skip stage 5)
- Postgres doesn't need restoring (skip stage 8)

## Partial rebuilds

If you don't need a full rebuild, you can do individual pieces manually:

**Just Docker:**
```bash
cd /willflix/docker && docker compose -p config up -d
```

**Just crontab:**
```bash
sudo crontab /willflix/etc/root-crontab
```

**Just systemd units:**
```bash
for unit in /willflix/etc/systemd/*.service; do
    sudo ln -sfn "$unit" "/etc/systemd/system/$(basename "$unit")"
done
sudo systemctl daemon-reload
```

**Just postgres restore:**
```bash
dir=/Volumes/Bonus1/postgres-backup/latest
gunzip -c "$dir/globals.sql.gz" | docker exec -i config-postgres-1 psql -U will postgres
for dump in "$dir"/*.sql.gz; do
    db=$(basename "$dump" .sql.gz)
    [[ "$db" == "globals" ]] && continue
    docker exec config-postgres-1 createdb -U will "$db" 2>/dev/null || true
    gunzip -c "$dump" | docker exec -i config-postgres-1 psql -U will "$db"
done
```

## Restoring appdata from restic

If the root SSD died and you lost `/willflix/docker/appdata/`, restore it from restic:

```bash
export RESTIC_REPOSITORY=/Volumes/Bonus1/lafayette
export RESTIC_PASSWORD_FILE=/willflix/secrets/restic_password
restic restore latest --target / --include "/willflix/docker/appdata"
```

This restores all container data (databases, configs, media indexes). Then restart Docker services.

## Critical files reference

| File | Purpose | Backed up? |
|------|---------|------------|
| `/willflix/secrets/*` | API keys, passwords | git-crypt in GitHub |
| `/willflix/docker/compose.yml` | All service definitions | git in GitHub |
| `/willflix/etc/root-crontab` | All cron jobs | git in GitHub |
| `/willflix/etc/systemd/*.service` | Docker systemd units | git in GitHub |
| `/willflix/docker/appdata/` | Container volumes (13GB) | restic daily |
| `/Volumes/Bonus1/postgres-backup/` | PostgreSQL dumps | pg_dump daily |
| `/Volumes/Bonus1/Plex Media Server.backup/` | Plex database | plex backup daily |
| `/Volumes/Media*` | Media files (98TB) | snapraid triple parity |
| `~/.ssh/id_ed25519` | SSH key | LastPass |
| `.git/git-crypt/keys/default` | git-crypt symmetric key | LastPass |

## Setting up LastPass (one-time)

### git-crypt key
```bash
git-crypt export-key /tmp/key
base64 /tmp/key
# Copy output → LastPass secure note "lafayette git-crypt key"
rm /tmp/key
```

### SSH key
```bash
cat ~/.ssh/id_ed25519
# Copy output → LastPass secure note "lafayette SSH key"
```
