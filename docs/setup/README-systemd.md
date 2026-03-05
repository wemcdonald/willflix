# Docker Systemd Services Setup

Automated setup for all Docker services as systemd units, providing proper system integration and startup management.

## Features

- **Automatic Discovery**: Finds all `.service` files in `/docker/systemd/`
- **Safe Operation**: Checks for existing links and handles conflicts
- **Comprehensive Reporting**: Shows what was linked, enabled, or already configured
- **Health Checks**: Verifies Docker and Docker Compose availability
- **Idempotent**: Safe to run multiple times

## Quick Setup

```bash
# Run the automated setup script
/docker/setup/systemd-setup.sh
```

## What It Does

1. **Scans** `/docker/systemd/` for all `.service` files
2. **Symlinks** each service to `/etc/systemd/system/`
3. **Enables** each service for automatic startup
4. **Reports** status of each operation
5. **Validates** system prerequisites

## Service Management

### Starting Services
```bash
# Start a specific service
sudo systemctl start traefik

# Start all Docker services (example for current services)
sudo systemctl start backup postgres redis authentik traefik vpn
```

### Checking Status
```bash
# Check specific service
sudo systemctl status traefik

# List all Docker services
systemctl list-units '*docker*' --all

# Show enabled services
systemctl list-unit-files --state=enabled | grep docker
```

### Managing Services
```bash
# Stop a service
sudo systemctl stop traefik

# Restart a service
sudo systemctl restart traefik

# Disable a service
sudo systemctl disable traefik

# View service logs
sudo journalctl -u traefik -f
```

## Current Services

The script automatically detects and configures these services:
- `adminer.service`
- `audiobookshelf.service`
- `authentik.service`
- `authentik-worker.service`
- `backup.service`
- `calibre.service`
- `calibre-web-automated.service`
- `ddclient-docker.service`
- `healthbot.service`
- `jdownloader.service`
- `nextcloud.service`
- `nginx-private.service`
- `nginx-public.service`
- `nzbget.service`
- `ofelia.service`
- `plex.service`
- `postgres.service`
- `qbittorrent.service`
- `radarr.service`
- `redis.service`
- `samba-docker.service`
- `smtp-relay.service`
- `sonarr.service`
- `traefik.service`
- `vnc.service`
- `vpn.service`
- `webhook-handler.service`

## Advantages Over Docker Compose

- **System Integration**: Services integrate with systemd startup/shutdown
- **Individual Control**: Start/stop/restart individual services
- **Boot Integration**: Services start automatically at boot
- **Logging**: Centralized logging through journalctl
- **Dependencies**: Proper service dependency management
- **Resource Limits**: Can use systemd resource controls

## Troubleshooting

### Common Issues

1. **Permission denied**
   - Ensure you run as regular user (not root)
   - Script will use sudo when needed

2. **Service fails to start**
   ```bash
   sudo systemctl status <service-name>
   sudo journalctl -u <service-name>
   ```

3. **Docker not running**
   ```bash
   sudo systemctl start docker
   sudo systemctl enable docker
   ```

### Reverting Changes

To remove all Docker systemd services:
```bash
# Stop all services first
sudo systemctl stop $(systemctl list-units '*docker*' --plain | grep -o '^[^ ]*')

# Disable and remove links
cd /etc/systemd/system
sudo systemctl disable *.service
sudo rm -f $(ls -la | grep '/docker/systemd' | awk '{print $9}')

# Reload daemon
sudo systemctl daemon-reload
```

## Service Dependencies

Some services depend on others:
- Most services depend on Docker being running
- Database services (postgres, redis) should start before apps
- Traefik should start before web services
- VPN should start before services that use it

The individual service files handle these dependencies appropriately.

## Best Practices

1. **Start Core Services First**: postgres, redis, traefik
2. **Monitor Logs**: Use `journalctl -f` to watch service startup
3. **Health Checks**: Verify services are responding after startup
4. **Resource Monitoring**: Monitor system resources when all services run
5. **Backup Configuration**: Keep `/docker/systemd/` backed up

## Integration with Docker Compose

These systemd services replace `docker compose up`. Benefits:
- Better system integration
- Individual service control
- Proper logging and monitoring
- System startup integration
- Resource management

You should stop using `docker compose up` and use systemd services instead.