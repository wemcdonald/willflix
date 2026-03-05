# Phase 3: Media Health Monitoring — Design

**Date**: 2026-03-04
**Status**: Approved
**PRD**: `docs/lafayette-health-monitoring-prd.md`, Phase 3 (media intelligence)
**Depends on**: Phase 1 (willflix-notify), Phase 2a (monitoring)

---

## Goals

Detect unexpected media changes (accidental deletions, failed imports, software misbehavior) and distinguish them from routine operations (quality upgrades, format changes). Monitor Sonarr/Radarr/NZBGet for systematic errors.

**Deliverables:**
- `lib/` — shared Python library (LLM wrapper, notification helper, config loader)
- `bin/cron/check_media_changes` — intelligent snapraid diff analysis with LLM classification
- `bin/cron/check_media_apps` — Sonarr/Radarr/NZBGet API health monitoring
- Integration with `snapraid_daily` (replaces `check_for_deletes`)

---

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | JSON API parsing, LLM integration, shared library — all painful in bash |
| LLM provider | Claude Haiku (default), vendor-neutral wrapper | Cheap, fast, good at classification. Easy to swap providers. |
| Change classification | LLM for all non-trivial changes | Numeric heuristics can't distinguish "5 episodes replaced with 5 better episodes" from "5 episodes of Show A replaced with 5 episodes of Show B" |
| Media app monitoring | Threshold-based checks initially, LLM-ready for pattern detection later | Start simple, add intelligence when we see what errors look like |
| Shared code | `lib/` directory at repo root | Both scripts and future tools share LLM, notify, and config code |
| Catalog database | None | Snapraid diff already tracks changes. No need to maintain our own inventory. |

---

## Shared Library (`lib/`)

```
lib/
├── __init__.py
├── llm.py          # Vendor-neutral LLM wrapper
├── notify.py       # Python wrapper around willflix-notify
└── config.py       # Loads willflix-notify.config + secrets
```

### `llm.py`

- `ask(prompt, system=None) → str` — single function, returns text response
- Reads provider from config: `LLM_PROVIDER=anthropic` (or `openai`, `gemini`)
- Reads API key from secrets: `/willflix/secrets/anthropic_api_key` (etc.)
- Default model: `claude-haiku-4-5-20251001`
- Fallback on failure: returns `None` (callers handle gracefully)
- No streaming, no tools, no conversation — just prompt in, text out

### `notify.py`

- `notify(severity, key, subject, body)` — calls `willflix-notify` via subprocess
- Keeps Python scripts from having to shell out manually

### `config.py`

- Loads `etc/willflix-notify.config` (shell-style KEY=VALUE)
- Provides access to secrets directory path
- Reads any media-app-specific config (API URLs, thresholds)

---

## `check_media_changes` — Snapraid Diff Analysis

**Runs from**: `snapraid_daily`, replacing `check_for_deletes`
**Schedule**: Mon–Sat 1am (same as current)

### How it works

1. Run `snapraid diff` and capture output
2. Parse added/deleted/moved/updated files from the diff output
3. Group changes by parent directory (show name, movie name)
4. For each directory with meaningful changes (not single-file adds):
   - Build a summary: files deleted, files added, files moved
   - Ask the LLM: "Classify these changes as: routine upgrade, reorganization, partial loss, or significant loss. One-line summary with the show/movie name."
5. Aggregate results:
   - **Routine/upgrade**: log only, no alert
   - **Partial loss**: WARNING alert with LLM summary and affected show/movie
   - **Significant loss**: CRITICAL alert, abort sync (same safety as current check_for_deletes)
6. If LLM is unavailable: fall back to net-delete count threshold (current behavior), include raw file lists in alert for manual review

### Exit behavior

- Exit 0: safe to proceed with sync
- Exit 1: abort sync (significant unexplained deletions)

Same contract as current `check_for_deletes`, so `snapraid_daily` doesn't need structural changes.

### LLM prompt (example)

