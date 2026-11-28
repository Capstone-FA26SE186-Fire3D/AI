"""Hybrid ranking: lexical + cosine merged with reciprocal rank fusion."""
from __future__ import annotations

import math
import re

import numpy as np

from app.index.base import ScoredChunk
from app.sources.chunking import Chunk

_TOKEN = re.compile(r"\w+", re.UNICODE)


# Vietnamese (and a few English) function words that carry no topic: counting them let a chunk full of "là, của, có,
# khi" outrank the one about the asked term (AI#44). Kept short on purpose: words such as "không", "người", "xuống"
# change the meaning of a fire-safety question and stay searchable.
STOPWORDS = frozenset("""
là của và có khi thì các những này nào gì như được cho với trong để một bạn tôi mình cần phải làm sao thế nếu hay hoặc
đã đang sẽ rồi ạ à nhé nhỉ vậy đó đây kia ở về bị theo mà nên cũng vẫn còn rất thể hãy xin giúp ơi
the a an of to is are and or in on for what how
""".split())


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def query_terms(text: str) -> list[str]:
    """Distinct searchable words of a question, in order: lower-cased, without stopwords; [] when none is left."""
    seen: dict[str, None] = {}
    for token in _tokens(text):
        if token not in STOPWORDS:
            seen.setdefault(token, None)
    return list(seen)


def rrf_merge(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for pos, item in enumerate(ranking):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + pos + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def lexical_rank(query: str, texts: dict[str, str], k1: float = 1.2, b: float = 0.75) -> list[str]:
    """Keys by BM25 over these texts (AI#44): rare words of the question ("CO2", "QCVN") weigh more than common ones,
    stopwords do not count, long chunks are not favoured. Keys without any query word are dropped; ties keep order."""
    terms = query_terms(query)
    if not terms or not texts:
        return []
    docs = {key: _tokens(text) for key, text in texts.items()}
    n = len(docs)
    avgdl = (sum(len(tokens) for tokens in docs.values()) / n) or 1.0
    counts = {key: {} for key in docs}
    df = dict.fromkeys(terms, 0)
    wanted = set(terms)
    for key, tokens in docs.items():
        tf = counts[key]
        for token in tokens:
            if token in wanted:
                tf[token] = tf.get(token, 0) + 1
        for term in tf:
            df[term] += 1
    idf = {term: math.log(1.0 + (n - df[term] + 0.5) / (df[term] + 0.5)) for term in terms}
    scored = []
    for key, tf in counts.items():
        if not tf:
            continue
        norm = k1 * (1.0 - b + b * len(docs[key]) / avgdl)
        score = sum(idf[t] * f * (k1 + 1.0) / (f + norm) for t, f in tf.items())
        scored.append((key, score))
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return [key for key, _ in scored]


def cosine_rank(query: list[float], vectors: dict[str, list[float]]) -> list[str]:
    """Keys by cosine similarity, highest first; ties keep their order (vectorised; see _cosine_rank_py)."""
    if not vectors:
        return []
    keys = list(vectors)
    try:
        m = np.asarray([vectors[k] for k in keys], dtype=np.float64)
        q = np.asarray(query, dtype=np.float64)
        if m.ndim != 2 or q.ndim != 1 or m.shape[1] != q.shape[0]:
            raise ValueError("ragged vectors")
    except ValueError:
        return _cosine_rank_py(query, vectors)
    qn = float(np.sqrt(q @ q))
    norms = np.sqrt(np.einsum("ij,ij->i", m, m))
    scores = np.zeros(len(keys))
    ok = norms > 0
    if qn > 0:
        scores[ok] = (m[ok] @ q) / (norms[ok] * qn)
    # BLAS sums rows in different orders, so identical vectors can differ in the last bit; rounding restores their tie
    # and the stable sort keeps tied keys in insertion order, as sorted() does in the reference.
    order = np.argsort(-np.round(scores, 12), kind="stable")
    return [keys[i] for i in order]


def _cosine_rank_py(query: list[float], vectors: dict[str, list[float]]) -> list[str]:
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
