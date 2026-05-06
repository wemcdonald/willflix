# OpenBrain (OB1) — Willflix Self-Hosted Install Plan

**Created:** 2026-04-30
**Source:** https://github.com/NateBJones-Projects/OB1
**Setup log:** `openbrain-setup-log.md` (running notes/decisions)

## What OpenBrain Is

Personal AI memory layer. Single Postgres+pgvector table (`thoughts`) +
remote MCP server. Any MCP-capable client (Claude Desktop/Web, ChatGPT,
Claude Code, Cursor) reads/writes via one URL → unified memory across all
AI tools.

Upstream architecture = Supabase Postgres + Supabase Edge Functions
(Deno). Two Edge Functions: `ingest-thought` (Slack capture only) and
`open-brain-mcp` (the MCP server, three tools: `search_thoughts`,
`list_thoughts`, `thought_stats`, `capture_thought`).

## Hard Overrides (per user)

| Override | Implication |
|---|---|
| Install in willflix | Service lives in `/willflix/docker/compose.yml`, follows willflix conventions |
| Use local Postgres, NOT Supabase | Skip Supabase entirely. Reuse existing `postgres` container. Add pgvector. Drop RLS. |
| Standard willflix dockerized service | Custom image under `/willflix/docker/images/openbrain-mcp/`, Traefik on `brain.willflix.org`, `/run/secrets/*` mount pattern |
| Secrets in `/willflix/secrets` | git-crypt encrypted; nothing in env files in repo |
| Maintain implementation plan + setup log | This file + `openbrain-setup-log.md` |
| User AFK → push notifications for blockers | `willflix-notify-send --channel pushover ...` |

## Architecture Decisions

### 1. Postgres image: switch `postgres:17` → `pgvector/pgvector:pg17`

The current container runs vanilla Postgres 17 without pgvector.
`pgvector/pgvector:pg17` is the official pgvector-bundled image, same
PG17 major, same data dir layout — drop-in swap, no dump/restore.

**Existing dependents:** authentik (server+worker), nextcloud,
health-server. All use plain SQL, no Postgres-version-pinned features
unique to vanilla postgres. Should restart cleanly.

**Mitigation:** Take a `pg_dumpall` snapshot before swapping, in case
rollback needed. Restart authentik/nextcloud after to confirm health.

### 2. Database isolation

Create:
- DB: `openbrain`
- User: `openbrain` with password from `/willflix/secrets/openbrain_postgres_password`
- Extension: `vector` (pgvector)
- Skip RLS — single-user, single-app DB. The DB user IS the service-role-equivalent.

### 3. MCP server: port from Edge Function → Deno container

Upstream `server/index.ts` (~440 lines) is Deno + Hono + supabase-js.

**Approach:** Run the same `index.ts` under `denoland/deno:alpine`,
replace the `@supabase/supabase-js` client with Deno's `postgres`
driver. Two RPC calls (`match_thoughts`, `upsert_thought`) become
direct `SELECT * FROM match_thoughts(...)` / `SELECT upsert_thought(...)`
queries. Two `.from('thoughts').select()` calls become raw SELECTs. Auth
path (`?key=` query param) unchanged.

Why port instead of running PostgREST: keeps the deployment one
container instead of two, avoids a JWT/role-translation layer, and the
SQL surface is small (4 query sites). Tradeoff: drift from upstream code
when they update it. Mitigation: keep the diff minimal + scoped to the
DB-client section.

Image: `/willflix/docker/images/openbrain-mcp/`
Files: `Dockerfile`, `index.ts` (ported), `deno.json` (with `postgres` import)

### 4. Routing: `brain.willflix.org`, NO authentik middleware

MCP clients (Claude Desktop, ChatGPT) cannot send custom auth headers,
and they do NOT do interactive OAuth. Auth is the
`?key=<MCP_ACCESS_KEY>` query param baked into the connection URL.

→ Traefik routes `brain.willflix.org` straight to the container, with
TLS via `le` resolver but NO `authentik-forward@file` middleware. Access
control = the access key, which we treat as a long secret.

### 5. LLM provider: OpenAI direct (deviation from upstream)

Upstream uses OpenRouter as a proxy. User has existing
`openai_api_key` — reuse it. Swap base URL
`https://openrouter.ai/api/v1` → `https://api.openai.com/v1`. Same
models (`text-embedding-3-small`, `gpt-4o-mini`), same cost, no extra
signup. Tradeoff: future model swaps to non-OpenAI providers require
code edits. Acceptable.

### 6. Multi-user (will + robin)

Single deployment, per-user access keys. Schema gains `user_id text NOT
NULL`. All queries scoped by user. One secret file
`openbrain_mcp_keys` containing JSON map `{"<key1>":"will","<key2>":"robin"}`.
Server resolves user from `?key=` param, injects into every DB call.

