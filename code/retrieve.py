"""Find the support chunks closest to a ticket."""

from dataclasses import dataclass

from db import connect
from embed import vector_literal

TOP_K = 5


@dataclass(frozen=True)
class Hit:
    path: str
    title: str
    heading: str
    body: str
    distance: float


def search(vector: list[float], company: str | None = None, limit: int = TOP_K) -> list[Hit]:
    literal = vector_literal(vector)
    company = (company or "").strip()
    if company and company.lower() != "none":
        sql = """
            SELECT path, title, heading, body, embedding <=> %s::vector AS distance
            FROM chunks
            WHERE company = %s
            ORDER BY distance
            LIMIT %s
        """
        params = (literal, company, limit)
    else:
        sql = """
            SELECT path, title, heading, body, embedding <=> %s::vector AS distance
            FROM chunks
            ORDER BY distance
            LIMIT %s
        """
        params = (literal, limit)

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [
        Hit(path=path, title=title or "", heading=heading or "", body=body, distance=float(distance))
        for path, title, heading, body, distance in rows
    ]
