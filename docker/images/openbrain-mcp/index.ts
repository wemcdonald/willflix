/**
 * OpenBrain MCP server — willflix self-hosted port.
 *
 * Differences from upstream OB1 server/index.ts:
 *   1. Storage: direct Postgres (postgres.js) instead of supabase-js.
 *   2. LLM: OpenAI direct (api.openai.com) instead of OpenRouter.
 *   3. Auth: per-user access keys via JSON map, not a single MCP_ACCESS_KEY.
 *   4. All thoughts queries scoped by user_id; AsyncLocalStorage threads
 *      the resolved user from request → tool handlers.
 *
 * Source-of-truth schema lives next to this file in schema.sql.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPTransport } from "@hono/mcp";
import { Hono } from "hono";
import { z } from "zod";
import postgres from "postgres";
import { AsyncLocalStorage } from "node:async_hooks";

// --- Config ---

function readSecret(name: string): string {
  const path = `/run/secrets/${name}`;
  return Deno.readTextFileSync(path).trim();
}

const POSTGRES_HOST = Deno.env.get("POSTGRES_HOST") ?? "postgres";
const POSTGRES_PORT = parseInt(Deno.env.get("POSTGRES_PORT") ?? "5432", 10);
const POSTGRES_DB = Deno.env.get("POSTGRES_DB") ?? "openbrain";
const POSTGRES_USER = Deno.env.get("POSTGRES_USER") ?? "openbrain";
const POSTGRES_PASSWORD = readSecret("openbrain_postgres_password");
const OPENAI_API_KEY = readSecret("openai_api_key");
const MCP_KEYS_RAW = readSecret("openbrain_mcp_keys");
const PORT = parseInt(Deno.env.get("PORT") ?? "8000", 10);

const OPENAI_BASE = "https://api.openai.com/v1";

// Map: access_key -> user_id
const KEY_TO_USER: Map<string, string> = (() => {
  const parsed = JSON.parse(MCP_KEYS_RAW) as Record<string, string>;
  const m = new Map<string, string>();
  for (const [k, u] of Object.entries(parsed)) m.set(k, u);
  return m;
})();

const sql = postgres({
  host: POSTGRES_HOST,
  port: POSTGRES_PORT,
  database: POSTGRES_DB,
  user: POSTGRES_USER,
  password: POSTGRES_PASSWORD,
  max: 8,
  idle_timeout: 30,
  connect_timeout: 10,
});

// --- User context plumbing ---

const userCtx = new AsyncLocalStorage<{ userId: string }>();
const getUser = (): string => {
  const v = userCtx.getStore();
  if (!v) throw new Error("user context missing — auth middleware not applied");
  return v.userId;
};

// --- LLM helpers ---

async function getEmbedding(text: string): Promise<number[]> {
  const r = await fetch(`${OPENAI_BASE}/embeddings`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "text-embedding-3-small",
      input: text,
    }),
  });
  if (!r.ok) {
    const msg = await r.text().catch(() => "");
    throw new Error(`OpenAI embeddings failed: ${r.status} ${msg}`);
  }
  const d = await r.json();
  return d.data[0].embedding;
}

async function extractMetadata(text: string): Promise<Record<string, unknown>> {
  const r = await fetch(`${OPENAI_BASE}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "gpt-4o-mini",
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: `Extract metadata from the user's captured thought. Return JSON with:
- "people": array of people mentioned (empty if none)
- "action_items": array of implied to-dos (empty if none)
- "dates_mentioned": array of dates YYYY-MM-DD (empty if none)
- "topics": array of 1-3 short topic tags (always at least one)
- "type": one of "observation", "task", "idea", "reference", "person_note"
Only extract what's explicitly there.`,
        },
        { role: "user", content: text },
      ],
    }),
  });
  const d = await r.json();
  try {
    return JSON.parse(d.choices[0].message.content);
  } catch {
    return { topics: ["uncategorized"], type: "observation" };
  }
}

// pgvector accepts a stringified array literal: "[0.1,0.2,...]"
const vectorLiteral = (v: number[]): string => `[${v.join(",")}]`;

// --- MCP Server ---

const server = new McpServer({ name: "open-brain", version: "1.0.0" });

server.registerTool(
  "search_thoughts",
  {
    title: "Search Thoughts",
    description:
      "Search captured thoughts by meaning. Use this when the user asks about a topic, person, or idea they've previously captured.",
    inputSchema: {
      query: z.string().describe("What to search for"),
      limit: z.number().optional().default(10),
      threshold: z.number().optional().default(0.5),
    },
  },
  async ({ query, limit, threshold }) => {
    try {
      const userId = getUser();
      const qEmb = await getEmbedding(query);
      const rows = await sql<
        Array<{
          id: string;
          content: string;
          metadata: Record<string, unknown>;
          similarity: number;
          created_at: Date;
        }>
      >`SELECT * FROM match_thoughts(
          ${userId}::text,
          ${vectorLiteral(qEmb)}::vector,
          ${threshold}::float,
          ${limit}::int,
          '{}'::jsonb
        )`;

      if (!rows.length) {
        return {
          content: [
            { type: "text" as const, text: "No thoughts matched that query." },
          ],
        };
      }

      const results = rows.map((t, i) => {
        const m = t.metadata || {};
        const parts = [
          `--- Result ${i + 1} (${(t.similarity * 100).toFixed(1)}% match) ---`,
          `Captured: ${new Date(t.created_at).toLocaleDateString()}`,
          `Type: ${m.type || "unknown"}`,
        ];
        if (Array.isArray(m.topics) && m.topics.length)
          parts.push(`Topics: ${(m.topics as string[]).join(", ")}`);
        if (Array.isArray(m.people) && m.people.length)
          parts.push(`People: ${(m.people as string[]).join(", ")}`);
        if (Array.isArray(m.action_items) && m.action_items.length)
          parts.push(`Actions: ${(m.action_items as string[]).join("; ")}`);
        parts.push(`\n${t.content}`);
        return parts.join("\n");
      });

      return {
        content: [
          {
            type: "text" as const,
            text: `Found ${rows.length} thought(s):\n\n${results.join("\n\n")}`,
          },
        ],
      };
    } catch (err: unknown) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${(err as Error).message}` },
        ],
        isError: true,
      };
    }
  },
);

server.registerTool(
  "list_thoughts",
  {
    title: "List Recent Thoughts",
    description:
      "List recently captured thoughts with optional filters by type, topic, person, or time range.",
    inputSchema: {
      limit: z.number().optional().default(10),
      type: z.string().optional()
        .describe(
          "Filter by type: observation, task, idea, reference, person_note",
        ),
      topic: z.string().optional().describe("Filter by topic tag"),
      person: z.string().optional().describe("Filter by person mentioned"),
      days: z.number().optional().describe("Only thoughts from the last N days"),
    },
  },
  async ({ limit, type, topic, person, days }) => {
    try {
      const userId = getUser();
      const filters: Record<string, unknown> = {};
      if (type) filters.type = type;
      if (topic) filters.topics = [topic];
      if (person) filters.people = [person];

      const rows = await sql<
        Array<{
          content: string;
          metadata: Record<string, unknown>;
          created_at: Date;
        }>
      >`
        SELECT content, metadata, created_at
        FROM thoughts
        WHERE user_id = ${userId}
          AND (${sql.json(filters)}::jsonb = '{}'::jsonb OR metadata @> ${sql.json(filters)}::jsonb)
          AND (${days ?? null}::int IS NULL OR created_at >= now() - (${days ?? 0}::int * interval '1 day'))
        ORDER BY created_at DESC
        LIMIT ${limit}
      `;

      if (!rows.length) {
        return {
          content: [
            { type: "text" as const, text: "No thoughts match those filters." },
          ],
        };
      }

      const results = rows.map((t, i) => {
        const m = t.metadata || {};
        const tags = Array.isArray(m.topics) ? (m.topics as string[]).join(", ") : "";
        return `${i + 1}. [${new Date(t.created_at).toLocaleDateString()}] (${m.type || "??"}${tags ? " - " + tags : ""})\n   ${t.content}`;
      });

      return {
        content: [
          {
            type: "text" as const,
            text: `${rows.length} recent thought(s):\n\n${results.join("\n\n")}`,
          },
        ],
      };
    } catch (err: unknown) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${(err as Error).message}` },
        ],
        isError: true,
      };
    }
  },
);

server.registerTool(
  "thought_stats",
  {
    title: "Thought Statistics",
    description:
      "Get a summary of all captured thoughts: totals, types, top topics, and people.",
    inputSchema: {},
  },
  async () => {
    try {
      const userId = getUser();
      const [{ count }] = await sql<Array<{ count: string }>>`
        SELECT COUNT(*)::text AS count FROM thoughts WHERE user_id = ${userId}
      `;
      const rows = await sql<Array<{ metadata: Record<string, unknown> }>>`
        SELECT metadata FROM thoughts WHERE user_id = ${userId}
      `;

      const types: Record<string, number> = {};
      const topics: Record<string, number> = {};
      const people: Record<string, number> = {};
      for (const r of rows) {
        const m = r.metadata || {};
        if (m.type) types[m.type as string] = (types[m.type as string] || 0) + 1;
        if (Array.isArray(m.topics))
          for (const t of m.topics)
            topics[t as string] = (topics[t as string] || 0) + 1;
        if (Array.isArray(m.people))
          for (const p of m.people)
            people[p as string] = (people[p as string] || 0) + 1;
      }
      const sortTop = (o: Record<string, number>): [string, number][] =>
        Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, 10);

      const fmt = (entries: [string, number][]): string =>
        entries.length
          ? entries.map(([k, n]) => `  ${k}: ${n}`).join("\n")
          : "  (none)";

      const text = [
        `Total thoughts: ${count}`,
        ``,
        `By type:`,
        fmt(sortTop(types)),
        ``,
        `Top topics:`,
        fmt(sortTop(topics)),
        ``,
        `Top people:`,
        fmt(sortTop(people)),
      ].join("\n");

      return { content: [{ type: "text" as const, text }] };
    } catch (err: unknown) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${(err as Error).message}` },
        ],
        isError: true,
      };
    }
  },
);

server.registerTool(
  "capture_thought",
  {
    title: "Capture Thought",
    description:
      "Save a new thought to the Open Brain. Generates an embedding and extracts metadata automatically. Use this when the user wants to save something to their brain directly from any AI client — notes, insights, decisions, or migrated content from other systems.",
    inputSchema: {
      content: z.string().describe(
        "The thought to capture — a clear, standalone statement that will make sense when retrieved later by any AI",
      ),
    },
  },
  async ({ content }) => {
    try {
      const userId = getUser();
      const [embedding, metadata] = await Promise.all([
        getEmbedding(content),
        extractMetadata(content),
      ]);

      const [upsert] = await sql<Array<{ upsert_thought: { id: string; fingerprint: string } }>>`
        SELECT upsert_thought(
          ${userId}::text,
          ${content}::text,
          ${sql.json({ metadata: { ...metadata, source: "mcp" } })}::jsonb
        ) AS upsert_thought
      `;
      const thoughtId = upsert.upsert_thought.id;

      await sql`
        UPDATE thoughts
        SET embedding = ${vectorLiteral(embedding)}::vector
        WHERE id = ${thoughtId} AND user_id = ${userId}
      `;

      const m = metadata as Record<string, unknown>;
      const tags = Array.isArray(m.topics)
        ? (m.topics as string[]).join(", ")
        : "uncategorized";
      return {
        content: [
          {
            type: "text" as const,
            text: `Captured thought (id: ${thoughtId})\nType: ${m.type || "observation"}\nTopics: ${tags}`,
          },
        ],
      };
    } catch (err: unknown) {
      return {
        content: [
          { type: "text" as const, text: `Error: ${(err as Error).message}` },
        ],
        isError: true,
      };
    }
  },
);

// --- Hono App ---

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-brain-key, accept, mcp-session-id",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
};

const app = new Hono();

app.options("*", (c) => c.text("ok", 200, corsHeaders));

app.get("/healthz", (c) => c.text("ok"));

app.all("*", async (c) => {
  const provided = c.req.header("x-brain-key") ||
    new URL(c.req.url).searchParams.get("key");
  if (!provided) {
    return c.json({ error: "missing access key" }, 401, corsHeaders);
  }
  const userId = KEY_TO_USER.get(provided);
  if (!userId) {
    return c.json({ error: "invalid access key" }, 401, corsHeaders);
  }

  return await userCtx.run({ userId }, async () => {
    const transport = new StreamableHTTPTransport();
    await server.connect(transport);
    return await transport.handleRequest(c);
  });
});

console.log(`openbrain-mcp listening on :${PORT} (users: ${[...KEY_TO_USER.values()].join(", ")})`);
Deno.serve({ port: PORT }, app.fetch);
