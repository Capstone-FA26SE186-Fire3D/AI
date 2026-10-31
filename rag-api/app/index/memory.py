"""In-memory KnowledgeIndex for tests and local runs."""
from __future__ import annotations

import threading

from app.index.base import IncompleteSource, ScoredChunk
from app.index.ranking import rank_chunks
from app.sources.chunking import Chunk


class MemoryIndex:
    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.eligible: dict[str, bool] = {}

    def _doc(self, document_id: str, content_hash: str, embedding_model: str) -> dict | None:
        doc = self._docs.get(document_id)
        if doc and doc["content_hash"] == content_hash and doc["embedding_model"] == embedding_model:
            return doc
        return None

    def has_current(self, document_id: str, content_hash: str, embedding_model: str) -> bool:
        with self._lock:
            doc = self._doc(document_id, content_hash, embedding_model)
            return bool(doc and doc["rows"] and len(doc["rows"]) >= doc["chunk_count"])

    def indexed_chunks(self, document_id: str, content_hash: str, embedding_model: str) -> set[int]:
        with self._lock:
            doc = self._doc(document_id, content_hash, embedding_model)
            return set(doc["rows"]) if doc else set()

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
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings differ in length")
        with self._lock:
            doc = self._doc(document_id, content_hash, embedding_model)
            if doc is None:
                doc = self._docs[document_id] = {
                    "content_hash": content_hash,
                    "embedding_model": embedding_model,
                    "rows": {},
                }
            doc.update(document_version=document_version, chunk_count=chunk_count, source_uri=source_uri, title=title)
            for chunk, emb in zip(chunks, embeddings):
                doc["rows"].setdefault(chunk.chunk_index, (chunk, list(emb)))

    def replace(
        self,
        document_id: str,
        document_version: str,
        content_hash: str,
        embedding_model: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        with self._lock:
            self._docs.pop(document_id, None)
        self.add_chunks(document_id, document_version, content_hash, embedding_model, len(chunks), chunks, embeddings)

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
        with self._lock:
            for doc_id in dict.fromkeys(document_ids):
                doc = self._docs.get(doc_id)
                if not doc or doc["embedding_model"] != embedding_model:
                    continue
                for index in sorted(doc["rows"]):
                    chunk, emb = doc["rows"][index]
                    chunks.append(chunk)
                    embeddings.append(emb)
        return rank_chunks(query_text, query_embedding, chunks, embeddings, top_k)

    def incomplete_sources(self, embedding_model: str) -> list[IncompleteSource]:
        with self._lock:
            return [
                IncompleteSource(doc_id, doc["document_version"], doc["content_hash"], doc["source_uri"], doc["title"])
                for doc_id, doc in self._docs.items()
                if doc["embedding_model"] == embedding_model and doc["source_uri"]
                and len(doc["rows"]) < doc["chunk_count"]
            ]

    def prune_ineligible(self) -> int:
        return 0
