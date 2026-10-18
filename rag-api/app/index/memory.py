"""In-memory KnowledgeIndex for tests and local runs."""
from __future__ import annotations

from app.index.base import ScoredChunk
from app.index.ranking import rank_chunks
from app.sources.chunking import Chunk


class MemoryIndex:
    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}
        self.eligible: dict[str, bool] = {}

    def has_current(self, document_id: str, content_hash: str, embedding_model: str) -> bool:
        doc = self._docs.get(document_id)
        return bool(doc and doc["content_hash"] == content_hash and doc["embedding_model"] == embedding_model)

    def replace(
        self,
        document_id: str,
        document_version: str,
        content_hash: str,
        embedding_model: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        self._docs[document_id] = {
            "document_version": document_version,
            "content_hash": content_hash,
            "embedding_model": embedding_model,
            "chunks": list(chunks),
            "embeddings": [list(e) for e in embeddings],
        }

    def search(
        self,
        query_text: str,
        query_embedding: list[float],
        document_ids: list[str],
        embedding_model: str,
        top_k: int,
    ) -> list[ScoredChunk]:
        chunks: list[Chunk] = []
        embeddings: list[list[float]] = []
        for doc_id in dict.fromkeys(document_ids):
            doc = self._docs.get(doc_id)
            if not doc or doc["embedding_model"] != embedding_model:
                continue
            chunks.extend(doc["chunks"])
            embeddings.extend(doc["embeddings"])
        return rank_chunks(query_text, query_embedding, chunks, embeddings, top_k)

    def prune_ineligible(self) -> int:
        return 0
