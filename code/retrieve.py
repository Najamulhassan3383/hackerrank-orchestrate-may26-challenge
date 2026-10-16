"""Find the support chunks closest to a ticket."""

from __future__ import annotations

from dataclasses import dataclass

from db import connect, ensure_schema, resolve_model_id, resolve_strategy_id
from embed import vector_literal

TOP_K = 5


@dataclass(frozen=True)
class Hit:
    path: str
    title: str
    heading: str
    body: str
    distance: float
    chunk_id: int | None = None
    parent_id: int | None = None
    sister_ids: tuple[int, ...] = ()


def search(
    vector: list[float],
    company: str | None = None,
    limit: int = TOP_K,
    *,
    model_name: str | None = None,
    strategy_name: str | None = None,
) -> list[Hit]:
    literal = vector_literal(vector)
    company = (company or "").strip()
    ensure_schema()
    with connect() as conn:
        model_id = resolve_model_id(conn, model_name)
        strategy_id = resolve_strategy_id(conn, strategy_name)
        if company and company.lower() != "none":
            sql = """
                SELECT id, parent_id, path, title, heading, body, sister_ids,
                       embedding <=> %s::vector AS distance
                FROM chunks
                WHERE company = %s
                  AND model_id = %s
                  AND strategy_id = %s
                ORDER BY distance
                LIMIT %s
            """
            params = (literal, company, model_id, strategy_id, limit)
        else:
            sql = """
                SELECT id, parent_id, path, title, heading, body, sister_ids,
                       embedding <=> %s::vector AS distance
                FROM chunks
                WHERE model_id = %s
                  AND strategy_id = %s
                ORDER BY distance
                LIMIT %s
            """
            params = (literal, model_id, strategy_id, limit)

        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    hits: list[Hit] = []
    for chunk_id, parent_id, path, title, heading, body, sister_ids, distance in rows:
        sisters = tuple(int(value) for value in (sister_ids or ()))
        hits.append(
            Hit(
                path=path,
                title=title or "",
                heading=heading or "",
                body=body,
                distance=float(distance),
                chunk_id=int(chunk_id),
                parent_id=int(parent_id),
                sister_ids=sisters,
            )
        )
    return hits
