"""Knowledge index contract: retrieval is always limited to pinned document ids."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.sources.chunking import Chunk


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float


@dataclass
class IncompleteSource:
    """A source whose embedding stopped part way (restart, quota); enough to queue it again."""

    document_id: str
    document_version: str
    content_hash: str
    source_uri: str
    title: str | None


class KnowledgeIndex(Protocol):
    def has_current(self, document_id: str, content_hash: str, embedding_model: str) -> bool:
        """True only when every chunk of this content is embedded with this model."""
        ...

    def current_sources(self, sources: list[tuple[str, str]], embedding_model: str) -> set[tuple[str, str]]:
        """The (document_id, content_hash) pairs of `sources` for which has_current is true, in one round trip: a
        question pins tens of sources, and one connection and query per source was most of its preparation time."""
        ...

    def indexed_chunks(self, document_id: str, content_hash: str, embedding_model: str) -> set[int]:
        """chunk_index values already stored for this content and model."""
        ...

    def add_chunks(
        self,
        document_id: str,
        document_version: str,
        content_hash: str,
        embedding_model: str,
        chunk_count: int,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        source_uri: str | None = None,
        title: str | None = None,
    ) -> None:
        """Stores one batch of a document of chunk_count chunks; chunks of other content or models are dropped first."""
        ...

    def incomplete_sources(self, embedding_model: str) -> list[IncompleteSource]: ...

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
