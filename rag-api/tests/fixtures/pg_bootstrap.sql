-- Test-only stand-in for the BE tables the AI service depends on.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id uuid NULL,
    status text NOT NULL
);

CREATE OR REPLACE VIEW ai_source_states AS
SELECT 'KnowledgeSource'::text AS kind,
       id,
       id AS version_id,
       organization_id,
       NULL::text AS visibility,
       NULL::text AS content_hash,
       NULL::text AS source_uri,
       (status = 'Approved') AS eligible,
       status
FROM knowledge_sources;
