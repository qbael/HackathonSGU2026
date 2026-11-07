CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ai_search_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version uuid NOT NULL DEFAULT gen_random_uuid()
);
INSERT INTO ai_search_state (singleton) VALUES (true) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS ai_items (
    item_id uuid PRIMARY KEY,
    document_version bigint NOT NULL CHECK (document_version > 0),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    tombstone boolean NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_documents (
    item_id uuid NOT NULL REFERENCES ai_items(item_id),
    model_id text NOT NULL,
    model_revision text NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions > 0),
    processing_profile text NOT NULL,
    document_version bigint NOT NULL CHECK (document_version > 0),
    source_id uuid NOT NULL,
    source_version bigint NOT NULL CHECK (source_version > 0),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    found_area text NOT NULL,
    found_on date,
    found_from timestamptz,
    found_until timestamptz,
    search_terms tsvector NOT NULL,
    location_tokens text[] NOT NULL,
    embedding vector NOT NULL CHECK (vector_dims(embedding) = dimensions),
    PRIMARY KEY (model_id, model_revision, dimensions, processing_profile, item_id, source_id)
);

CREATE INDEX IF NOT EXISTS ai_documents_item ON ai_documents(item_id);

-- Upgrade existing one-source databases atomically; rerunning leaves the same key.
DO $$
BEGIN
    IF (SELECT pg_get_constraintdef(oid) FROM pg_constraint
        WHERE conrelid = 'ai_documents'::regclass AND conname = 'ai_documents_pkey')
        NOT LIKE '%source_id%' THEN
        ALTER TABLE ai_documents DROP CONSTRAINT ai_documents_pkey;
        ALTER TABLE ai_documents ADD PRIMARY KEY
            (model_id, model_revision, dimensions, processing_profile, item_id, source_id);
    END IF;
END $$;
