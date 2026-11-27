"""In-process cache of chunk embeddings for inline sources (lessons, library items sent with each question).

The BE sends an organization's whole inline content with every question; re-embedding it each time exhausts the
provider's per-minute quota. Vectors are keyed by embedding model and chunk text, so unchanged content is embedded
once per process lifetime; edited text simply misses. float32 arrays keep 1,000 Gemini vectors near 12 MB.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

import numpy as np


def _key(model: str, text: str) -> tuple[str, str]:
    return model, hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(self, max_items: int = 5000) -> None:
        self.max_items = max(1, max_items)
        self._items: OrderedDict[tuple[str, str], np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    def get_many(self, model: str, texts: list[str]) -> list[list[float] | None]:
        # Hashing and list conversion happen outside the lock; stored arrays are never modified, only replaced.
        keys = [_key(model, text) for text in texts]
        found: list[np.ndarray | None] = []
        with self._lock:
            for key in keys:
                vec = self._items.get(key)
                if vec is not None:
                    self._items.move_to_end(key)
                found.append(vec)
        return [None if vec is None else vec.tolist() for vec in found]

    def put_many(self, model: str, texts: list[str], vectors: list[list[float]]) -> None:
        if len(texts) != len(vectors):
            raise ValueError("texts and vectors differ in length")
        with self._lock:
            for text, vec in zip(texts, vectors):
                key = _key(model, text)
                self._items[key] = np.asarray(vec, dtype=np.float32)
                self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
