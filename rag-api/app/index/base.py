"""Knowledge index contract: retrieval is always limited to pinned document ids."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.sources.chunking import Chunk


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float


class KnowledgeIndex(Protocol):
    def has_current(self, document_id: str, content_hash: str, embedding_model: str) -> bool: ...

    def replace(
        self,
        document_id: str,
        document_version: str,
        content_hash: str,
        embedding_model: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None: ...

    def search(
        self,
        query_text: str,
        query_embedding: list[float],
        document_ids: list[str],
        embedding_model: str,
        top_k: int,
    ) -> list[ScoredChunk]: ...

    def prune_ineligible(self) -> int: ...
