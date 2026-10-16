"""Embed every chunk and store the vectors in Postgres.

Rows are keyed by (model, strategy, path, content_hash). A second run skips
bodies that are already stored for that model+strategy pair. Pass --rebuild to
delete only that pair's rows and start over. Sister chunk IDs are filled after
each parent document's rows are inserted.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from chunking import STRATEGY_NAME, Chunk, load_chunks
from db import (
    DEFAULT_DIMENSIONS,
    DEFAULT_MODEL_NAME,
    connect,
    ensure_schema,
    get_or_create_model,
    get_or_create_strategy,
    upsert_document,
)
from embed import embed_text, vector_literal

ROOT = Path(__file__).resolve().parent.parent
BATCH = 20
WORKERS = 4

INSERT = """
INSERT INTO chunks (
    parent_id, company, path, title, heading, body, content_hash,
    chunk_index, char_count, word_count, token_count,
    model_id, strategy_id, embedding
)
VALUES (
    %s, %s, %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s::vector
)
ON CONFLICT (model_id, strategy_id, path, content_hash) DO NOTHING
RETURNING id, parent_id
"""


def content_hash(body: str) -> str:
    return hashlib.md5(body.encode("utf-8")).hexdigest()


def body_key(chunk: Chunk) -> tuple[str, str]:
    return chunk.path, content_hash(chunk.body)


def stored_keys(conn, model_id: int, strategy_id: int) -> set[tuple[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT path, content_hash
            FROM chunks
            WHERE model_id = %s AND strategy_id = %s
            """,
            (model_id, strategy_id),
        )
        return {(path, digest) for path, digest in cur.fetchall()}


def insert_batch(
    conn,
    chunks: list[Chunk],
    vectors: list[list[float]],
    *,
    parent_ids: dict[str, int],
    model_id: int,
    strategy_id: int,
) -> list[tuple[int, int]]:
    """Insert a batch. Returns (chunk_id, parent_id) for newly inserted rows."""
    inserted: list[tuple[int, int]] = []
    with conn.cursor() as cur:
        for chunk, vector in zip(chunks, vectors):
            cur.execute(
                INSERT,
                (
                    parent_ids[chunk.path],
                    chunk.company,
                    chunk.path,
                    chunk.title,
                    chunk.heading,
                    chunk.body,
                    content_hash(chunk.body),
                    chunk.chunk_index,
                    chunk.char_count,
                    chunk.word_count,
                    chunk.token_count,
                    model_id,
                    strategy_id,
                    vector_literal(vector),
                ),
            )
            row = cur.fetchone()
            if row is not None:
                inserted.append((int(row[0]), int(row[1])))
    conn.commit()
    return inserted


def refresh_sister_ids(conn, model_id: int, strategy_id: int, parent_ids: set[int]) -> None:
    if not parent_ids:
        return
    with conn.cursor() as cur:
        for parent_id in parent_ids:
            cur.execute(
                """
                SELECT id
                FROM chunks
                WHERE parent_id = %s AND model_id = %s AND strategy_id = %s
                ORDER BY chunk_index, id
                """,
                (parent_id, model_id, strategy_id),
            )
            ids = [int(row[0]) for row in cur.fetchall()]
            for chunk_id in ids:
                sisters = [other for other in ids if other != chunk_id]
                cur.execute(
                    "UPDATE chunks SET sister_ids = %s::bigint[] WHERE id = %s",
                    (sisters, chunk_id),
                )
    conn.commit()


def ensure_documents(conn, chunks: list[Chunk]) -> dict[str, int]:
    by_path: dict[str, Chunk] = {}
    for chunk in chunks:
        by_path.setdefault(chunk.path, chunk)
    parent_ids: dict[str, int] = {}
    for path, chunk in by_path.items():
        parent_ids[path] = upsert_document(conn, chunk.company, path, chunk.title)
    conn.commit()
    return parent_ids


def index(
    rebuild: bool,
    *,
    model_name: str | None = None,
    strategy_name: str | None = None,
) -> None:
    load_dotenv(ROOT / ".env")
    ensure_schema()

    model_name = model_name or os.environ.get("BEDROCK_EMBEDDING_MODEL") or DEFAULT_MODEL_NAME
    strategy_name = strategy_name or STRATEGY_NAME

    print("reading articles", flush=True)
    chunks = load_chunks(progress=True)

    with connect() as conn:
        model_id = get_or_create_model(
            conn,
            model_name,
            dimensions=DEFAULT_DIMENSIONS,
            notes="Registered by index_chunks.py",
        )
        strategy_id = get_or_create_strategy(
            conn,
            strategy_name,
            description=(
                "Keep articles <= 8000 chars whole; else split on ## then paragraphs "
                "with 200-char overlap; title+heading prefix on body"
            ),
            max_chars=8000,
            overlap_chars=200,
            notes="Registered by index_chunks.py",
        )
        print(
            f"model {model_name!r} id={model_id}; strategy {strategy_name!r} id={strategy_id}",
            flush=True,
        )

        if rebuild:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM chunks WHERE model_id = %s AND strategy_id = %s",
                    (model_id, strategy_id),
                )
            conn.commit()
            done: set[tuple[str, str]] = set()
        else:
            done = stored_keys(conn, model_id, strategy_id)

        parent_ids = ensure_documents(conn, chunks)
        pending = [chunk for chunk in chunks if body_key(chunk) not in done]
        print(
            f"chunks {len(chunks)}, already stored {len(chunks) - len(pending)}, "
            f"to embed {len(pending)}",
            flush=True,
        )
        if not pending:
            # Still refresh sisters in case a prior run was interrupted.
            refresh_sister_ids(conn, model_id, strategy_id, set(parent_ids.values()))
            return

        total = len(chunks)
        completed = total - len(pending)
        lock = threading.Lock()
        touched_parents: set[int] = set()

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

        # Group pending by parent so sister_ids can be filled soon after each doc.
        by_parent: dict[str, list[Chunk]] = defaultdict(list)
        for chunk in pending:
            by_parent[chunk.path].append(chunk)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for path, group in by_parent.items():
                group.sort(key=lambda item: item.chunk_index)
                for start in range(0, len(group), BATCH):
                    batch = group[start : start + BATCH]
                    vectors = list(pool.map(embed_one, batch))
                    inserted = insert_batch(
                        conn,
                        batch,
                        vectors,
                        parent_ids=parent_ids,
                        model_id=model_id,
                        strategy_id=strategy_id,
                    )
                    touched_parents.update(parent_id for _, parent_id in inserted)
                    print(
                        f"stored {completed}/{total} remaining {total - completed}",
                        flush=True,
                    )
                refresh_sister_ids(conn, model_id, strategy_id, {parent_ids[path]})

        if touched_parents:
            refresh_sister_ids(conn, model_id, strategy_id, touched_parents)


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed support chunks into pgvector.")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete stored chunks for this model+strategy and embed again",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Embedding model name to register/use (default: BEDROCK_EMBEDDING_MODEL)",
    )
    parser.add_argument(
        "--strategy",
        default=None,
        help=f"Strategy name to register/use (default: {STRATEGY_NAME})",
    )
    args = parser.parse_args()
    try:
        index(args.rebuild, model_name=args.model, strategy_name=args.strategy)
    except Exception as exc:
        print(f"indexing failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