```
The following file changes were detected in /Volumes/Media/TV/Breaking Bad/:

Deleted:
  S01E05.720p.BluRay.x264-GROUP.mkv (4.2GB)
  S01E06.720p.BluRay.x264-GROUP.mkv (3.8GB)

Added:
  S01E05.1080p.WEB-DL.x265-GROUP.mkv (2.1GB)
  S01E06.1080p.WEB-DL.x265-GROUP.mkv (1.9GB)

Classify these changes as one of:
- routine_upgrade: same content replaced with better quality/smaller format
- reorganization: files moved or renamed but content preserved
- partial_loss: some content lost, some replaced or added
- significant_loss: content deleted with no equivalent replacement

Reply with JSON: {"classification": "...", "summary": "one-line human-readable summary"}
```

---

## `check_media_apps` — API Health Monitor

**Runs from**: cron every 6 hours
**Schedule**: `0 */6 * * *`

### Checks

**Sonarr** (`localhost:8989/api/v3/`):
- Queue: items with `errorMessage` or `status=warning` — count by show name
- History: failed imports in last 24h — count by show name
- Disk space: warnings from `/api/v3/rootfolder`
- Alert if: >3 failed imports in 24h, or queue errors stuck >6h

**Radarr** (`localhost:7878/api/v3/`):
- Same pattern as Sonarr — queue errors, failed imports, disk space
- Alert if: >3 failed imports in 24h, or queue errors stuck >6h

**NZBGet** (`localhost:6789/jsonrpc/`):
- Check for downloads with `ParStatus=FAILURE` or `UnpackStatus=FAILURE`
- Check for downloads completed but stuck (not picked up by Sonarr/Radarr)
- Alert if: >3 failures in 24h, or completed downloads not imported >12h

**General**:
- Inactivity check: if Sonarr/Radarr haven't successfully imported anything in 7 days, WARNING (might indicate a silent failure)
- API unreachable: CRITICAL (service is down)

### Alert format

```
Subject: Sonarr: 8 failed imports in the last 24 hours

Affected shows:
  Breaking Bad — 3 failed imports (disk full)
  Better Call Saul — 5 failed imports (permission denied)

Check:
  Sonarr UI: http://localhost:8989/queue
  Logs: docker logs sonarr --tail 50
```

### API keys

Sonarr and Radarr API keys are already in `/willflix/secrets/` (`sonarr_api_key`, `radarr_api_key`). NZBGet uses basic auth configured in its container.

---

## Configuration

New config values in `etc/willflix-notify.config`:

```bash
# Media app API endpoints (defaults for standard Docker setup)
SONARR_URL="http://localhost:8989"
RADARR_URL="http://localhost:7878"
NZBGET_URL="http://localhost:6789"

# LLM for media change classification
LLM_PROVIDER="anthropic"
LLM_MODEL="claude-haiku-4-5-20251001"

# check_media_apps thresholds
MEDIA_FAILED_IMPORT_THRESHOLD=3    # alert if more than N in 24h
MEDIA_QUEUE_STUCK_HOURS=6          # alert if queue errors older than N hours
MEDIA_INACTIVITY_DAYS=7            # alert if no successful imports in N days
```

---

## Integration with snapraid_daily

Current flow:
```
snapraid_daily → check_for_deletes (bash) → snapraid sync
```

New flow:
```
snapraid_daily → check_media_changes (python) → snapraid sync
```

`snapraid_daily` calls `check_media_changes` instead of `check_for_deletes`. Same exit code contract. The bash script `check_for_deletes` is retired.

---

## Crontab additions

```cron
# Media app health checks (every 6 hours)
0 */6 * * * /willflix/bin/cron/check_media_apps
```

`check_media_changes` does NOT get its own cron entry — it runs from `snapraid_daily`.

---

## File changes

**New:**
- `lib/__init__.py`
- `lib/llm.py`
- `lib/notify.py`
- `lib/config.py`
- `bin/cron/check_media_changes`
- `bin/cron/check_media_apps`

**Modified:**
- `bin/cron/snapraid_daily` — call `check_media_changes` instead of `check_for_deletes`
- `etc/willflix-notify.config` — add media app URLs, LLM config, thresholds
- `etc/root-crontab` — add `check_media_apps` entry

**Retired:**
- `bin/cron/check_for_deletes` — replaced by `check_media_changes`

---

## What this does NOT cover

- Real-time monitoring (cron is sufficient)
- Plex integration (if files are on disk and Sonarr/Radarr are healthy, Plex finds them)
- Individual download failure alerts (only patterns)
- Media catalog database (snapraid diff is the source of truth)
- LLM pattern detection for media app errors (infrastructure is ready, add when needed)
