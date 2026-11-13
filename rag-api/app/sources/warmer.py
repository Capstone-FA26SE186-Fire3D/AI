"""Embeds knowledge sources outside the request path.

One daemon thread drains a queue of pinned sources: it fetches and chunks each document, embeds the chunks in small
batches under a per-minute item budget (waiting out a provider 429 for the delay it asks for) and stores every batch as
soon as it is embedded. A restart resumes from the stored batches: the sources left incomplete are queued again on
start, and only their missing chunks are embedded.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Callable
from urllib.parse import unquote, urlsplit

import httpx

from app.answering.usage import CHARS_PER_TOKEN
from app.core.config import Settings
from app.index.base import KnowledgeIndex
from app.llm.base import Provider, ProviderError, RateLimited
from app.sources.chunking import chunk_sections
from app.sources.fetch import fetch_document
from app.sources.embedding_cache import EmbeddingCache
from app.sources.render import document_sections, inline_sections
from app.v2.errors import AdapterRefusal, refuse
from app.v2.schemas import SourcePin

log = logging.getLogger(__name__)

READY = "ready"
QUEUED = "queued"

_WINDOW_SECONDS = 60.0
_DEFAULT_RATE_LIMIT_WAIT = 60.0
_MAX_RATE_LIMITED = 30
_MAX_PROVIDER_FAILURES = 3


def _filename(uri: str) -> str:
    return unquote(urlsplit(uri).path.rsplit("/", 1)[-1])


class _Stopped(Exception):
    pass


def _bare(refusal: AdapterRefusal) -> AdapterRefusal:
    """A copy without traceback or cause: a stored failure is shared by request threads for source_retry_seconds, and
    the original's traceback holds the fetched document and chunks (up to source_max_bytes) and grows on each re-raise."""
    return AdapterRefusal(refusal.status_code, refusal.code, refusal.message)


