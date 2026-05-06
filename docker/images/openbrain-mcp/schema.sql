-- OpenBrain schema (multi-user variant for willflix)
-- Apply to a fresh `openbrain` DB owned by the `openbrain` role.
-- Source-of-truth copy; deployed once during initial provisioning.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS thoughts (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id text NOT NULL,
  content text NOT NULL,
  embedding vector(1536),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  content_fingerprint text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_thoughts_embedding_hnsw
  ON thoughts USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_thoughts_metadata_gin
  ON thoughts USING gin (metadata);

CREATE INDEX IF NOT EXISTS idx_thoughts_user_created
  ON thoughts (user_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_thoughts_user_fingerprint
  ON thoughts (user_id, content_fingerprint)
  WHERE content_fingerprint IS NOT NULL;

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS thoughts_updated_at ON thoughts;
CREATE TRIGGER thoughts_updated_at
  BEFORE UPDATE ON thoughts
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Semantic search scoped per user.
CREATE OR REPLACE FUNCTION match_thoughts(
  p_user_id text,
  query_embedding vector(1536),
  match_threshold float DEFAULT 0.5,
  match_count int DEFAULT 10,
  filter jsonb DEFAULT '{}'::jsonb
) RETURNS TABLE (
  id uuid,
  content text,
  metadata jsonb,
  similarity float,
  created_at timestamptz
) LANGUAGE plpgsql AS $$
BEGIN
  RETURN QUERY
  SELECT t.id, t.content, t.metadata,
         1 - (t.embedding <=> query_embedding) AS similarity,
         t.created_at
  FROM thoughts t
  WHERE t.user_id = p_user_id
    AND t.embedding IS NOT NULL
    AND 1 - (t.embedding <=> query_embedding) > match_threshold
    AND (filter = '{}'::jsonb OR t.metadata @> filter)
  ORDER BY t.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;

-- Insert-or-merge by per-user content fingerprint. Embedding set in a follow-up UPDATE.
CREATE OR REPLACE FUNCTION upsert_thought(
  p_user_id text,
  p_content text,
  p_payload jsonb DEFAULT '{}'::jsonb
) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  v_fingerprint text;
  v_id uuid;
BEGIN
  v_fingerprint := encode(sha256(convert_to(
    lower(trim(regexp_replace(p_content, '\s+', ' ', 'g'))),
    'UTF8'
  )), 'hex');

  INSERT INTO thoughts (user_id, content, content_fingerprint, metadata)
  VALUES (p_user_id, p_content, v_fingerprint,
          COALESCE(p_payload->'metadata', '{}'::jsonb))
  ON CONFLICT (user_id, content_fingerprint)
  WHERE content_fingerprint IS NOT NULL
  DO UPDATE SET
    updated_at = now(),
    metadata = thoughts.metadata || COALESCE(EXCLUDED.metadata, '{}'::jsonb)
  RETURNING id INTO v_id;

  RETURN jsonb_build_object('id', v_id, 'fingerprint', v_fingerprint);
END;
$$;
