"""Connect to the local pgvector database."""

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "postgresql://support:support@localhost:5432/support"


def database_url() -> str:
    load_dotenv(ROOT / ".env")
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url())


def ping() -> tuple[str, int]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            version = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM chunks")
            count = cur.fetchone()
    if version is None or count is None:
        raise RuntimeError("pgvector extension or chunks table is missing")
    return str(version[0]), int(count[0])


if __name__ == "__main__":
    vector_version, chunk_count = ping()
    print(f"connected, pgvector {vector_version}, chunks {chunk_count}")
