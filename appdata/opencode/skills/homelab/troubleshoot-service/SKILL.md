---
name: troubleshoot-service
description: Use when a Docker service is down, unreachable, returning errors, timing out, showing 502/504, or behaving unexpectedly on the willflix.org homelab infrastructure — also when the user says something is "broken", "not working", or "can't reach"
---

# Troubleshoot Docker Service

## Overview

Systematic triage for Docker service issues on the willflix.org infrastructure. Work layer by layer: container state, then networking, then routing, then auth.

**Core principle:** Gather evidence at each layer before proposing fixes. Don't guess.

## Quick Diagnostic Commands

Run these first to orient. All `docker compose` commands run from `/docker/config`.

| Check | Command |
|-------|---------|
| Systemd status | `sudo systemctl status {service}` |
| Container state | `docker compose ps {service}` |
| Recent logs | `docker compose logs --tail=100 {service}` |
| Systemd journal | `journalctl -u {service} -n 100` |
| Networks | `docker inspect {service} \| jq '.[0].NetworkSettings.Networks \| keys'` |
| Labels | `docker inspect {service} \| jq '.[0].Config.Labels'` |
| Traefik logs | `docker compose logs --tail=50 traefik` |
| Authentik health | `docker compose logs --tail=50 authentik-server` |
| Disk space | `df -h /docker /Volumes/Media` |
| Memory | `free -h` |
| Docker disk | `docker system df` |

## Triage Procedure

### 1. Identify the Service

Map the user's problem to a compose service name. If unclear:
```bash
docker compose ps                    # list all running services
grep -n 'container_name\|image:' /docker/config/docker-compose.yml
```

### 2. Container State

```bash
sudo systemctl status {service}
docker compose ps {service}
```

| State | Meaning | Next Step |
|-------|---------|-----------|
| `Up` | Running | Skip to step 3 |
| `Restarting` | Crash loop | Check logs (step 3) |
| `Exited` | Stopped/crashed | Check logs, then `sudo systemctl restart {service}` |
| Not listed | Never started or removed | Check compose file, then start |

### 3. Logs

```bash
docker compose logs --tail=100 {service}
journalctl -u {service} -n 100
```

Look for: permission errors, missing env vars, failed DB connections, port conflicts, OOM kills.

### 4. Networking

```bash
# Check attached networks
docker inspect {service} | jq '.[0].NetworkSettings.Networks | keys'

# Test internal connectivity
docker exec {service} ping -c1 postgres 2>/dev/null
docker exec {service} wget -qO- http://localhost:{port}/health 2>/dev/null
```

| Symptom | Likely Cause |
|---------|-------------|
| Can't reach postgres/redis | Missing `default` network |
| Traefik can't route | Missing `traefik_public` network |
| VPN service can't reach anything | gluetun disconnected — check vpn logs |
| DNS resolution fails inside container | Docker DNS issue — restart Docker daemon |

For VPN-routed services:
```bash
docker compose logs --tail=50 vpn    # check gluetun connection status
docker exec vpn ping -c1 1.1.1.1     # test VPN tunnel
```

### 5. Traefik Routing

```bash
# Verify labels
docker inspect {service} | jq '.[0].Config.Labels' | grep traefik

# Check Traefik logs for routing errors
docker compose logs --tail=50 traefik | grep {service}
```

Common label issues:
- `Host()` rule mismatch (typo in domain)
- Wrong port in `loadbalancer.server.port`
- Missing `traefik.enable=true`
- Service on wrong Docker network (must be `traefik_public`)

Cert issues:
```bash
# Check acme.json for the domain
jq '.le.Certificates[] | select(.domain.main == "{service}.willflix.org")' \
  /docker/appdata/letsencrypt/acme.json
```

### 6. Authentication

**Forward-auth (502 after login, redirect loop):**
```bash
docker compose logs --tail=50 authentik-server
# Verify middleware file syntax
cat /docker/config/traefik-middlewares.yml
# Test outpost endpoint directly
curl -sI http://authentik-server:9000/outpost.goauthentik.io/auth/traefik
```

**OIDC (login fails, callback errors):**
- Verify client ID/secret match between Authentik provider and service config
- Check redirect URI matches exactly
- Test discovery URL: `curl -s https://auth.willflix.org/application/o/{slug}/.well-known/openid-configuration | jq .`

### 7. Dependencies

Check upstream services if the target depends on them:

```bash
docker compose ps postgres redis authentik-server smtp-relay
docker compose logs --tail=20 postgres | grep -i error
```

### 8. Resources

```bash
df -h /docker /Volumes/Media
free -h
docker system df
docker stats --no-stream {service}
```

| Symptom | Fix |
|---------|-----|
| Disk full | `docker system prune`, clean logs, expand volume |
| OOM killed | Add `deploy.resources.limits.memory` or increase |
| High CPU | Check for runaway process, add CPU limit |

### 9. Propose and Apply Fix

Based on findings, apply the fix. Always specify service name:

```bash
sudo systemctl restart {service}
# or for compose-level changes:
docker compose up -d {service}
```

### 10. Verify Fix

Re-run the failing checks from earlier steps. Confirm:
- Container is `Up`
- Logs are clean
- Web UI is reachable
- Auth flow works (if applicable)

## Common Failure Patterns

| Symptom | Usual Cause | Quick Fix |
|---------|------------|-----------|
| 502 Bad Gateway | Container down or wrong port | Restart, check port label |
| 504 Gateway Timeout | Service starting slowly | Wait, check healthcheck |
| Redirect loop | Auth misconfigured | Check middleware, cookie domain |
| Connection refused | Service not listening | Check logs for startup errors |
| Name not resolving | DNS/Traefik issue | Check Host() rule, cert status |
| Intermittent 502 | Container restarting | Check logs for crash cause |
| VPN service offline | gluetun disconnected | `docker compose restart vpn` |
