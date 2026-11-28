"""Cache of chunk embeddings for inline sources (lessons, library items sent with each question).

The BE sends an organization's whole inline content with every question; re-embedding it each time exhausts the
provider's per-minute quota. Vectors are keyed by embedding model and chunk text, so unchanged content is embedded
once; edited text simply misses. float32 arrays keep 1,000 Gemini vectors near 12 MB (5,000 e5-small ones near 8 MB).

With a `path` the cache also lives on disk (AI#43): it is loaded at start and rewritten (temp file + rename) at most
every `save_interval` seconds and on `flush()`, so a restart or a deploy keeps every lesson already embedded. A missing,
unreadable or foreign file only means an empty cache; a failed write only means the next restart embeds again.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

_FORMAT = "fet3d-inline-embeddings/1"


def _key(model: str, text: str) -> tuple[str, str]:
    return model, hashlib.sha256(text.encode("utf-8")).hexdigest()


class EmbeddingCache:
    def __init__(
        self,
        max_items: int = 5000,
        path: str | os.PathLike | None = None,
        *,
        save_interval: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_items = max(1, max_items)
        self._items: OrderedDict[tuple[str, str], np.ndarray] = OrderedDict()
        self._lock = threading.Lock()
        self.path = Path(path) if path else None
        self.save_interval = max(0.0, save_interval)
        self._clock = clock
        self._dirty = False
        self._last_save = clock()
        self._save_lock = threading.Lock()
        if self.path is not None:
            self._load()

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
            self._dirty = True
        if self.path is not None and self._clock() - self._last_save >= self.save_interval:
            self.flush()

    def flush(self) -> bool:
        """Writes the cache to `path` when it changed since the last write; True when a file was written."""
        if self.path is None:
            return False
        with self._save_lock:
            with self._lock:
                if not self._dirty:
                    return False
                entries = list(self._items.items())  # stored arrays are never modified, so this snapshot is safe
                self._dirty = False
            self._last_save = self._clock()
            try:
                self._write(entries)
            except Exception:
                with self._lock:
                    self._dirty = True
                log.warning("inline embedding cache not saved to %s", self.path, exc_info=True)
                return False
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    # ---- disk -----------------------------------------------------------------------------

    def _write(self, entries: list[tuple[tuple[str, str], np.ndarray]]) -> None:
        # One group per (model, dimension); "order" keeps the LRU position of every entry across groups.
        groups: dict[tuple[str, int], list[tuple[int, str, np.ndarray]]] = {}
        for pos, ((model, digest), vec) in enumerate(entries):
            groups.setdefault((model, int(vec.shape[0])), []).append((pos, digest, vec))
        arrays: dict[str, np.ndarray] = {"format": np.array(_FORMAT)}
        models = []
        for i, ((model, _dim), rows) in enumerate(groups.items()):
            models.append(model)
            arrays[f"o{i}"] = np.array([pos for pos, _, _ in rows], dtype=np.int64)
            arrays[f"k{i}"] = np.array([digest for _, digest, _ in rows], dtype="<U64")
            arrays[f"v{i}"] = np.stack([vec for _, _, vec in rows]).astype(np.float32, copy=False)
        arrays["models"] = np.array(models, dtype=str) if models else np.array([], dtype="<U1")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "wb") as fh:
            np.savez(fh, **arrays)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            with np.load(self.path, allow_pickle=False) as data:
                if str(data["format"]) != _FORMAT:
                    raise ValueError("unknown cache format")
                rows: list[tuple[int, tuple[str, str], np.ndarray]] = []
                for i, model in enumerate(data["models"].tolist()):
                    order, digests, vectors = data[f"o{i}"], data[f"k{i}"], data[f"v{i}"]
                    if not (len(order) == len(digests) == len(vectors)) or vectors.ndim != 2:
                        raise ValueError("inconsistent cache group")
                    rows.extend(
                        (int(pos), (str(model), str(digest)), np.array(vec, dtype=np.float32))
                        for pos, digest, vec in zip(order, digests, vectors)
                    )
        except Exception:
            log.warning("inline embedding cache at %s not readable; starting empty", self.path, exc_info=True)
            return
        rows.sort(key=lambda row: row[0])
        with self._lock:
            for _, key, vec in rows[-self.max_items:]:
                self._items[key] = vec
        log.info("inline embedding cache loaded: %d vectors from %s", len(self._items), self.path)
