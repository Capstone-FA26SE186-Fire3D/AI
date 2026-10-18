"""Locator-aware chunking of source sections."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Section:
    text: str
    locator: dict


@dataclass
class Chunk:
    chunk_id: str
    document_id: str
    document_version: str
    chunk_index: int
    content: str
    locator: dict
    excerpt_locator: str


def format_locator(locator: dict) -> str:
    if not locator:
        return "Toàn văn"
    if "page" in locator:
        return f"Trang {locator['page']}"
    if "heading" in locator:
        text = f"Mục {locator['heading']}"
        if "paragraph" in locator:
            text += f", đoạn {locator['paragraph']}"
        return text
    if "paragraph" in locator:
        return f"Đoạn {locator['paragraph']}"
    if "block" in locator:
        return f"Khối {locator['block']}"
    if "field" in locator:
        return f"Trường {locator['field']}"
    return "Toàn văn"


def _windows(text: str, size: int, overlap: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out: list[str] = []
    start = 0
    n = len(text)
    while True:
        end = min(start + size, n)
        if end < n:
            lo = start + int(size * 0.8)
            ws = max(text.rfind(" ", lo, end), text.rfind("\n", lo, end))
            if ws > start + overlap:
                end = ws + 1
        out.append(text[start:end])
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return out


def chunk_sections(
    sections: list[Section],
    document_id: str,
    document_version: str,
    chunk_size: int = 900,
    overlap: int = 150,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        text = section.text.strip()
        if not text:
            continue
        for piece in _windows(text, chunk_size, overlap):
            idx = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{document_id}:{document_version}:{idx}",
                    document_id=document_id,
                    document_version=document_version,
                    chunk_index=idx,
                    content=piece,
                    locator=dict(section.locator),
                    excerpt_locator=format_locator(section.locator),
                )
            )
    return chunks
