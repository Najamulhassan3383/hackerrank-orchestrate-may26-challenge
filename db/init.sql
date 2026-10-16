CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
    id bigserial PRIMARY KEY,
    company text,
    path text NOT NULL,
    title text,
    heading text,
    body text NOT NULL,
    embedding vector(1024)
);
