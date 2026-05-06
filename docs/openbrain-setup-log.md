# OpenBrain Setup — Running Log

Companion to `openbrain-setup.md`. Append-only record of major steps,
decisions, and surprises during install.

## 2026-04-30

### Research phase

- Fetched + indexed OB1 docs: README, getting-started, FAQ, AI-assisted setup, CLAUDE.md, server/index.ts (440 lines), server/deno.json.
- Confirmed schema: `thoughts(id uuid, content text, embedding vector(1536), metadata jsonb, content_fingerprint text, created_at, updated_at)` + 3 indexes (hnsw vector_cosine_ops, gin metadata, btree created_at) + `match_thoughts()` + `upsert_thought()` + `update_updated_at()` trigger.
- Confirmed MCP server is single-file Deno + Hono + supabase-js, 4 DB call sites, auth via `?key=` query param. Tools: search_thoughts, list_thoughts, thought_stats, capture_thought.
- Reviewed willflix conventions: postgres:17 already in compose, secrets pattern is `/willflix/secrets/<name>` mounted to `/run/secrets/<name>`, Traefik labels with `authentik-forward@file` (will OMIT here since MCP needs ?key= auth path).
- Existing pg-dependent services: authentik-server, authentik-worker, nextcloud, health-server.
- Existing secrets that exist (so do NOT recreate): postgres_password, openai_api_key. Need to ADD: openbrain_postgres_password, openbrain_mcp_access_key, openrouter_api_key.

### Decisions logged in plan

- Switch postgres image: `postgres:17` → `pgvector/pgvector:pg17` (same PG17, drop-in).
- Port `server/index.ts` to use Deno postgres driver (replace supabase-js, ~4 call sites).
- Skip RLS (single-app DB).
- Skip Slack capture for v1.
- LLM provider: OpenRouter (no swap; upstream-faithful).
- Routing: `brain.willflix.org`, NO authentik forwardauth (auth = `?key=`).

### User decisions (received in chat)

- Users: `will`, `robin`
- LLM provider: OpenAI direct (existing `openai_api_key`) — deviation from upstream's OpenRouter. Base URL swap only, same models.
- Subdomain `brain.willflix.org` confirmed.
- Slack capture skipped for v1.

### Multi-user schema implications

- `thoughts.user_id text NOT NULL` added to schema.
- Composite indexes / per-user filtering on all queries.
- `match_thoughts` + `upsert_thought` SQL functions take `p_user_id`.
- Auth: server loads `/run/secrets/openbrain_mcp_keys` (JSON map), resolves `?key=` → user, scopes every DB call.
- Reserve `user_id = "shared"` namespace for future household-shared thoughts (not exposed in v1 tools).

### Implementation summary

1. **Postgres image swap** — `postgres:17` → `pgvector/pgvector:pg17-trixie` (matched glibc 2.41 of original data; pg17 vanilla swap caused no-op collation warning when first tried with bookworm tag, switched to trixie). Pre-snapshot at `/willflix/docker/appdata/postgres-backups/pre-pgvector-2026-04-30.sql.gz` (25M, 324 COPY blocks). All dependents (authentik, nextcloud, health-server) restarted clean.
2. **Provisioned** `openbrain` role + DB. Vector extension created as superuser (only superuser can `CREATE EXTENSION vector`).
3. **Schema** lives in `/willflix/docker/images/openbrain-mcp/schema.sql` — source of truth, applied via `psql -U openbrain -d openbrain -f schema.sql`.
4. **Server port (Deno)** — replaced supabase-js with postgres.js via `https://deno.land/x/postgresjs@v3.4.5/mod.js`. Replaced OpenRouter with OpenAI (base URL swap, same models). Added `AsyncLocalStorage` to thread `user_id` from request → tool handlers without polluting tool inputSchema.
5. **Auth** — `/run/secrets/openbrain_mcp_keys` is a JSON object `{"<key>":"<user>"}`. Server reads at startup, builds Map, resolves on each request.
6. **Bug found + fixed during smoke test**: `ON CONFLICT (user_id, content_fingerprint)` requires the partial-index predicate `WHERE content_fingerprint IS NOT NULL`. Added to upsert_thought.
7. **Traefik routing fix**: had to add `traefik.docker.network=config_traefik_public` label — without it Traefik defaulted to the wrong network and produced 504s. Common willflix gotcha (other services that touch both `traefik_public` + `default` use the same label).
8. **Smoke test results** (all from external `https://brain.willflix.org`):
   - GET `/healthz` → 200 ok
   - GET `/` no key → 401 `{"error":"missing access key"}`
   - POST `/?key=BAD` → 401
   - POST `/?key=<will>` `tools/list` → 4 tools
   - POST `/?key=<will>` `capture_thought` → row inserted, embedding stored, metadata extracted by gpt-4o-mini
   - POST `/?key=<will>` `search_thoughts` → 57% match returned for own data
   - POST `/?key=<robin>` `search_thoughts` for will-only content → no hits (isolation verified)
   - POST `/?key=<robin>` `capture_thought` → row inserted as user `robin`
   - `list_thoughts`, `thought_stats`, topic-filter `list_thoughts` all return correct shape.
9. **Monitoring** — added to `/willflix/etc/willflix-services.conf` at tier `warning`.

### Open / followups

- Image references: `pgvector/pgvector:pg17-trixie` is unpinned to a release tag. Could pin to `0.8.2-pg17-trixie` for reproducibility. Left floating to match willflix's convention of `image: postgres:17` (also floating).
- Slack capture (`ingest-thought` Edge Function) skipped. Would be a second container if added.
- "shared" household namespace exists in schema (`user_id = "shared"` is just a string) but no tool exposes it. Adding would require either a `--shared` flag in capture/search or a separate set of tools.
- Auto-upgrade: openbrain-mcp will be picked up by nightly `update_containers` since `upgrade: false` not set. Image is built locally from this repo so updates only happen when we rebuild — no remote pull risk.