Rotation: regenerate one user's key without affecting the other.
Future-proof: reserve `user_id = "shared"` for household facts (not
exposed in v1 tools, but schema supports it).

### 7. Skip Slack capture for v1

Upstream `ingest-thought` Edge Function captures from Slack. Out of
scope for initial install — MCP server handles read+write itself.
Revisit if/when desired.

## Components Inventory

| Item | Location |
|---|---|
| Plan (this file) | `/willflix/docs/openbrain-setup.md` |
| Running log | `/willflix/docs/openbrain-setup-log.md` |
| Custom image | `/willflix/docker/images/openbrain-mcp/` |
| Compose service | added to `/willflix/docker/compose.yml` |
| Postgres password | `/willflix/secrets/openbrain_postgres_password` |
| MCP access keys (JSON map) | `/willflix/secrets/openbrain_mcp_keys` |
| OpenAI API key | `/willflix/secrets/openai_api_key` (already exists) |
| Schema migration SQL | `/willflix/docker/images/openbrain-mcp/schema.sql` (also kept in repo as record) |
| Service monitoring entry | added to `/willflix/etc/willflix-services.conf` |

## Step-by-Step Plan

1. **Plan + log** (this file).
2. **Snapshot postgres** — `pg_dumpall` to `/willflix/docker/appdata/postgres/pre-pgvector-dump.sql`.
3. **Switch Postgres image** to `pgvector/pgvector:pg17` in compose.yml. Restart. Verify authentik/nextcloud/health-server still healthy.
4. **Provision openbrain DB**:
   - Generate password (`openssl rand -hex 32`)
   - `CREATE ROLE openbrain ... ; CREATE DATABASE openbrain OWNER openbrain;`
   - `\c openbrain ; CREATE EXTENSION vector;`
   - Apply schema (`thoughts` table, indexes, `match_thoughts`, `content_fingerprint`, `upsert_thought`, `update_updated_at` trigger)
5. **Generate two MCP access keys** (`openssl rand -hex 32` ×2). Build JSON `{"<key_will>":"will","<key_robin>":"robin"}` and store at `/willflix/secrets/openbrain_mcp_keys`.
6. **OpenAI key already present** at `/willflix/secrets/openai_api_key`.
7. **Build openbrain-mcp image**:
   - Dockerfile: `FROM denoland/deno:alpine-2.x`, `COPY deno.json index.ts /app/`, cache deps, `CMD ["run","--allow-net","--allow-env","--allow-read","/app/index.ts"]`
   - Port `index.ts`: replace supabase-js with `https://deno.land/x/postgres` driver. Two `.rpc()` → SQL function calls; two `.from()` → SELECTs. Same Hono auth wrapper. Listen on :8000.
   - `deno.json`: drop `@supabase/supabase-js`, keep hono+mcp+zod, add `postgres`.
8. **Add compose service** with secrets, env vars, traefik labels (no authentik middleware), `depends_on: [postgres]`, `traefik_public` network.
9. **Add top-level secrets stanzas** in compose.yml for the 3 new files.
10. **Boot**: `docker compose up -d openbrain-mcp`, watch logs.
11. **Smoke test**: curl health endpoint, JSON-RPC `tools/list`, `capture_thought`, `search_thoughts`. Verify row in `thoughts`.
12. **Register monitoring**: add `openbrain-mcp` entry to `/willflix/etc/willflix-services.conf` (tier: warning, type: docker).
13. **Notify user** with the MCP Connection URL: `https://brain.willflix.org/?key=<key>`.

## User Decisions (resolved 2026-04-30)

- Users: `will` + `robin`
- LLM provider: OpenAI direct (existing `openai_api_key`)
- Subdomain: `brain.willflix.org` confirmed
- Slack capture: skipped for v1

## Risks / Watch Items

- **Postgres image swap** — All shared-DB services share `appdata/postgres/data`. pgvector image uses identical PG17 binaries + adds the extension; should be a no-op for existing DBs. Pre-snapshot taken anyway. Health check after restart: authentik login still works, nextcloud still serves.
- **Upstream drift** — Forking `index.ts` means we have to manually pull upstream changes. Acceptable given small surface; will note version pinned in setup log.
- **Access key in URL** — URL gets logged in Traefik access logs. Acceptable per upstream design (this is how all MCP clients work). Mitigation: set Traefik `accesslog.format` to suppress query strings if it becomes a concern. Out of scope for v1.
- **MCP endpoint exposed publicly** — Anyone with the URL+key can read/write the thoughts DB. Treated as the auth boundary. Rotation: regenerate the secret + restart.