class RateLimiter:
    """At most per_minute units (items or tokens) in any 60-second window; acquire waits until the batch fits."""

    def __init__(self, per_minute: int, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
        self.per_minute = max(1, per_minute)
        self.clock = clock
        self.sleep = sleep
        self._sent: deque[tuple[float, int]] = deque()

    def acquire(self, items: int) -> None:
        items = min(max(1, items), self.per_minute)
        while True:
            now = self.clock()
            while self._sent and now - self._sent[0][0] >= _WINDOW_SECONDS:
                self._sent.popleft()
            if sum(n for _, n in self._sent) + items <= self.per_minute:
                self._sent.append((now, items))
                return
            self.sleep(self._sent[0][0] + _WINDOW_SECONDS - now)


class SourceWarmer:
    """Queue of sources to embed. background=False embeds inside request() instead (tests and scripts)."""

    def __init__(
        self,
        index: KnowledgeIndex,
        provider: Provider,
        settings: Settings,
        http: httpx.Client | None = None,
        *,
        background: bool = True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.index = index
        self.provider = provider
        self.settings = settings
        self.http = http
        self.background = background
        self.clock = clock
        self.limiter = RateLimiter(settings.embed_items_per_minute, clock, self._sleep)
        self.token_limiter = RateLimiter(settings.embed_tokens_per_minute, clock, self._sleep)
        self.inline_cache = EmbeddingCache(settings.inline_cache_items)
        self._queue: dict[tuple[str, str], SourcePin] = {}
        self._failed: dict[tuple[str, str], tuple[AdapterRefusal, float]] = {}
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- request side ----------------------------------------------------------------------

    def request(self, pin: SourcePin) -> str | AdapterRefusal:
        """READY, QUEUED, or the refusal of a recent failure; never blocks on embedding in background mode."""
        if pin.kind == "KnowledgeSource" and not pin.source_uri:
            return refuse("AI_SOURCE_UNAVAILABLE", f"Source {pin.document_id} has no source_uri")
        key = (pin.document_id, pin.content_hash or pin.document_version)
        if not self.background:
            try:
                self._warm(pin)
            except AdapterRefusal as exc:
                return _bare(exc)
            return READY
        with self._cond:
            failure = self._failed.get(key)
            if failure is not None:
                if failure[1] > self.clock():
                    return _bare(failure[0])
                del self._failed[key]
            self._queue.setdefault(key, pin)
            self._cond.notify()
        self.start()
        return QUEUED

    def pending(self) -> int:
        with self._cond:
            return len(self._queue)

    # ---- worker ----------------------------------------------------------------------------

    def start(self) -> None:
        if not self.background:
            return
        with self._cond:
            if self._thread is not None:
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="ai-source-warmer", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
            thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)

    def _requeue_incomplete(self) -> None:
        try:
            incomplete = self.index.incomplete_sources(self.provider.embedding_model)
        except Exception:
            log.exception("listing incomplete sources failed")
            return
        with self._cond:
            for src in incomplete:
                pin = SourcePin(
                    kind="KnowledgeSource", document_id=src.document_id, document_version=src.document_version,
                    title=src.title, content_hash=src.content_hash, source_uri=src.source_uri,
                )
                self._queue.setdefault((src.document_id, src.content_hash), pin)
        if incomplete:
            log.info("resuming %d partly embedded sources", len(incomplete))

    def _run(self) -> None:
        self._requeue_incomplete()
        while not self._stop.is_set():
            with self._cond:
                while not self._queue and not self._stop.is_set():
                    self._cond.wait()
                if self._stop.is_set():
                    return
                key, pin = next(iter(self._queue.items()))
            self.run_one(key, pin)

    def run_one(self, key: tuple[str, str], pin: SourcePin) -> None:
        """Embeds one queued source and settles it: done, or failed until source_retry_seconds pass."""
        failure: AdapterRefusal | None = None
        try:
            self._warm(pin)
        except _Stopped:
            return  # stays queued in the index as an incomplete source; resumed on the next start
        except AdapterRefusal as exc:
            failure = _bare(exc)
        except Exception:
            log.exception("source preparation failed", extra={"document_id": pin.document_id})
            failure = refuse("AI_TEMPORARILY_UNAVAILABLE", "Source preparation failed", status=503)
        with self._cond:
            self._queue.pop(key, None)
            if failure is not None:
                log.warning("source %s not prepared: %s", pin.document_id, failure.code)
                self._failed[key] = (failure, self.clock() + self.settings.source_retry_seconds)
            # Expired failures of keys never asked again (e.g. the source moved to a new hash) would stay forever.
            now = self.clock()
            for stale in [k for k, (_, until) in self._failed.items() if until <= now]:
                del self._failed[stale]

    def _sleep(self, seconds: float) -> None:
        if self._stop.wait(max(0.0, seconds)):
            raise _Stopped()

    def _warm(self, pin: SourcePin) -> None:
        if pin.kind != "KnowledgeSource":
            self._warm_inline(pin)
            return
        model = self.provider.embedding_model
        content_hash = pin.content_hash or ""
        if self.index.has_current(pin.document_id, content_hash, model):
            return
        data, content_type = fetch_document(
            pin.source_uri,
            content_hash,
            max_bytes=self.settings.source_max_bytes,
            timeout=self.settings.source_fetch_timeout_seconds,
            client=self.http,
        )
        chunks = chunk_sections(
            document_sections(data, content_type, _filename(pin.source_uri)), pin.document_id, pin.document_version
        )
        if not chunks:
            raise refuse("AI_SOURCE_UNAVAILABLE", f"Source {pin.document_id} has no readable text")
        done = self.index.indexed_chunks(pin.document_id, content_hash, model)
        missing = [chunk for chunk in chunks if chunk.chunk_index not in done]
        size = max(1, self.settings.embed_batch_size)
        log.info("embedding source %s: %d of %d chunks left", pin.document_id, len(missing), len(chunks))
        for start in range(0, len(missing), size):
            batch = missing[start:start + size]
            embeddings = self._embed([chunk.content for chunk in batch])
            self.index.add_chunks(
                pin.document_id, pin.document_version, content_hash, model, len(chunks), batch, embeddings,
                source_uri=pin.source_uri, title=pin.title,
            )
        log.info("source %s ready", pin.document_id)

    def _warm_inline(self, pin: SourcePin) -> None:
        """Inline content (sent with the question) only fills the embedding cache; nothing is fetched or indexed."""
        model = self.provider.embedding_model
        texts = [c.content for c in chunk_sections(inline_sections(pin), pin.document_id, pin.document_version)]
        missing = [t for t, v in zip(texts, self.inline_cache.get_many(model, texts)) if v is None]
        size = max(1, self.settings.embed_batch_size)
        if missing:
            log.info("embedding inline source %s: %d of %d chunks left", pin.document_id, len(missing), len(texts))
        for start in range(0, len(missing), size):
            batch = missing[start:start + size]
            self.inline_cache.put_many(model, batch, self._embed(batch))

    def _embed(self, texts: list[str]) -> list[list[float]]:
        limited = failed = 0
        while True:
            self.limiter.acquire(len(texts))
            self.token_limiter.acquire(sum(math.ceil(len(text) / CHARS_PER_TOKEN) for text in texts))
            try:
                return self.provider.embed(texts)
            except RateLimited as exc:
                limited += 1
                if limited >= _MAX_RATE_LIMITED:
                    raise refuse("AI_TEMPORARILY_UNAVAILABLE", "Embedding quota exhausted", status=503) from exc
                wait = exc.retry_after if exc.retry_after is not None else _DEFAULT_RATE_LIMIT_WAIT
                log.info("embedding rate limited, waiting %.0fs", wait)
                self._sleep(wait)
            except ProviderError as exc:
                failed += 1
                if failed >= _MAX_PROVIDER_FAILURES:
                    raise refuse("AI_TEMPORARILY_UNAVAILABLE", "Embedding provider unavailable", status=503) from exc
                self._sleep(5.0 * failed)
