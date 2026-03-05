# Config — Compose & Infrastructure Patterns

## Key Files

- `docker-compose.yml` — main orchestration (all services)
- `traefik-middlewares.yml` — Authentik forward-auth middleware definition
- `secrets/` — git-crypt encrypted credentials

## Standard Environment

```yaml
environment:
  - PUID=122
  - PGID=129
  - TZ=America/Los_Angeles
```

## Authentication Patterns

### 1. Forward-Auth (Admin Tools)

For services without OIDC support. Traefik intercepts every request and validates against Authentik.

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.services.{name}.loadbalancer.server.port={port}"
  - "traefik.http.routers.{name}.rule=Host(`{name}.willflix.org`)"
  - "traefik.http.routers.{name}.entrypoints=websecure"
  - "traefik.http.routers.{name}.tls.certresolver=le"
  - "traefik.http.routers.{name}.middlewares=authentik-forward@file"
```

The `authentik-forward@file` middleware is defined in `traefik-middlewares.yml` and forwards these headers to the service:
- `X-authentik-username`, `X-authentik-email`, `X-authentik-groups`
- `X-authentik-name`, `X-authentik-uid`

**Use when:** Service has no OIDC support, admin-only or authenticated access needed.

### 2. OIDC Integration (User Apps)

For services with native OAuth2/OIDC support (Nextcloud, Audiobookshelf). The app redirects to Authentik directly — no Traefik middleware needed.

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.services.{name}.loadbalancer.server.port={port}"
  - "traefik.http.routers.{name}.rule=Host(`{name}.willflix.org`)"
  - "traefik.http.routers.{name}.entrypoints=websecure"
  - "traefik.http.routers.{name}.tls.certresolver=le"
  # NO middleware — app handles auth via OIDC
```

**Authentik setup required:**
1. Create OAuth2/OIDC Provider in Authentik admin
2. Create Application linked to provider
3. Configure service with client ID/secret and discovery URL

**Use when:** Service supports OIDC, user-facing login flow needed.

### 3. No Authentication (Public)

Same labels as OIDC but no middleware and no app-level auth. Publicly accessible.

## VPN Routing Pattern

For services that must route all traffic through VPN (e.g., torrent clients). Uses gluetun as a sidecar with kill-switch behavior.

```yaml
vpn:
  image: qmcgaw/gluetun
  cap_add:
    - NET_ADMIN
  devices:
    - /dev/net/tun:/dev/net/tun
  ports:
    - "{host_port}:{service_port}"  # Dependent service's port exposed HERE
  environment:
    - VPN_SERVICE_PROVIDER=privado
    - FIREWALL_VPN_INPUT_PORTS={allowed_ports}
  networks:
    - traefik_public
  labels:
    - "traefik.http.services.{service}.loadbalancer.server.port={service_port}"

dependent_service:
  image: ...
  network_mode: "service:vpn"  # All traffic routes through VPN
  depends_on:
    - vpn
  # NO ports — vpn container exposes them
  # NO networks — uses vpn's network stack
```

**Key rules:**
- Ports go on the VPN container, not the service
- Dependent service has NO `ports:` or `networks:` sections
- Traefik routes to the VPN container's exposed port

## Common Compose Patterns

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
    - default  # Required for postgres access
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

### Host Network Mode

```yaml
myservice:
  network_mode: host
  # Cannot use Traefik — access directly via host port
```

### Health Checks

```yaml
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

### Resource Limits

```yaml
deploy:
  resources:
    limits:
      memory: 1G
      cpus: '0.5'
```

### Media Volumes

```yaml
volumes:
  - /Volumes/Media:/Volumes/Media        # General media services
  - /Volumes/Plex:/Volumes/Plex          # Plex-specific
```

## Secrets

### Docker Secrets (preferred for sensitive values)

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

### Env File Pattern

```yaml
services:
  myservice:
    env_file:
      - /docker/config/secrets/myservice_env
```

### Script Sourcing

```bash
source /docker/config/secrets/authentik_api_env
```

All secrets files are git-crypt encrypted. Never commit plaintext secrets.

## Network Binding & Tailscale Serve

### Binding Policy

Services should bind to the **narrowest interface** needed:

| Access pattern | Bind to | Tailscale serve? | Example |
|---------------|---------|-------------------|---------|
| Public web (Traefik) | `0.0.0.0` or Docker default | No | Sonarr, Radarr |
| Tailnet-only (direct port access) | `127.0.0.1` | Yes | PostgreSQL, Redis, Adminer |
| Docker-internal only | No host port | No | smtp-relay |
| Host-native + Tailnet | `127.0.0.1` | Yes | OpenCode serve/web |

**Docker services** accessed only via Traefik don't need host port binding changes — Traefik reaches them over Docker networks, not host ports. The host port is a convenience for direct access.

**Host-native services** (OpenCode, VNC, etc.) should bind `127.0.0.1` and use `tailscale serve` for tailnet access.

### Tailscale Serve

Tailscale serve creates HTTPS proxies on the tailnet, making `127.0.0.1`-bound services reachable at `willflix.tail88dba.ts.net:{port}`.

**Source of truth:** `/docker/bin/tailscale-serve-setup`

This script is the single config file for all tailscale serve entries. It resets all entries and re-applies them. To add/remove/change entries:

1. Edit `/docker/bin/tailscale-serve-setup`
2. Preview: `sudo /docker/bin/tailscale-serve-setup --dry-run`
3. Apply: `sudo /docker/bin/tailscale-serve-setup`
4. Commit the script change

Entries persist across reboots (stored in tailscaled state). The script only needs to run when entries change.

**Supported proxy types:**

```bash
# HTTPS → HTTP (web services)
tailscale serve --bg --https=PORT http://127.0.0.1:PORT

# TCP passthrough (databases, non-HTTP)
tailscale serve --bg --tcp=PORT tcp://127.0.0.1:PORT

# HTTPS → HTTPS (self-signed upstream)
tailscale serve --bg --https=PORT https+insecure://127.0.0.1:PORT
```

**Access:** `willflix.tail88dba.ts.net:{port}` — tailnet-authenticated, no extra auth layer.

### When Adding a New Service

If the service needs tailnet-only direct access:

1. Bind to `127.0.0.1` (in compose: `127.0.0.1:port:port`, in systemd: `--hostname 127.0.0.1`)
2. Add a `tailscale serve` entry in `/docker/bin/tailscale-serve-setup`
3. Run the setup script
4. Update the port map at `/docker/appdata/nginx-private/home/ports.html`
