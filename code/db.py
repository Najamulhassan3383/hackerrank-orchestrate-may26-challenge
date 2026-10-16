"""Connect to the local pgvector database and keep the schema current."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
INIT_SQL = ROOT / "db" / "init.sql"
DEFAULT_URL = "postgresql://support:support@localhost:5432/support"

DEFAULT_MODEL_NAME = "amazon.titan-embed-text-v2:0"
DEFAULT_STRATEGY_NAME = "heading_max8000_overlap200"
DEFAULT_DIMENSIONS = 1024


def database_url() -> str:
    load_dotenv(ROOT / ".env")
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())


def _legacy_chunks_exists(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'chunks'
        """
    )
    if cur.fetchone() is None:
        return False
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'chunks'
          AND column_name = 'parent_id'
        """
    )
    return cur.fetchone() is None


def ensure_schema(conn: psycopg.Connection | None = None) -> None:
    """Apply db/init.sql. Replace a pre-linkage chunks table if still on the old shape."""
    sql = INIT_SQL.read_text(encoding="utf-8")
    owns_conn = conn is None
    if owns_conn:
        conn = connect()
    assert conn is not None
    try:
        with conn.cursor() as cur:
            if _legacy_chunks_exists(cur):
                cur.execute("DROP TABLE IF EXISTS chunks CASCADE")
            cur.execute(sql)
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def get_or_create_model(
    conn,
    name: str,
    *,
    provider: str = "bedrock",
    dimensions: int = DEFAULT_DIMENSIONS,
    notes: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO embedding_models (name, provider, dimensions, notes)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
                SET provider = EXCLUDED.provider,
                    dimensions = EXCLUDED.dimensions,
                    notes = COALESCE(EXCLUDED.notes, embedding_models.notes)
            RETURNING id
            """,
            (name, provider, dimensions, notes),
        )
        row = cur.fetchone()
    conn.commit()
    assert row is not None
    return int(row[0])


def get_or_create_strategy(
    conn,
    name: str,
    *,
    description: str | None = None,
    max_chars: int | None = None,
    overlap_chars: int | None = None,
    notes: str | None = None,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO embedding_strategies (
                name, description, max_chars, overlap_chars, notes
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (name) DO UPDATE
                SET description = COALESCE(EXCLUDED.description, embedding_strategies.description),
                    max_chars = COALESCE(EXCLUDED.max_chars, embedding_strategies.max_chars),
                    overlap_chars = COALESCE(
                        EXCLUDED.overlap_chars, embedding_strategies.overlap_chars
                    ),
                    notes = COALESCE(EXCLUDED.notes, embedding_strategies.notes)
            RETURNING id
            """,
            (name, description, max_chars, overlap_chars, notes),
        )
        row = cur.fetchone()
    conn.commit()
    assert row is not None
    return int(row[0])


def resolve_model_id(conn, name: str | None = None) -> int:
    load_dotenv(ROOT / ".env")
    model_name = name or os.environ.get("BEDROCK_EMBEDDING_MODEL") or DEFAULT_MODEL_NAME
    return get_or_create_model(conn, model_name, dimensions=DEFAULT_DIMENSIONS)


def resolve_strategy_id(conn, name: str | None = None) -> int:
    strategy_name = name or DEFAULT_STRATEGY_NAME
    return get_or_create_strategy(
        conn,
        strategy_name,
        description=(
            "Keep articles <= 8000 chars whole; else split on ## then paragraphs "
            "with 200-char overlap; title+heading prefix on body"
        ),
        max_chars=8000,
        overlap_chars=200,
    )


def upsert_document(conn, company: str, path: str, title: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (company, path, title)
            VALUES (%s, %s, %s)
            ON CONFLICT (path) DO UPDATE
                SET company = EXCLUDED.company,
                    title = EXCLUDED.title
            RETURNING id
            """,
            (company, path, title),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def ping() -> tuple[str, int, int, int]:
    ensure_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            version = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM chunks")
            chunk_count = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM embedding_models")
            model_count = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM embedding_strategies")
            strategy_count = cur.fetchone()
    if version is None or chunk_count is None or model_count is None or strategy_count is None:
        raise RuntimeError("pgvector extension or linkage tables are missing")
    return (
        str(version[0]),
        int(chunk_count[0]),
        int(model_count[0]),
        int(strategy_count[0]),
    )


if __name__ == "__main__":
    vector_version, chunk_count, model_count, strategy_count = ping()
    print(
        f"connected, pgvector {vector_version}, chunks {chunk_count}, "
        f"models {model_count}, strategies {strategy_count}"
    )
