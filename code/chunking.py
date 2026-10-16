"""Split support articles into pieces that can be embedded later.

Short articles stay whole. Longer ones split on ``##`` headings. A section
that is still too long splits on paragraphs, repeating about 200 characters
so a step on the boundary is not lost. Release notes are left out.

The text in ``Chunk.body`` is what the embedding model should see: the article
title, the section heading, then the section. Nothing in this file calls Bedrock.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data"

MAX_CHARS = 8000
PARAGRAPH_OVERLAP = 200

COMPANIES = {
    "hackerrank": "HackerRank",
    "claude": "Claude",
    "visa": "Visa",
}

_TITLE = re.compile(r'^title:\s*"?(.*?)"?\s*$', re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    company: str
    path: str
    title: str
    heading: str
    body: str


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", text
    return parts[1], parts[2]


def article_title(frontmatter: str, body: str) -> str:
    match = _TITLE.search(frontmatter)
    if match and match.group(1).strip():
        return match.group(1).strip()
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def company_for(path: Path) -> str:
    try:
        relative = path.relative_to(DATA_ROOT)
    except ValueError:
        relative = path
    folder = relative.parts[0] if relative.parts else ""
    return COMPANIES.get(folder, folder)


def is_release_notes(path: Path) -> bool:
    return "release-notes" in path.parts


def split_sections(body: str) -> list[tuple[str, str]]:
    """Split on level-2 headings. Text before the first heading has an empty heading."""
    sections: list[tuple[str, str]] = []
    heading = ""
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("## ") and not line.startswith("### "):
            text = "\n".join(current).strip()
            if text:
                sections.append((heading, text))
            heading = line[3:].strip()
            current = [line]
        else:
            current.append(line)
    text = "\n".join(current).strip()
    if text:
        sections.append((heading, text))
    return sections


def _hard_split(text: str) -> list[str]:
    step = max(1, MAX_CHARS - PARAGRAPH_OVERLAP)
    pieces = []
    start = 0
    while start < len(text):
        pieces.append(text[start : start + MAX_CHARS].strip())
        if start + MAX_CHARS >= len(text):
            break
        start += step
    return [piece for piece in pieces if piece]


def split_long_section(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) <= 1:
        return _hard_split(text)

    pieces: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        if len(paragraph) > MAX_CHARS:
            if current:
                pieces.append("\n\n".join(current))
                current = []
                current_len = 0
            pieces.extend(_hard_split(paragraph))
            continue
        extra = len(paragraph) + (2 if current else 0)
        if current and current_len + extra > MAX_CHARS:
            joined = "\n\n".join(current)
            pieces.append(joined)
            tail = joined[-PARAGRAPH_OVERLAP:].strip()
            current = [tail, paragraph] if tail else [paragraph]
            current_len = sum(len(part) for part in current) + 2 * (len(current) - 1)
        else:
            current.append(paragraph)
            current_len += extra
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def embed_text(title: str, heading: str, content: str) -> str:
    parts = [part for part in (title.strip(), heading.strip(), content.strip()) if part]
    return "\n\n".join(parts)


def chunk_article(path: Path, text: str) -> list[Chunk]:
    frontmatter, body = split_frontmatter(text)
    title = article_title(frontmatter, body)
    body = body.strip()
    if not body:
        return []

    company = company_for(path)
    relative = path.relative_to(ROOT).as_posix()
    if len(body) <= MAX_CHARS:
        sections = [("", body)]
    else:
        sections = split_sections(body)

    chunks: list[Chunk] = []
    for heading, content in sections:
        for piece in split_long_section(content):
            chunks.append(
                Chunk(
                    company=company,
                    path=relative,
                    title=title,
                    heading=heading,
                    body=embed_text(title, heading, piece),
                )
            )
    return chunks


def load_chunks(
    data_root: Path = DATA_ROOT,
    *,
    skip_release_notes: bool = True,
    progress: bool = False,
) -> list[Chunk]:
    paths = [
        path
        for path in sorted(data_root.rglob("*.md"))
        if path.name != "index.md" and not (skip_release_notes and is_release_notes(path))
    ]
    chunks: list[Chunk] = []
    total = len(paths)
    for index, path in enumerate(paths, start=1):
        text = path.read_text(encoding="utf-8")
        chunks.extend(chunk_article(path, text))
        if progress:
            print(
                f"chunking {index}/{total} remaining {total - index} chunks {len(chunks)}",
                flush=True,
            )
    return chunks


def main() -> None:
    files = [
        path
        for path in sorted(DATA_ROOT.rglob("*.md"))
        if path.name != "index.md" and not is_release_notes(path)
    ]
    chunks = load_chunks(progress=True)
    whole = sum(1 for path in files if len(split_frontmatter(path.read_text(encoding="utf-8"))[1].strip()) <= MAX_CHARS)
    longest = max(chunks, key=lambda chunk: len(chunk.body))
    print(f"files {len(files)}")
    print(f"chunks {len(chunks)}")
    print(f"articles kept whole {whole}")
    print(f"longest chunk {len(longest.body)} chars {longest.path}")


if __name__ == "__main__":
    main()
