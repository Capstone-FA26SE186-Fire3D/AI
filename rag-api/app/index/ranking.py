"""Hybrid ranking: lexical + cosine merged with reciprocal rank fusion."""
from __future__ import annotations

import math
import re

from app.index.base import ScoredChunk
from app.sources.chunking import Chunk

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def rrf_merge(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for pos, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + pos + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def lexical_rank(query: str, texts: dict[str, str]) -> list[str]:
    q = set(_tokens(query))
    scored = []
    for key, text in texts.items():
        score = len(q & set(_tokens(text)))
        if score > 0:
            scored.append((key, score))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return [key for key, _ in scored]


def cosine_rank(query: list[float], vectors: dict[str, list[float]]) -> list[str]:
    qn = math.sqrt(sum(x * x for x in query))

    def cos(vec: list[float]) -> float:
        vn = math.sqrt(sum(x * x for x in vec))
        if qn == 0 or vn == 0:
            return 0.0
        return sum(a * b for a, b in zip(query, vec)) / (qn * vn)

    scored = sorted(((k, cos(v)) for k, v in vectors.items()), key=lambda kv: kv[1], reverse=True)
    return [key for key, _ in scored]


def normalise(merged: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Scale RRF scores to 0..1 by dividing by the maximum."""
    if not merged:
        return []
    top = max(score for _, score in merged)
    return [(key, score / top) for key, score in merged]


def rank_chunks(
    query_text: str,
    query_embedding: list[float],
    chunks: list[Chunk],
    embeddings: list[list[float]],
    top_k: int,
) -> list[ScoredChunk]:
    by_key = {str(i): c for i, c in enumerate(chunks)}
    texts = {k: c.content for k, c in by_key.items()}
    vectors = {str(i): e for i, e in enumerate(embeddings)}
    merged = rrf_merge([lexical_rank(query_text, texts), cosine_rank(query_embedding, vectors)])
    return [ScoredChunk(by_key[k], s) for k, s in normalise(merged)[:top_k]]
