import hashlib

import httpx
import pytest

from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.base import RateLimited
from app.llm.fake import FakeProvider
from app.sources.chunking import chunk_sections
from app.sources.render import document_sections
from app.sources.resolver import SourceResolver
from app.sources.warmer import QUEUED, READY, RateLimiter, SourceWarmer
from app.v2.errors import AdapterRefusal
from app.v2.schemas import SourcePin

URL = "https://files.example/a.txt"
# Enough paragraphs for several chunks, so batches and resume are observable.
LONG = "\n\n".join(f"Đoạn {i}: lối thoát nạn số {i} phải luôn thông thoáng và có đèn chỉ dẫn. " * 30 for i in range(8)).encode()


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class CountingProvider(FakeProvider):
    def __init__(self, fail_on: set[int] | None = None, rate_limited: int = 0) -> None:
        super().__init__()
        self.embed_calls: list[int] = []
        self.fail_on = fail_on or set()
        self.rate_limited = rate_limited

    def embed(self, texts):
        if self.rate_limited:
            self.rate_limited -= 1
            raise RateLimited("429", retry_after=7)
        self.embed_calls.append(len(texts))
        if len(self.embed_calls) in self.fail_on:
            raise RuntimeError("process killed")
        return super().embed(texts)


def _http(body, log=None):
    def handler(request):
        if log is not None:
            log.append(str(request.url))
        return httpx.Response(200, content=body, headers={"content-type": "text/plain"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _pin(body, doc="doc-1", title="QCVN 06"):
    return SourcePin(
        kind="KnowledgeSource", document_id=doc, document_version="v1", title=title,
        content_hash=hashlib.sha256(body).hexdigest(), source_uri=URL,
    )


def _background(body, provider=None, log=None, **settings):
    """Background warmer whose thread never starts: tests drain it with drain()."""
    index = MemoryIndex()
    provider = provider or CountingProvider()
    clock = Clock()
    warmer = SourceWarmer(index, provider, Settings(**settings), _http(body, log), clock=clock)
    sleeps: list[float] = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock.now += seconds

    warmer.start = lambda: None
    warmer._sleep = warmer.limiter.sleep = sleep
    warmer.sleeps = sleeps
    return warmer, index, provider, clock


def drain(warmer):
    while warmer._queue:
        key, pin = next(iter(warmer._queue.items()))
        warmer.run_one(key, pin)


def _chunk_count(body):
    return len(chunk_sections(document_sections(body, "text/plain", "a.txt"), "doc-1", "v1"))


def test_question_does_not_wait_for_embedding():
    log = []
    warmer, index, provider, _ = _background(LONG, log=log)
    resolver = SourceResolver(index, provider, warmer.settings, warmer=warmer)
    with pytest.raises(AdapterRefusal) as exc:
        resolver.prepare([_pin(LONG)])
    assert (exc.value.code, exc.value.status_code) == ("AI_SOURCES_PREPARING", 503)
    assert log == [] and provider.embed_calls == []
    drain(warmer)
    assert resolver.prepare([_pin(LONG)]).knowledge_ids == ["doc-1"]
    assert len(log) == 1


def test_ready_sources_answer_while_others_prepare():
    other = b"Binh chua chay xach tay dat o noi de thay."
    warmer, index, provider, _ = _background(LONG)
    resolver = SourceResolver(index, provider, warmer.settings, warmer=warmer)
    warmer.request(_pin(LONG, doc="ready"))
    drain(warmer)
    prepared = resolver.prepare([_pin(LONG, doc="ready"), _pin(other, doc="new", title="TCVN 3890")])
    assert prepared.knowledge_ids == ["ready"]
    assert prepared.limitations == ["Nguồn TCVN 3890 đang được chuẩn bị, chưa dùng cho câu hỏi này."]
    assert warmer.pending() == 1


def test_inline_source_answers_while_knowledge_prepares():
    warmer, index, provider, _ = _background(LONG)
    resolver = SourceResolver(index, provider, warmer.settings, warmer=warmer)
    inline = SourcePin(kind="LearnPost", document_id="lp", document_version="1", content={"title": "Thoát nạn"})
    prepared = resolver.prepare([inline, _pin(LONG)])
    assert prepared.inline_chunks and prepared.knowledge_ids == []
    assert len(prepared.limitations) == 1


def test_batches_respect_size_and_rate():
    warmer, index, provider, _ = _background(LONG, embed_batch_size=2, embed_items_per_minute=4)
    warmer.request(_pin(LONG))
    drain(warmer)
    total = _chunk_count(LONG)
    assert total >= 3
    assert sum(provider.embed_calls) == total and max(provider.embed_calls) <= 2
    assert index.has_current("doc-1", _pin(LONG).content_hash, provider.embedding_model)


def test_rate_limited_waits_retry_delay_then_continues():
    provider = CountingProvider(rate_limited=1)
    warmer, index, provider, _ = _background(LONG, provider=provider)
    warmer.request(_pin(LONG))
    drain(warmer)
    assert 7 in warmer.sleeps
    assert index.has_current("doc-1", _pin(LONG).content_hash, provider.embedding_model)


def test_interrupted_embedding_resumes_with_missing_chunks_only():
    provider = CountingProvider(fail_on={2})
    warmer, index, provider, clock = _background(LONG, provider=provider, embed_batch_size=1)
    pin = _pin(LONG)
    warmer.request(pin)
    drain(warmer)
    stored = index.indexed_chunks("doc-1", pin.content_hash, provider.embedding_model)
    assert stored == {0}
    assert not index.has_current("doc-1", pin.content_hash, provider.embedding_model)
    # Restart: a fresh warmer finds the partial source on its own and embeds only what is missing.
    restarted = SourceWarmer(index, CountingProvider(), warmer.settings, _http(LONG))
    restarted.start = lambda: None
    restarted._requeue_incomplete()
    assert restarted.pending() == 1
    drain(restarted)
    assert sum(restarted.provider.embed_calls) == _chunk_count(LONG) - 1
    assert index.has_current("doc-1", pin.content_hash, provider.embedding_model)


def test_failure_is_remembered_then_retried():
    other = b"noi dung khac"
    warmer, index, provider, clock = _background(other, source_retry_seconds=300)
    resolver = SourceResolver(index, provider, warmer.settings, warmer=warmer)
    pin = _pin(LONG)  # hash of LONG, server returns other bytes
    warmer.request(pin)
    drain(warmer)
    with pytest.raises(AdapterRefusal) as exc:
        resolver.prepare([pin])
    assert exc.value.code == "AI_SOURCE_HASH_MISMATCH"
    clock.now = 301
    assert warmer.request(pin) == QUEUED


def test_synchronous_mode_embeds_inside_request():
    warmer = SourceWarmer(MemoryIndex(), CountingProvider(), Settings(), _http(LONG), background=False)
    assert warmer.request(_pin(LONG)) == READY
    missing = SourcePin(kind="KnowledgeSource", document_id="x", document_version="1", content_hash="a" * 64)
    assert warmer.request(missing).code == "AI_SOURCE_UNAVAILABLE"


def test_rate_limiter_window():
    clock = Clock()
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock.now += seconds

    limiter = RateLimiter(4, clock, sleep)
    limiter.acquire(3)
    clock.now = 10
    limiter.acquire(1)
    assert sleeps == []
    limiter.acquire(2)
    assert sleeps == [50]
