"""Retrieval strictly scoped to the pinned sources."""
from __future__ import annotations

from app.index.base import KnowledgeIndex, ScoredChunk
from app.index.ranking import normalise, rank_chunks, rrf_merge
from app.llm.base import Provider, embed_query
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
    # Normally embedded by the request service before the request is marked Processing (a quota error there is a clean,
    # retryable 503 instead of an unknown outcome); embedded here only for callers that skip that step.
    if prepared.query_embedding is not None:
        query_embedding = prepared.query_embedding
    else:
        query_embedding = embed_query(provider, question)
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
