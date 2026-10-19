"""Retrieval strictly scoped to the pinned sources."""
from __future__ import annotations

from app.index.base import KnowledgeIndex, ScoredChunk
from app.index.ranking import normalise, rank_chunks, rrf_merge
from app.llm.base import Provider
from app.sources.resolver import PreparedSources


def retrieve(
    question: str,
    prepared: PreparedSources,
    index: KnowledgeIndex,
    provider: Provider,
    top_k: int = 8,
) -> list[ScoredChunk]:
    if not prepared.knowledge_ids and not prepared.inline_chunks:
        return []
    query_embedding = provider.embed([question])[0]
    by_id: dict[str, ScoredChunk] = {}
    rankings: list[list[str]] = []
    if prepared.knowledge_ids:
        hits = index.search(question, query_embedding, prepared.knowledge_ids, provider.embedding_model, top_k)
        rankings.append([h.chunk.chunk_id for h in hits])
        by_id.update({h.chunk.chunk_id: h for h in hits})
    if prepared.inline_chunks:
        hits = rank_chunks(question, query_embedding, prepared.inline_chunks, prepared.inline_embeddings, top_k)
        rankings.append([h.chunk.chunk_id for h in hits])
        by_id.update({h.chunk.chunk_id: h for h in hits})
    merged = normalise(rrf_merge([r for r in rankings if r]))
    return [ScoredChunk(by_id[cid].chunk, score) for cid, score in merged[:top_k]]
