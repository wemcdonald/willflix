# Backup Configuration

Our backup system uses Restic running in a Docker container with automated daily backups and configurable retention policies.

## Configuration Overview

**Backup Service**: `restic-backup` container using `mazzolino/restic` image
**Repository**: `/Volumes/Bonus1/lafayette` (local storage)
**Source**: `/home/will/server-config` (Docker configuration and data)
**Schedule**: Daily at 3:30 AM Pacific Time
**Compression**: Maximum compression enabled

### Retention Policy
- Keep last 10 snapshots
- Keep daily snapshots for 7 days
- Keep weekly snapshots for 8 weeks  
- Keep monthly snapshots for 24 months

### Exclusions
- Git repositories (`.git` folders)
- MySQL data files (`/srv/mysql/data`)
- Compressed files (`*.gz`)

## Command Line Access

Set up the alias for easier access:
```bash
alias drestic='docker exec restic-backup restic -r /Volumes/Bonus1/lafayette'
```

## Basic Operations

### View Recent Backups
```bash
# List all snapshots
drestic snapshots

# List last 10 snapshots
drestic snapshots --last 10

# List snapshots with more detail
drestic snapshots --compact
```

### Browse Backup Contents
```bash
# List files in latest backup
drestic ls latest

# List files in specific snapshot
drestic ls <snapshot-id>

# List specific directory in latest backup
drestic ls latest /home/will/server-config/docker

# Search for specific files
drestic find config.yml
```

### Repository Information
```bash
# Show repository statistics
drestic stats

# Show repository statistics for latest snapshot
drestic stats latest

# Check repository integrity
drestic check

# Check repository with detailed output
drestic check --read-data
```

### File Restoration
```bash
# Restore entire latest backup to /tmp/restore
drestic restore latest --target /tmp/restore

# Restore specific file/directory
drestic restore latest --target /tmp/restore --include "/home/will/server-config/docker/docker-compose.yml"

# Restore to specific directory with path filtering
drestic restore latest --target /tmp/restore --include "/home/will/server-config/appdata/nextcloud"
```

### Mount Backups (Interactive Browsing)
```bash
# Mount backup as filesystem (requires FUSE)
drestic mount /mnt/backup

# Browse mounted backup
ls /mnt/backup/snapshots/latest/home/will/server-config/

# Unmount when done
fusermount -u /mnt/backup
```

### Compare Snapshots
```bash
# Compare two snapshots
drestic diff <snapshot1-id> <snapshot2-id>

# Compare latest with previous
drestic diff $(drestic snapshots --json | jq -r '.[1].id') latest
```

### Manual Backup Operations
```bash
# Create manual backup
drestic backup /home/will/server-config --exclude="*.log" --exclude="/home/will/server-config/.git"

# Create backup with tag
drestic backup /home/will/server-config --tag manual-backup

# List snapshots with specific tag
drestic snapshots --tag manual-backup
```

### Maintenance
```bash
# Remove old snapshots (apply retention policy)
drestic forget --keep-last 10 --keep-daily 7 --keep-weekly 8 --keep-monthly 24 --prune

# Optimize repository (remove unreferenced data)
drestic prune

# Combine forget and prune
drestic forget --keep-last 10 --keep-daily 7 --keep-weekly 8 --keep-monthly 24 --prune
```

## Container Management

### Check Backup Status
```bash
# View container logs
docker logs restic-backup

# View recent backup logs
docker logs restic-backup --tail 50

# Follow backup logs in real time
docker logs restic-backup --follow
```

### Manual Container Operations
```bash
# Start backup container
docker start restic-backup

# Stop backup container
docker stop restic-backup

# Restart backup container
docker restart restic-backup

# Run backup immediately
docker exec restic-backup restic backup /home/will/server-config
```

## Security Notes

- Repository password is stored securely in Docker secrets
- Backup repository is on local storage (`/Volumes/Bonus1/lafayette`)
- Source data includes sensitive configuration files and secrets
- All operations require access to the running `restic-backup` container

## Troubleshooting

### Common Issues
```bash
# Repository locked
drestic unlock

# Repository errors
drestic check --read-data

# Container not running
docker start restic-backup

# Check available disk space
df -h /Volumes/Bonus1/

# View backup container environment
docker exec restic-backup env | grep RESTIC
```

### Emergency Recovery
```bash
# If container is unavailable, install restic directly:
# sudo apt-get install restic
# export RESTIC_REPOSITORY=/Volumes/Bonus1/lafayette
# export RESTIC_PASSWORD_FILE=/willflix/secrets/restic_password
# restic snapshots
```

For more information, see the [Restic documentation](https://restic.readthedocs.io/).