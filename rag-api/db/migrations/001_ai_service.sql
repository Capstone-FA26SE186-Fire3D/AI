-- Fire3D AI service: durable request table (Postgres 15+ / Supabase).
CREATE SCHEMA IF NOT EXISTS ai_service;

CREATE TABLE IF NOT EXISTS ai_service.requests (
    request_id            text PRIMARY KEY,
    operation             text NOT NULL,
    audience              text NOT NULL,
    input_hash            char(64) NOT NULL,
    payload               jsonb NOT NULL,
    status                text NOT NULL CHECK (status IN ('Received', 'Processing', 'Completed')),
    attempts              int NOT NULL DEFAULT 0,
    response              jsonb,
    usage_total           jsonb,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    processing_started_at timestamptz,
    completed_at          timestamptz
);

CREATE INDEX IF NOT EXISTS ix_requests_status_started
    ON ai_service.requests (status, processing_started_at);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fet3d_ai_service') THEN
        CREATE ROLE fet3d_ai_service NOLOGIN;
    END IF;
END
$$;

REVOKE ALL ON SCHEMA ai_service FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ai_service FROM PUBLIC;
GRANT USAGE ON SCHEMA ai_service TO fet3d_ai_service;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_service.requests TO fet3d_ai_service;
