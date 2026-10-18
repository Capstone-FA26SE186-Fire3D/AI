"""Sanitise model output before it goes back to BE."""
from __future__ import annotations

import re

from app.index.base import ScoredChunk
from app.v2.schemas import Citation

_HTML = re.compile(r"<[^>\n]*>")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_LINE_PREFIX = re.compile(r"^[ \t]*(?:#{1,6}[ \t]*|[-*][ \t]+)", re.MULTILINE)
_MARKS = re.compile(r"\*\*|__|`")


def to_plain_text(text: str, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    out = _HTML.sub("", text)
    out = _LINK.sub(r"\1", out)
    out = _LINE_PREFIX.sub("", out)
    out = _MARKS.sub("", out)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"[ \t]*\n[ \t]*", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out[:limit].strip()


def clean_list(items: list[str]) -> list[str]:
    cleaned = [to_plain_text(i, 500) for i in items if isinstance(i, str)]
    return [c for c in cleaned if c][:20]


def build_citations(raw: list[dict], retrieved: dict[str, ScoredChunk]) -> list[Citation]:
    out: dict[str, Citation] = {}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        chunk_id = entry.get("chunk_id")
        if not isinstance(chunk_id, str) or chunk_id not in retrieved or chunk_id in out:
            continue
        scored = retrieved[chunk_id]
        chunk = scored.chunk
        rel = entry.get("relevance")
        if isinstance(rel, bool) or not isinstance(rel, (int, float)) or not 0 <= rel <= 1:
            rel = min(1.0, max(0.0, float(scored.score)))
        out[chunk_id] = Citation(
            document_id=chunk.document_id,
            document_version=chunk.document_version,
            chunk_id=chunk_id,
            excerpt_locator=chunk.excerpt_locator,
            relevance=float(rel),
        )
        if len(out) >= 20:
            break
    return list(out.values())
