"""KnowledgeIndex over BE's knowledge_chunks table. Every query is limited to pinned source ids."""
from __future__ import annotations

import json
import uuid

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

from app.index.base import IncompleteSource, ScoredChunk
from app.index.ranking import normalise, rrf_merge
from app.sources.chunking import Chunk, format_locator

_CANDIDATES = 20

_VECTOR_SQL = (
    "SELECT id, source_id, chunk_index, content, locator, metadata FROM knowledge_chunks "
    "WHERE source_id = ANY(%s::uuid[]) AND metadata->>'embedding_model' = %s "
    "ORDER BY embedding <=> %s LIMIT " + str(_CANDIDATES)
)
_TEXT_SQL = (
    "SELECT id, source_id, chunk_index, content, locator, metadata FROM knowledge_chunks "
    "WHERE source_id = ANY(%s::uuid[]) AND metadata->>'embedding_model' = %s "
    "AND to_tsvector('simple', content) @@ plainto_tsquery('simple', %s) "
    "ORDER BY ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', %s)) DESC LIMIT "
    + str(_CANDIDATES)
)


def _uuids(ids: list[str]) -> list[str]:
    out = []
    for value in ids:
        try:
            out.append(str(uuid.UUID(str(value))))
        except ValueError:
            continue
    return list(dict.fromkeys(out))


def _chunk(row) -> Chunk:
    chunk_id, source_id, chunk_index, content, locator, metadata = row
    return Chunk(
        chunk_id=str(chunk_id),
        document_id=str(source_id),
        document_version=(metadata or {}).get("document_version", ""),
        chunk_index=chunk_index,
        content=content,
        locator=locator or {},
        excerpt_locator=format_locator(locator or {}),
    )


class PgVectorIndex:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self._dsn)
        try:
            register_vector(conn)
        except Exception:
            conn.close()
            raise
        return conn

    def has_current(self, document_id: str, content_hash: str, embedding_model: str) -> bool:
        ids = _uuids([document_id])
        if not ids:
            return False
        with self._connect() as conn:
            stored, expected = conn.execute(
                "SELECT count(*), max((metadata->>'chunk_count')::int) FROM knowledge_chunks WHERE source_id = %s::uuid "
                "AND metadata->>'content_hash' = %s AND metadata->>'embedding_model' = %s",
                (ids[0], content_hash, embedding_model),
            ).fetchone()
        # Rows written by replace() carry no chunk_count: they were stored in one transaction, so complete.
        return stored > 0 and (expected is None or stored >= expected)

    def indexed_chunks(self, document_id: str, content_hash: str, embedding_model: str) -> set[int]:
        ids = _uuids([document_id])
        if not ids:
            return set()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT chunk_index FROM knowledge_chunks WHERE source_id = %s::uuid "
                "AND metadata->>'content_hash' = %s AND metadata->>'embedding_model' = %s",
                (ids[0], content_hash, embedding_model),
            ).fetchall()
        return {row[0] for row in rows}

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
        with self._connect() as conn:  # one transaction per batch: a crash keeps every earlier batch
            conn.execute(
                "DELETE FROM knowledge_chunks WHERE source_id = %s::uuid AND (metadata->>'content_hash' IS DISTINCT FROM %s "
                "OR metadata->>'embedding_model' IS DISTINCT FROM %s)",
                (document_id, content_hash, embedding_model),
            )
            for chunk, emb in zip(chunks, embeddings):
                metadata = {
                    "content_hash": content_hash,
                    "document_version": document_version,
                    "embedding_model": embedding_model,
                    "embedding_dim": len(emb),
                    "chunk_count": chunk_count,
                    "source_uri": source_uri,
                    "title": title,
                }
                conn.execute(
                    "INSERT INTO knowledge_chunks (source_id, chunk_index, content, locator, embedding, metadata) "
                    "VALUES (%s::uuid, %s, %s, %s::jsonb, %s, %s::jsonb) ON CONFLICT (source_id, chunk_index) DO NOTHING",
                    (
                        document_id,
                        chunk.chunk_index,
                        chunk.content,
                        json.dumps(chunk.locator),
                        np.asarray(emb, dtype=np.float32),
                        json.dumps(metadata),
                    ),
                )

    def incomplete_sources(self, embedding_model: str) -> list[IncompleteSource]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT source_id, metadata->>'document_version', metadata->>'content_hash', metadata->>'source_uri', "
                "metadata->>'title' FROM knowledge_chunks "
                "WHERE metadata->>'embedding_model' = %s AND metadata ? 'chunk_count' AND metadata->>'source_uri' IS NOT NULL "
                "GROUP BY 1, 2, 3, 4, 5 HAVING count(*) < max((metadata->>'chunk_count')::int)",
                (embedding_model,),
            ).fetchall()
        return [IncompleteSource(str(r[0]), r[1] or "", r[2], r[3], r[4]) for r in rows]

    def replace(
        self,
        document_id: str,
        document_version: str,
        content_hash: str,
        embedding_model: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings differ in length")
        with self._connect() as conn:  # one transaction: commit on success, rollback on error
            conn.execute("DELETE FROM knowledge_chunks WHERE source_id = %s::uuid", (document_id,))
            for chunk, emb in zip(chunks, embeddings):
                metadata = {
                    "content_hash": content_hash,
                    "document_version": document_version,
                    "embedding_model": embedding_model,
                    "embedding_dim": len(emb),
                }
                conn.execute(
                    "INSERT INTO knowledge_chunks (source_id, chunk_index, content, locator, embedding, metadata) "
                    "VALUES (%s::uuid, %s, %s, %s::jsonb, %s, %s::jsonb)",
                    (
                        document_id,
                        chunk.chunk_index,
                        chunk.content,
                        json.dumps(chunk.locator),
                        np.asarray(emb, dtype=np.float32),
                        json.dumps(metadata),
                    ),
                )

    def search(
        self,
        query_text: str,
        query_embedding: list[float],
        document_ids: list[str],
        embedding_model: str,
        top_k: int,
    ) -> list[ScoredChunk]:
        ids = _uuids(document_ids)
        if not ids:
            return []
        with self._connect() as conn:
            vec_rows = conn.execute(
                _VECTOR_SQL, (ids, embedding_model, np.asarray(query_embedding, dtype=np.float32))
            ).fetchall()
            txt_rows = conn.execute(_TEXT_SQL, (ids, embedding_model, query_text, query_text)).fetchall()
        chunks: dict[str, Chunk] = {}
        for row in [*vec_rows, *txt_rows]:
            chunks.setdefault(str(row[0]), _chunk(row))
        merged = normalise(rrf_merge([[str(r[0]) for r in vec_rows], [str(r[0]) for r in txt_rows]]))
        return [ScoredChunk(chunks[k], s) for k, s in merged[:top_k]]

    def prune_ineligible(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM knowledge_chunks c USING ai_source_states s "
                "WHERE s.kind = 'KnowledgeSource' AND s.id = c.source_id AND NOT s.eligible"
            )
            return cur.rowcount
