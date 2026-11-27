"""Retrieval strictly scoped to the pinned sources."""
from __future__ import annotations

from app.index.base import KnowledgeIndex, ScoredChunk
from app.index.ranking import normalise, rank_chunks, rrf_merge
from app.llm.base import Provider, embed_query
from app.sources.criteria import is_context_snapshot
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
    # The context snapshot is added whole by _with_context, so it does not take the ranked slots.
    context_ids = _context_ids(prepared)
    others = [(c, e) for c, e in zip(prepared.inline_chunks, prepared.inline_embeddings) if c.document_id not in context_ids]
    if others:
        hits = rank_chunks(question, query_embedding, [c for c, _ in others], [e for _, e in others], top_k)
        rankings.append([h.chunk.chunk_id for h in hits])
        by_id.update({h.chunk.chunk_id: h for h in hits})
    merged = normalise(rrf_merge([r for r in rankings if r]))
    ranked = [ScoredChunk(by_id[cid].chunk, score) for cid, score in merged[:top_k]]
    return _with_context(prepared, ranked)


# The Training snapshot or Session result the question is about is the subject itself, not a candidate source: all of
# it (every criterion and metric) goes to the model, ahead of the ranked chunks, whatever the question's wording.
MAX_CONTEXT_CHUNKS = 24


def _context_ids(prepared: PreparedSources) -> set[str]:
    return {doc for doc, pin in prepared.pins.items() if is_context_snapshot(pin.kind)}


def _with_context(prepared: PreparedSources, ranked: list[ScoredChunk]) -> list[ScoredChunk]:
    context_ids = _context_ids(prepared)
    if not context_ids:
        return ranked
    pinned = [c for c in prepared.inline_chunks if c.document_id in context_ids][:MAX_CONTEXT_CHUNKS]
    seen = {c.chunk_id for c in pinned}
    return [ScoredChunk(c, 1.0) for c in pinned] + [sc for sc in ranked if sc.chunk.chunk_id not in seen]
