---
name: add-docker-service
description: Use when adding a new Docker service to the willflix.org homelab infrastructure, deploying a self-hosted application, setting up a new container, or when the user says "add", "set up", "deploy", or "I want to run" a service
---

# Add Docker Service

## Overview

Checklist-driven procedure for adding a new Docker service to the willflix.org infrastructure. Covers compose entry, Traefik routing, authentication, systemd management, and appdata tracking.

**CRITICAL:** Never run bare `docker compose up -d` or `docker compose down` — always specify service names.

## Checklist

Use TodoWrite to create a todo for each step.

### 1. Research the Service

Before writing any config, determine:

| Question | Where to Find |
|----------|---------------|
| Default port | Docker Hub page, docs |
| Required env vars | Docker Hub, GitHub README |
| Volume paths (config, data) | Docker Hub "Volumes" section |
| OIDC/OAuth2 support | Docs "Authentication" section |
| Database needs (postgres, redis, sqlite) | Docs "Installation" section |
| Needs media access | User requirement |
| Needs VPN routing | User requirement (torrents, usenet) |

### 2. Choose Auth Pattern

Ask the user which pattern fits:

| Pattern | When | Traefik Middleware |
|---------|------|--------------------|
| **Forward-auth** | Admin tools, no native OIDC | `authentik-forward@file` |
| **OIDC** | User-facing app with native OAuth2 | None (app handles it) |
| **Public** | No auth needed | None |

### 3. Choose Networks

| Condition | Network |
|-----------|---------|
| All web services | `traefik_public` |
| Needs postgres or redis | Add `default` |
| Needs VPN routing | Use `network_mode: "service:vpn"` (no networks) |
| Telegram/chat bots | `homebot_network` |

### 4. Write Compose Entry

Add to `/docker/config/docker-compose.yml`.

**Standard web service:**
```yaml
myservice:
  image: org/myservice:latest
  container_name: myservice
  environment:
    - PUID=122
    - PGID=129
    - TZ=America/Los_Angeles
  volumes:
    - /docker/appdata/myservice:/config
  restart: unless-stopped
  networks:
    - traefik_public
  labels:
    - "traefik.enable=true"
    - "traefik.http.services.myservice.loadbalancer.server.port=8080"
    - "traefik.http.routers.myservice.rule=Host(`myservice.willflix.org`)"
    - "traefik.http.routers.myservice.entrypoints=websecure"
    - "traefik.http.routers.myservice.tls.certresolver=le"
    - "traefik.http.routers.myservice.middlewares=authentik-forward@file"
```

**With database:**
```yaml
myservice:
  # ... same as above ...
  depends_on:
    - postgres
  networks:
    - traefik_public
    - default
```

**With media access — add volume:**
```yaml
    - /Volumes/Media:/Volumes/Media
```

**VPN-routed service** (ports go on vpn container, service uses `network_mode: "service:vpn"`):
```yaml
myservice:
  image: org/myservice:latest
  container_name: myservice
  network_mode: "service:vpn"
  environment:
    - PUID=122
    - PGID=129
    - TZ=America/Los_Angeles
  volumes:
    - /docker/appdata/myservice:/config
  depends_on:
    - vpn
  # NO ports, NO networks — vpn container handles both
```

### 5. Create Appdata Directory

```bash
mkdir -p /docker/appdata/myservice
```

### 6. Update Appdata Gitignore

Edit `/docker/appdata/.gitignore`:

- **Generates lots of data** (databases, caches, media downloads): add `myservice/` to exclusion section
- **Has config worth tracking**: add selective includes:
  ```gitignore
  !myservice/config/
  !myservice/config/**
  ```
- **Has logs or sensitive data in tracked dirs**: add specific exclusions:
  ```gitignore
  myservice/logs/
  ```

### 7. Create Systemd Unit

Write `/docker/systemd/myservice.service`:

```ini
[Unit]
Description=My Service Name
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

For **multi-container services** (e.g., app + worker):
```ini
ExecStart=/usr/bin/docker compose up -d myservice-server myservice-worker
ExecStop=/usr/bin/docker compose down myservice-server myservice-worker
```

### 8. Enable Systemd Service

```bash
sudo ln -s /docker/systemd/myservice.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable myservice
sudo systemctl start myservice
```

### 9. Update Port Map

Add the new service to the port documentation at `/docker/appdata/nginx-private/home/ports.html` (served at `private.willflix.org/ports.html`). Add a row to the appropriate category table with: port, service name, public subdomain (if any), access level, and notes.

### 10. Verify

```bash
sudo systemctl status myservice
docker compose ps myservice                         # from /docker/config
curl -sI https://myservice.willflix.org | head -5    # check Traefik routing
```

### 10. OIDC Setup (if applicable)

If the service supports OIDC and user chose that pattern:

1. Go to Authentik admin -> Providers -> Create OAuth2/OIDC Provider
2. Set redirect URI: `https://myservice.willflix.org/callback` (varies per app)
3. Note client ID and client secret
4. Create Application linked to the provider, slug: `myservice`, launch URL: `https://myservice.willflix.org`
5. Configure the service with:
   - Client ID / Client Secret
   - Discovery URL: `https://auth.willflix.org/application/o/myservice/.well-known/openid-configuration`

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Forgot `traefik.enable=true` | Service invisible to Traefik |
| Wrong port in loadbalancer label | Check Docker Hub for actual default port |
| Missing `traefik_public` network | Traefik can't reach the container |
| VPN service has its own `ports:` | Ports must go on the vpn container |
| Bare `docker compose up -d` | Always specify service name(s) |
| Forward-auth on OIDC app | Double auth — pick one pattern |
| Forgot to update port map | Add row to `/docker/appdata/nginx-private/home/ports.html` |
