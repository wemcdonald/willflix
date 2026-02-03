# AGENTS.md - Infrastructure Patterns Guide

This document provides patterns and procedures for AI agents working with this Docker-based server infrastructure.

## Directory Structure

```
/docker/
├── appdata/           # Persistent data for each service
├── bin/               # Utility scripts (user management, webhooks, mail)
├── config/            # Core configuration (compose, traefik, secrets)
│   ├── docker-compose.yml    # Main orchestration file
│   ├── traefik-middlewares.yml  # Authentik forward-auth config
│   ├── nginx-public.conf     # Static content server config
│   └── secrets/              # Encrypted credentials (git-crypt)
├── logs/              # Service log output
├── setup/             # Installation scripts and docs
└── systemd/           # Systemd service unit files (symlinked to /etc/systemd/system/)
```

## Networks

Three Docker networks are defined:

| Network | Purpose | Usage |
|---------|---------|-------|
| `traefik_public` | External-facing services behind Traefik | Web apps, APIs |
| `default` | Internal communication | Databases, Redis, service-to-service |
| `homebot_network` | Isolated bot services | Telegram bots |

Services typically join `traefik_public` for web access and `default` for database access.

## Authentication Patterns

### Pattern 1: Forward-Auth (Admin Tools)

For services that don't support OIDC natively. Traefik intercepts requests and validates with Authentik.

**Traefik labels:**
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.services.{name}.loadbalancer.server.port={port}"
  - "traefik.http.routers.{name}.rule=Host(`{name}.willflix.org`)"
  - "traefik.http.routers.{name}.entrypoints=websecure"
  - "traefik.http.routers.{name}.tls.certresolver=le"
  - "traefik.http.routers.{name}.middlewares=authentik-forward@file"
```

The `authentik-forward@file` middleware is defined in `/docker/config/traefik-middlewares.yml` and passes these headers to the service:
- `X-authentik-username`
- `X-authentik-email`
- `X-authentik-groups`
- `X-authentik-name`
- `X-authentik-uid`

**Use when:** Service has no OIDC support, admin-only access needed.

### Pattern 2: OIDC Integration (User Apps)

For services with native OIDC/OAuth2 support. The app redirects to Authentik directly.

**Traefik labels (no middleware):**
```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.services.{name}.loadbalancer.server.port={port}"
  - "traefik.http.routers.{name}.rule=Host(`{name}.willflix.org`)"
  - "traefik.http.routers.{name}.entrypoints=websecure"
  - "traefik.http.routers.{name}.tls.certresolver=le"
  # NO middleware - app handles auth
```

**Authentik setup required:**
1. Create OAuth2/OIDC Provider in Authentik
2. Create Application linked to provider
3. Configure service with client ID/secret and discovery URL

**Use when:** Service supports OIDC, need user-facing login flow.

### Pattern 3: No Authentication (Public)

For publicly accessible services.

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.services.{name}.loadbalancer.server.port={port}"
  - "traefik.http.routers.{name}.rule=Host(`{name}.willflix.org`)"
  - "traefik.http.routers.{name}.entrypoints=websecure"
  - "traefik.http.routers.{name}.tls.certresolver=le"
  # NO middleware
```

## VPN Routing Pattern

For services that need all traffic routed through VPN (e.g., torrent clients):

```yaml
vpn:
  image: qmcgaw/gluetun
  cap_add:
    - NET_ADMIN
  devices:
    - /dev/net/tun:/dev/net/tun
  ports:
    - "{host_port}:{service_port}"  # Expose the dependent service's port here
  environment:
    - VPN_SERVICE_PROVIDER=privado
    - FIREWALL_VPN_INPUT_PORTS={allowed_ports}
  networks:
    - traefik_public
  labels:
    # Traefik routes to this container's port
    - "traefik.http.services.{service}.loadbalancer.server.port={service_port}"

dependent_service:
  image: ...
  network_mode: "service:vpn"  # Route all traffic through VPN
  depends_on:
    - vpn
  # NO ports section - vpn container exposes them
  # NO networks section - uses vpn's network
```

**Key points:**
- Dependent service uses `network_mode: "service:vpn"`
- Ports are exposed on the VPN container, not the service
- VPN acts as kill-switch: if VPN drops, service loses connectivity
- Traefik reaches the service via VPN container's exposed port

## Adding a New Service

### Step 1: Add to docker-compose.yml

**Basic web service with forward-auth:**
```yaml
myservice:
  image: myimage:latest
  container_name: myservice
  environment:
    - PUID=122
    - PGID=129
    - TZ=America/Los_Angeles
  volumes:
    - /docker/appdata/myservice:/config
  restart: unless-stopped
  labels:
    - "traefik.enable=true"
    - "traefik.http.services.myservice.loadbalancer.server.port=8080"
    - "traefik.http.routers.myservice.rule=Host(`myservice.willflix.org`)"
    - "traefik.http.routers.myservice.entrypoints=websecure"
    - "traefik.http.routers.myservice.tls.certresolver=le"
    - "traefik.http.routers.myservice.middlewares=authentik-forward@file"
  networks:
    - traefik_public
```

**Service needing database access:**
```yaml
myservice:
  # ... same as above ...
  networks:
    - traefik_public
    - default  # For postgres/redis access
  depends_on:
    - postgres
```

**Service needing media access:**
```yaml
myservice:
  # ... same as above ...
  volumes:
    - /docker/appdata/myservice:/config
    - /Volumes/Media:/Volumes/Media
```

### Step 2: Create appdata directory

```bash
mkdir -p /docker/appdata/myservice
```

### Step 3: Create systemd service

