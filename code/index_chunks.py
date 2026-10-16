"""Embed every chunk and store the vectors in Postgres.

A second run skips bodies that are already stored. Pass --rebuild to start over.
"""

import argparse
import hashlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from chunking import Chunk, load_chunks
from db import connect
from embed import embed_text, vector_literal

ROOT = Path(__file__).resolve().parent.parent
BATCH = 20
WORKERS = 4

INSERT = """
INSERT INTO chunks (company, path, title, heading, body, embedding)
VALUES (%s, %s, %s, %s, %s, %s::vector)
"""


def body_key(chunk: Chunk) -> tuple[str, str]:
    digest = hashlib.md5(chunk.body.encode("utf-8")).hexdigest()
    return chunk.path, digest


def stored_keys(conn) -> set[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute("SELECT path, md5(body) FROM chunks")
        return {(path, digest) for path, digest in cur.fetchall()}


def insert_batch(conn, chunks: list[Chunk], vectors: list[list[float]]) -> None:
    rows = [
        (chunk.company, chunk.path, chunk.title, chunk.heading, chunk.body, vector_literal(vector))
        for chunk, vector in zip(chunks, vectors)
    ]
    with conn.cursor() as cur:
        cur.executemany(INSERT, rows)
    conn.commit()


def index(rebuild: bool) -> None:
    load_dotenv(ROOT / ".env")
    print("reading articles", flush=True)
    chunks = load_chunks(progress=True)
    with connect() as conn:
        if rebuild:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE chunks RESTART IDENTITY")
            conn.commit()
            done: set[tuple[str, str]] = set()
        else:
            done = stored_keys(conn)

        pending = [chunk for chunk in chunks if body_key(chunk) not in done]
        print(
            f"chunks {len(chunks)}, already stored {len(chunks) - len(pending)}, to embed {len(pending)}",
            flush=True,
        )
        if not pending:
            return

        total = len(chunks)
        completed = total - len(pending)
        lock = threading.Lock()

        def embed_one(chunk: Chunk) -> list[float]:
            nonlocal completed
            vector = embed_text(chunk.body)
            with lock:
                completed += 1
                current = completed
                print(
                    f"api {current}/{total} remaining {total - current} {chunk.path}",
                    flush=True,
                )
            return vector

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for start in range(0, len(pending), BATCH):
                batch = pending[start : start + BATCH]
                vectors = list(pool.map(embed_one, batch))
                insert_batch(conn, batch, vectors)
                print(f"stored {completed}/{total} remaining {total - completed}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed support chunks into pgvector.")
    parser.add_argument("--rebuild", action="store_true", help="Delete stored chunks and embed again")
    args = parser.parse_args()
    try:
        index(args.rebuild)
    except Exception as exc:
        print(f"indexing failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
