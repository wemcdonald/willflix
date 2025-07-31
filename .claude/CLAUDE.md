# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

This is a self-hosted media server setup running containerized services behind Traefik reverse proxy with Authentik SSO authentication. The architecture implements a comprehensive Single Sign-On (SSO) solution for both user-facing applications and admin-only services.

The /docker directory should contain almost all of the custom configuration for the server's apps - this directory should allow a user to get the full application stack up and running on a new machine.

### Core Architecture

**SSO Stack**: Traefik (reverse proxy) + Authentik (identity provider) + PostgreSQL + Redis
- **Traefik**: Handles routing, SSL termination (Let's Encrypt), and forward authentication
- **Authentik**: Central identity provider with OIDC/SAML support and forward-auth capabilities
- **Auth Flow**: Users authenticate once with Authentik, then access all authorized services seamlessly

**Service Categories**:
1. **User-facing apps**: Calibre-Web, Audiobookshelf, Nextcloud (use OIDC/reverse proxy auth)
2. **Admin apps**: Sonarr, Radarr, NZBGet, qBittorrent, JDownloader (protected by forward-auth only)

### Network Architecture

All services run on Docker with two key networks:
- `traefik_public`: External-facing services behind Traefik
- `default`: Internal communication network

Services are accessed via subdomains (e.g., `books.willflix.org`, `sonarr.willflix.org`) with automatic SSL certificates.

## User Management System

Three custom scripts handle user provisioning across the SSO ecosystem:

### Scripts Location: `/docker/bin/`

1. **`add-calibre-user`**: Adds users to Calibre-Web SQLite database only
2. **`sync-users`**: Syncs users from Authentik "Willflix Users" group to Calibre-Web
3. **`add-user`**: Creates users in both Authentik and Calibre-Web systems

### Configuration

All scripts source environment variables from `/docker/config/secrets/authentik_api_env`:
- `AUTHENTIK_API_KEY`: API token for Authentik REST API
- `AUTHENTIK_WILLFLIX_GROUP_ID`: UUID of main user group
- `CALIBRE_USER_ROLE`: Permission bits for regular users (258 = Download + View Books)
- `CALIBRE_ADMIN_ROLE`: Permission bits for admin users (475 = Full permissions)

### User Creation Patterns

**Authentik Users**: Created with `type: "external"`, automatically added to "Willflix Users" group
**Calibre-Web Users**: Role-based permissions, support reverse proxy authentication via `X-authentik-username` header
**Upsert Logic**: Scripts only create users if both username AND email are completely new

## Key Services Integration

### Authentication Flow

1. **Forward Auth Apps** (Admin tools): Traefik middleware → Authentik authorization → Pass/Deny
2. **OIDC Apps** (Audiobookshelf): Direct OIDC integration with Authentik as IdP
3. **Reverse Proxy Auth** (Calibre-Web): Trusts `X-authentik-username` header from Traefik

### Database Locations

- **Authentik**: PostgreSQL database (container: `postgres`)
- **Calibre-Web**: SQLite at `/docker/appdata/calibre-web-automated/app.db`
- **Audiobookshelf**: SQLite at `/docker/appdata/audiobookshelf/config/absdatabase.sqlite` (may have schema corruption)

## Docker Compose Structure

**Main compose file**: `/docker/config/docker-compose.yml`
**Secrets management**: `/docker/config/secrets/` directory with git-crypt encryption
**Middleware config**: `/docker/config/traefik-middlewares.yml` defines Authentik forward-auth

### Service Dependencies

```
Traefik → Authentik Server/Worker → PostgreSQL + Redis
       ↓
All other services (protected by auth middleware)
```

### Volume Mounts

- Application data: `/docker/appdata/{service}/`
- Media storage: `/Volumes/Media/` (shared across media services)
- Config: `/docker/config/` (compose files, secrets, middleware definitions)

## Development Commands

### User Management

```bash
# Add user to both Authentik and Calibre-Web
./bin/add-user username email@example.com user

# Add user to Calibre-Web only
./bin/add-calibre-user username email@example.com admin

# Sync all Authentik users to Calibre-Web
./bin/sync-users
```

### Database Operations

```bash
# Check Calibre-Web users and roles
sqlite3 /docker/appdata/calibre-web-automated/app.db "SELECT name, email, role FROM user;"

# Access PostgreSQL via localhost and leveraging ~/.pgpass
psql -h localhost -U authentik -d authentik
```

### Service Management
DON'T use `docker compose up -d` or docker compose down` on all services.
ALWAYS use names - e.g. `docker compose up -d authentik-server authentik-worker`.
This means that for other things in docker-compose (like networks), you'll have to manage them manually as well.

```bash
# Get the name of a running container
docker-name traefik

# Deploy/update services
cd /docker/config && docker compose up -d

# View logs for specific service
docker compose logs -f $(docker-name authentik-server)

# Restart Traefik (after middleware changes)
docker compose restart traefik
```

## Security Considerations

**Secret Management**: All sensitive data stored in `/docker/config/secrets/` and encrypted with git-crypt
**Network Security**: Services only accessible via internal Docker networks, not exposed ports
**Authentication Headers**: Traefik passes user identity headers only after Authentik verification
**Database Access**: Calibre-Web trusts reverse proxy headers only when properly configured

## Traefik Configuration Patterns

Services require specific labels for proper integration:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.{service}.rule=Host(`{service}.willflix.org`)"
  - "traefik.http.routers.{service}.entrypoints=websecure"
  - "traefik.http.routers.{service}.tls.certresolver=le"
  - "traefik.http.routers.{service}.middlewares=authentik-forward@file"
  - "traefik.http.services.{service}.loadbalancer.server.port={port}"
```

The `authentik-forward@file` middleware is defined in `traefik-middlewares.yml` and handles the SSO integration.

## Infrastructure Services

### VPN & Network Isolation

**qBittorrent + Gluetun VPN**: Torrenting is isolated through a VPN container setup
- `vpn` service runs Gluetun (Privado VPN provider) with kill-switch functionality
- `qbittorrent` uses `network_mode: "service:vpn"` to route all traffic through VPN
- Traefik can still reach qBittorrent web UI via the VPN container's exposed port
- **Firewall Rules**: Only VPN traffic allowed, prevents IP leaks if VPN fails

### Mail Relay System

**SMTP Relay**: Containerized Postfix relay for system notifications
- `smtp-relay` service provides local SMTP server on port 25
- Configured to relay through Gmail SMTP with authentication
- **Local Integration**: `/docker/bin/sendmail-docker` wrapper script makes system sendmail work with containerized SMTP
- **Setup**: `/docker/setup/mail.txt` contains command to configure system sendmail alternative

### Backup Infrastructure

**Restic Automated Backups**: Scheduled backup system using restic
- Backs up `/home/will/server-config` (excluding `.git` and database files)
- **Schedule**: Daily at 3:30 AM with retention policy (10 recent, 7 daily, 8 weekly, 24 monthly)
- **Storage**: Local backup to `/Volumes/Bonus1/lafayette` with rclone integration
- **Compression**: Maximum compression with 64MB pack size for efficiency

### Database Services

**PostgreSQL**: Shared database for multiple services
- Primary database for Authentik authentication system
- Nextcloud also configured to use this PostgreSQL instance
- **Access**: Configured with user `will` and custom data directory

**Redis**: Caching and session storage
- Used by Authentik for session management and caching
- AOF (Append Only File) persistence enabled for durability

### Development & Admin Tools

**VNC Desktop**: Remote desktop access for media management
- Custom-built Docker image with LXQt desktop environment
- **Resolution**: 1920x1080 with VNC access on port 5900
- **Media Access**: Full access to `/Volumes/Media` for file management
- Password-protected via secrets system

**Adminer**: Web-based database administration
- Lightweight PHP-based database management interface
- Accessible on port 48080 for PostgreSQL administration

## Directory Structure & Deployment

### `/docker/systemd/` - Service Management

Individual systemd service files for each container:
- **Purpose**: Allows fine-grained service management outside of compose
- **Pattern**: Each service uses `docker compose up -d {service}` in working directory `/docker/config`
- **Dependencies**: Services properly depend on `docker.service`
- **Usage**: `systemctl enable traefik.service` for automatic startup

### `/docker/setup/` - System Integration

Setup scripts and configuration for host system integration:
- **`mail.txt`**: Command to integrate containerized SMTP with system sendmail
- **Purpose**: Bridge between containerized services and host system utilities

### `/docker/bin/` - Utility Scripts

Custom utilities beyond the user management scripts:
- **`sendmail-docker`**: SMTP wrapper that routes system mail through containerized relay
- **User Management**: The three authentication scripts (`add-user`, `add-calibre-user`, `sync-users`)

### Deployment Philosophy

**Selective Service Management**: Never use `docker compose up -d` or `docker compose down` without service names
- **Reason**: Prevents accidental startup/shutdown of critical services
- **Practice**: Always specify service names explicitly
- **Networks**: Must be managed manually when using selective deployment

**Configuration Externalization**: All service configuration stored in `/docker/config/`
- **Compose Files**: Main orchestration in `docker-compose.yml`
- **Secrets**: Encrypted with git-crypt in `config/secrets/`
- **Middleware**: Traefik middleware definitions in separate YAML files
