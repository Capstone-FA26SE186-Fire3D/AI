-- #91: storage the AI service indexes into. knowledge_chunks is the v7 table (Docs fire_evacuation_schema.sql) and is created only
-- where pgvector exists (Supabase installs it in schema extensions); elsewhere the step is skipped with a notice. The embedding
-- dimension and the ANN index stay open until the production embedding model is chosen, as in v7.
-- The backend owns this DDL. The AI service connects with a login that is a member of fet3d_ai_indexer: it may write chunks and
-- read ai_source_states (created by AddAiContractV2), nothing else (no service-role key, no tenant tables). Retrieval must still be limited to the source ids
-- and versions pinned in each request; ai_source_states only tells the indexer which sources to drop.
DO $$
DECLARE vector_schema text;r text;
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='fet3d_ai_indexer') THEN CREATE ROLE fet3d_ai_indexer NOLOGIN;END IF;
 SELECT n.nspname INTO vector_schema FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE t.typname='vector' ORDER BY n.nspname='extensions' DESC LIMIT 1;
 IF vector_schema IS NULL THEN RAISE NOTICE 'pgvector is not installed; knowledge_chunks is not created.';RETURN;END IF;
 EXECUTE format('CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID REFERENCES knowledge_sources(id) ON DELETE CASCADE NOT NULL,
    chunk_index INT NOT NULL,
    content     TEXT NOT NULL,
    locator     JSONB NOT NULL DEFAULT ''{}'',
    embedding   %I.vector,
    metadata    JSONB NOT NULL DEFAULT ''{}'',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source_id, chunk_index))',vector_schema);
 CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_source ON knowledge_chunks(source_id);
 ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
 REVOKE ALL ON knowledge_chunks FROM PUBLIC;
 FOREACH r IN ARRAY ARRAY['anon','authenticated','fire3d_api','fet3d_backend_executor'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN EXECUTE format('REVOKE ALL ON knowledge_chunks FROM %I',r);END IF;
 END LOOP;
 GRANT SELECT,INSERT,UPDATE,DELETE ON knowledge_chunks TO fet3d_ai_indexer;
 EXECUTE format('GRANT USAGE ON SCHEMA %I TO fet3d_ai_indexer',vector_schema);
 IF NOT EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='knowledge_chunks' AND policyname='ai_indexer') THEN
  CREATE POLICY ai_indexer ON knowledge_chunks TO fet3d_ai_indexer USING(true) WITH CHECK(true);
 END IF;
END $$;
