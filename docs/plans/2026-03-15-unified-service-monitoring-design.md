# Unified Service Monitoring Design

**Date**: 2026-03-15
**Status**: Draft
**Problem**: Docker and systemd checks use blocklist approach, causing false-positive alerts for services that are intentionally down. No severity tiers — everything is either ignored or CRITICAL/WARNING. Container name matching is exact-only.

## Design

### Single Config File: `etc/willflix-services.conf`

YAML format. Every monitored service is listed with a type and tier.

```yaml
services:
  traefik:
    type: docker
    tier: critical
  authentik-server:
    type: docker
    tier: critical
  plex:
    type: docker
    tier: warning
  snapraid-sync:
    type: systemd
    tier: info
  calibre:
    type: docker
    tier: ignore
```

**Types**:
- `docker` — check that a matching container is running and healthy
- `systemd` — check that the systemd unit is active
- `both` — check that both the container AND the systemd unit are up

**Tiers**:
- `critical` — CRITICAL severity (pushover emergency, repeats until ack'd)
- `warning` — WARNING severity (pushover normal)
- `info` — INFO severity (email only, no pushover)
- `ignore` — skip entirely (documents the service exists but we don't care)

Optional fields:
- `systemd: <unit-name>` — override when unit name differs from `<name>.service`

### Single Check Script: `bin/cron/willflix-check-services`

Replaces both `willflix-check-docker` and `willflix-check-systemd`. Runs every 15 minutes via cron.

**Logic per service**:
1. Skip if `tier: ignore`
2. If type includes `docker`: find a running container matching the service name (see matching below). Check for crash-loop (Restarting status) and unhealthy status.
3. If type includes `systemd`: check that `<name>.service` (or override) is active
4. For `type: both`: both checks must pass
5. Alert at the tier's severity level

**Container name matching**: A service name `foo` matches a container if:
- Container name is exactly `foo`, OR
- Container name matches pattern `<prefix>-foo-<digits>` (e.g. `config-foo-1`)

Implemented as regex: `^(.+-)?<name>(-\d+)?$`

**Crash-loop detection**: If a container's status starts with `Restarting`, alert as CRITICAL regardless of the service's configured tier (crash loops are always urgent).

**Unhealthy detection**: If a container is Up but `(unhealthy)`, alert at the configured tier's severity.

### Unknown Service Detection

After checking all configured services, scan for:
- Running/stopped containers not matched by any config entry
- Failed systemd units not matched by any config entry

These get an INFO alert with `--dedup-window 3d` so they only repeat every 3 days. Subject format: `Unknown container: <name> on <hostname>` / `Unknown failed unit: <name> on <hostname>`.

### Extend `willflix-notify` Dedup

Add `--dedup-window <duration>` flag (e.g. `3d`, `12h`, `1w`). When present, overrides the default daily-reset dedup logic with a simple time-since-last-alert check. The existing daily-reset behavior remains the default when the flag is absent.

### Retired Artifacts

- `bin/cron/willflix-check-docker` — deleted
- `bin/cron/willflix-check-systemd` — deleted
- `etc/willflix-check-docker.ignore` — deleted
- `etc/willflix-check-systemd.ignore` — deleted

Cron entries updated to call `willflix-check-services` instead.

### Ignored Services: One-Time Cleanup

As a one-time action during implementation (not part of the script), stop docker containers and disable systemd units for services in the `ignore` tier. They remain in compose.yml for easy restart if needed later.

Affected: calibre, whoami, adminer, webhook-handler, lazylibrarian, homarr, grocerybot, homebot, gastown, guildmaster, overseerr, copyparty, byparr.

## Service Config (initial)

```yaml
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
