CREATE EXTENSION IF NOT EXISTS vector;

-- Catalog of embedding models under test (Titan, future models, etc.).
CREATE TABLE IF NOT EXISTS embedding_models (
    id smallserial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    provider text NOT NULL DEFAULT 'bedrock',
    dimensions integer NOT NULL DEFAULT 1024,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Catalog of chunking / embedding strategies under test.
CREATE TABLE IF NOT EXISTS embedding_strategies (
    id smallserial PRIMARY KEY,
    name text NOT NULL UNIQUE,
    description text,
    max_chars integer,
    overlap_chars integer,
    notes text,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- One row per source article. Chunks point here as their parent.
CREATE TABLE IF NOT EXISTS documents (
    id bigserial PRIMARY KEY,
    company text,
    path text NOT NULL UNIQUE,
    title text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id bigserial PRIMARY KEY,
    parent_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    company text,
    path text NOT NULL,
    title text,
    heading text,
    body text NOT NULL,
    content_hash text NOT NULL,
    chunk_index integer NOT NULL DEFAULT 0,
    sister_ids bigint[] NOT NULL DEFAULT '{}',
    char_count integer NOT NULL DEFAULT 0,
    word_count integer NOT NULL DEFAULT 0,
    token_count integer NOT NULL DEFAULT 0,
    model_id smallint NOT NULL REFERENCES embedding_models (id),
    strategy_id smallint NOT NULL REFERENCES embedding_strategies (id),
    embedding vector(1024),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_id, strategy_id, path, content_hash),
    UNIQUE (model_id, strategy_id, parent_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_company_idx
    ON chunks (company);

CREATE INDEX IF NOT EXISTS chunks_parent_idx
    ON chunks (parent_id);

CREATE INDEX IF NOT EXISTS chunks_model_strategy_idx
    ON chunks (model_id, strategy_id);

CREATE INDEX IF NOT EXISTS chunks_sister_ids_gin
    ON chunks USING gin (sister_ids);

-- Defaults matching the current pipeline.
INSERT INTO embedding_models (name, provider, dimensions, notes)
VALUES (
    'amazon.titan-embed-text-v2:0',
    'bedrock',
    1024,
    'Default Titan V2 embedding used by code/embed.py'
)
ON CONFLICT (name) DO NOTHING;

INSERT INTO embedding_strategies (name, description, max_chars, overlap_chars, notes)
VALUES (
    'heading_max8000_overlap200',
    'Keep articles <= 8000 chars whole; else split on ## then paragraphs with 200-char overlap; title+heading prefix on body',
    8000,
    200,
    'Default strategy implemented in code/chunking.py'
)
ON CONFLICT (name) DO NOTHING;