Create `/docker/systemd/myservice.service`:
```ini
[Unit]
Description=My Service
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=true
WorkingDirectory=/docker/config
ExecStart=/usr/bin/docker compose up -d myservice
ExecStop=/usr/bin/docker compose down myservice
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

**For multi-container services** (like authentik with server + worker):
```ini
ExecStart=/usr/bin/docker compose up -d myservice-server myservice-worker
ExecStop=/usr/bin/docker compose down myservice-server myservice-worker
```

### Step 4: Enable the systemd service

```bash
cd /etc/systemd/system
sudo ln -s /docker/systemd/myservice.service .
sudo systemctl daemon-reload
sudo systemctl enable myservice
sudo systemctl start myservice
```

### Step 5: Create Authentik application (if using forward-auth)

1. Go to Authentik admin → Applications → Create
2. Name: `myservice`
3. Slug: `myservice`
4. Provider: Select or create an authorization flow
5. Launch URL: `https://myservice.willflix.org`

## Modifying Existing Services

### Change service configuration

1. Edit `/docker/config/docker-compose.yml`
2. Restart the service:
   ```bash
   sudo systemctl restart myservice
   # or
   cd /docker/config && docker compose up -d myservice
   ```

### Update Traefik routing

1. Edit labels in docker-compose.yml
2. Restart the service (Traefik picks up label changes automatically)

### Update Traefik middleware

1. Edit `/docker/config/traefik-middlewares.yml`
2. Restart Traefik:
   ```bash
   sudo systemctl restart traefik
   ```

## Service Management Commands

**IMPORTANT:** Never use bare `docker compose up -d` or `docker compose down`. Always specify service names.

### Using systemctl (preferred)
```bash
sudo systemctl start myservice
sudo systemctl stop myservice
sudo systemctl restart myservice
sudo systemctl status myservice
sudo journalctl -u myservice -f  # View logs
```

### Using docker compose directly
```bash
cd /docker/config
docker compose up -d myservice
docker compose down myservice
docker compose logs -f myservice
docker compose ps myservice
```

### Get container name
```bash
docker-name myservice  # Returns actual container name
```

### Execute into container
```bash
docker exec -it myservice /bin/bash
```

## Appdata Git Tracking

The `/docker/appdata/.gitignore` uses a layered approach to track configs while excluding data:

```gitignore
# Layer 1: Exclude data-heavy directories entirely
audiobookshelf/
postgres/
radarr/
sonarr/

# Layer 2: Include certain directories entirely (configs only)
!authentik/
!nginx-*/
!smtp-relay/

# Layer 3: Selectively include specific configs from excluded dirs
!nextcloud/config/
!nextcloud/config/**
!jdownloader/cfg/
!jdownloader/cfg/**
!*/config.xml
!*/*.conf

# Layer 4: Exclude sensitive/data from included dirs
authentik/media/
authentik/certs/
nginx-*/logs/
```

**When adding a new service:**
1. If it generates lots of data (databases, caches, media): Add `servicename/` to exclude it
2. If you want to track its config files, add selective includes:
   ```gitignore
   !servicename/config/
   !servicename/config/**
   ```
3. If it has logs or sensitive data in tracked dirs, exclude those specifically

**Pattern:** Exclude by default, explicitly include only what should be version controlled.

## Secrets Management

Secrets are stored in `/docker/config/secrets/` (encrypted with git-crypt).

### Using Docker secrets
```yaml
secrets:
  my_secret:
    file: ./secrets/my_secret

services:
  myservice:
    secrets:
      - my_secret
    environment:
      - MY_SECRET_FILE=/run/secrets/my_secret
```

### Using env files
```yaml
services:
  myservice:
    env_file:
      - /docker/config/secrets/myservice_env
```

### In scripts
```bash
source /docker/config/secrets/authentik_api_env
```

## Common Patterns

### Service with PostgreSQL
```yaml
myservice:
  depends_on:
    - postgres
  environment:
    - DB_HOST=postgres
    - DB_NAME=myservice
    - DB_USER=myservice
    - DB_PASSWORD_FILE=/run/secrets/myservice_db_password
  networks:
    - traefik_public
    - default
```

### Service with Redis
```yaml
myservice:
  depends_on:
    - redis
  environment:
    - REDIS_HOST=redis
  networks:
    - default
```

### Service using host network
```yaml
myservice:
  network_mode: host
  # Cannot use Traefik - access directly via host port
```

### Health checks
```yaml
myservice:
  healthcheck:
    test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s
```

### Resource limits
```yaml
myservice:
  deploy:
    resources:
      limits:
        memory: 1G
        cpus: '0.5'
```

## User Management Scripts

Located in `/docker/bin/`:

| Script | Purpose |
|--------|---------|
| `add-user` | Create user in Authentik + Calibre-Web + Nextcloud + Plex |
| `add-calibre-user` | Add user to Calibre-Web only |
| `sync-users` | Sync Authentik group members to Calibre-Web |
| `invite-to-plex` | Send Plex server invite |
| `list-users` | List all Authentik users |
| `email-users` | Send email to all users |

Usage:
```bash
/docker/bin/add-user username email@example.com [admin|user]
```

## Troubleshooting

### Service won't start
```bash
sudo systemctl status myservice
sudo journalctl -u myservice -n 50
docker compose logs myservice
```

### Traefik routing issues
```bash
# Check Traefik dashboard (if enabled)
# Verify labels are correct
docker inspect myservice | grep -A 50 Labels

# Check Traefik logs
docker compose logs traefik
```

### Authentication issues
```bash
# Check Authentik logs
docker compose logs authentik-server

# Verify middleware is loading
# Check traefik-middlewares.yml syntax
```

### Network issues
```bash
# Verify service is on correct network
docker inspect myservice | grep -A 10 Networks

# Test internal connectivity
docker exec myservice ping postgres
```
