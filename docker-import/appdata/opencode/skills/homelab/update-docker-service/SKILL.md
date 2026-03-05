---
name: update-docker-service
description: Use when upgrading, updating, or pulling a new version of a Docker service on the willflix.org homelab — also when the user says "bump", "pull latest", "new version available", or wants to check for updates
---

# Update Docker Service

## Overview

Cautious upgrade procedure for Docker services. Check for breaking changes before pulling, keep a rollback path, and verify after restart.

**Core principle:** Updates are not fire-and-forget. Always check changelogs and verify the service works after upgrading.

## Single Service Update

### 1. Check Current Version

```bash
docker compose images {service}    # from /docker/config
docker inspect {service} --format '{{.Image}}'
```

Note the current image ID/digest for rollback:
```bash
docker inspect {service} --format '{{.Image}}' > /tmp/{service}-previous-image
```

### 2. Research the Update

Before pulling, check for breaking changes:

| Source | What to Look For |
|--------|-----------------|
| GitHub releases page | Breaking changes, migration steps |
| Docker Hub tags | Available versions, `latest` vs pinned |
| Changelog / docs | Config format changes, deprecated env vars |
| Reddit / forums | Reports of issues with new version |

**Red flags that require extra care:**
- Major version bump (e.g., v3 -> v4)
- Database migration required
- Config file format change
- Dropped environment variables
- Changed default port

### 3. Pre-flight Checks

```bash
# Ensure appdata config is committed
cd /docker && git status

# If uncommitted config changes exist, commit first
git add -A && git commit -m "pre-upgrade: {service} config snapshot"
```

### 4. Pull New Image

```bash
docker compose pull {service}    # from /docker/config
```

### 5. Restart the Service

```bash
sudo systemctl restart {service}
```

This runs `docker compose down {service}` then `docker compose up -d {service}`, picking up the new image.

### 6. Verify

```bash
# Check it started cleanly
sudo systemctl status {service}
docker compose logs --tail=50 {service}

# Confirm new version
docker compose images {service}

# Test web UI
curl -sI https://{service}.willflix.org | head -5
```

Look for:
- Migration messages in logs (expected for DB-backed services)
- Error messages or crash loops
- Web UI loads and functions normally

### 7. Rollback (if broken)

If the update caused problems:

**Option A — Pin previous tag** (if you know it):
Edit `docker-compose.yml` to use the specific previous tag instead of `latest`, then:
```bash
docker compose up -d --force-recreate {service}    # from /docker/config
```

**Option B — Use cached image** (if still available locally):
```bash
# List local images
docker images | grep {service}
# Tag the old one and update compose to use it
```

**Option C — Restore config and recreate:**
```bash
cd /docker && git checkout -- appdata/{service}/
sudo systemctl restart {service}
```

## Bulk Updates

For updating multiple services at once:

```bash
# Pull all images at once (safe — doesn't restart anything)
docker compose pull service1 service2 service3    # from /docker/config

# Restart one at a time, verifying each
sudo systemctl restart service1
# verify service1 ...
sudo systemctl restart service2
# verify service2 ...
```

**Never restart all services simultaneously.** If something breaks, you won't know which update caused it.

## Pinned vs Latest Tags

| Approach | Pros | Cons |
|----------|------|------|
| `:latest` | Always current, simple | Surprise breaking changes |
| `:v2.10` | Predictable, deliberate upgrades | Must manually update tag |
| `:2025.6.4` | Exact version, fully reproducible | Most manual maintenance |

Most services in this stack use `:latest`. For critical services (Traefik, Authentik, Postgres), prefer pinned tags.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Update without checking changelog | Always research first — step 2 |
| Restart all services after bulk pull | Restart one at a time |
| No rollback plan | Note image digest before pulling |
| Forgot to commit config pre-upgrade | `git status` in /docker before pulling |
| Service needs DB migration but didn't run it | Check logs for migration instructions |
| Bare `docker compose up -d` | Always specify service name(s) |
