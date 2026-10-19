import hashlib

import httpx
import pytest

from app.answering.retrieval import retrieve
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.fake import FakeProvider
from app.sources.resolver import SourceResolver
from app.v2.errors import AdapterRefusal
from app.v2.schemas import SourcePin


def _setup(bodies):
    """bodies: dict url -> bytes. Returns (resolver, index, provider, fetch_log)."""
    log = []

    def handler(request):
        log.append(str(request.url))
        return httpx.Response(200, content=bodies[str(request.url)], headers={"content-type": "text/plain"})

    index = MemoryIndex()
    provider = FakeProvider()
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return SourceResolver(index, provider, Settings(), http=http), index, provider, log


def _pin(url, body, version="v1", doc="doc-1"):
    return SourcePin(
        kind="KnowledgeSource", document_id=doc, document_version=version, title="Tài liệu",
        content_hash=hashlib.sha256(body).hexdigest(), source_uri=url,
    )


def test_knowledge_source_fetched_and_indexed_once():
    url = "https://files.example/a.txt"
    body = b"Loi thoat hiem phai thong thoang."
    resolver, index, provider, log = _setup({url: body})
    pin = _pin(url, body)
    first = resolver.prepare([pin])
    second = resolver.prepare([pin])
    assert len(log) == 1
    assert first.knowledge_ids == second.knowledge_ids == ["doc-1"]
    assert first.pins["doc-1"] is pin
    hits = retrieve("loi thoat hiem", first, index, provider)
    assert hits and all(h.chunk.document_id == "doc-1" for h in hits)
    assert all(0 <= h.score <= 1 for h in hits)


def test_knowledge_source_reindexed_on_new_hash():
    url = "https://files.example/a.txt"
    old, new = b"noi dung cu", b"noi dung moi hoan toan"
    bodies = {url: old}
    resolver, index, provider, log = _setup(bodies)
    resolver.prepare([_pin(url, old, "v1")])
    bodies[url] = new
    prepared = resolver.prepare([_pin(url, new, "v2")])
    assert len(log) == 2
    hits = retrieve("noi dung", prepared, index, provider)
    assert hits and {h.chunk.document_version for h in hits} == {"v2"}


def test_missing_uri_refused_unavailable():
    resolver, *_ = _setup({})
    pin = SourcePin(kind="KnowledgeSource", document_id="d", document_version="v1", content_hash="a" * 64)
    with pytest.raises(AdapterRefusal) as exc:
        resolver.prepare([pin])
    assert exc.value.code == "AI_SOURCE_UNAVAILABLE"


def test_missing_hash_refused_even_if_indexed():
    url = "https://files.example/a.txt"
    body = b"abc def"
    resolver, *_ = _setup({url: body})
    resolver.prepare([_pin(url, body)])
    pin = SourcePin(kind="KnowledgeSource", document_id="doc-1", document_version="v1", source_uri=url)
    with pytest.raises(AdapterRefusal) as exc:
        resolver.prepare([pin])
    assert exc.value.code == "AI_SOURCE_UNAVAILABLE"


def test_inline_learnpost_chunks():
    resolver, index, provider, log = _setup({})
    pin = SourcePin(
        kind="LearnPost", document_id="lp-1", document_version="3", title="Bài học",
        content={"title": "Bình chữa cháy", "summary": "Cách dùng bình chữa cháy xách tay"},
    )
    prepared = resolver.prepare([pin])
    assert prepared.knowledge_ids == []
    assert prepared.inline_chunks and len(prepared.inline_chunks) == len(prepared.inline_embeddings)
    hits = retrieve("bình chữa cháy", prepared, index, provider)
    assert hits and hits[0].chunk.document_id == "lp-1"
    assert log == []


def test_content_omitted_adds_limitation():
    resolver, *_ = _setup({})
    pin = SourcePin(kind="LearnPost", document_id="x", document_version="1", title="Lớn", content_omitted=True)
    prepared = resolver.prepare([pin])
    assert prepared.limitations == ["Nguồn Lớn quá lớn, không được dùng."]
    assert not prepared.inline_chunks and not prepared.pins


def test_no_usable_pins_retrieves_nothing():
    resolver, index, provider, _ = _setup({})
    prepared = resolver.prepare([])
    assert retrieve("q", prepared, index, provider) == []
    assert provider.calls == []


def test_total_fetch_deadline_refuses_new_fetches():
    bodies = {f"https://files.example/{i}.txt": f"noi dung {i}".encode() for i in range(3)}
    resolver, index, provider, log = _setup(bodies)
    ticks = iter([0.0, 10.0, 61.0, 61.0, 61.0])
    resolver.clock = lambda: next(ticks)
    pins = [_pin(url, body, doc=f"doc-{i}") for i, (url, body) in enumerate(bodies.items())]
    with pytest.raises(AdapterRefusal) as exc:
        resolver.prepare(pins)
    assert exc.value.code == "AI_SOURCE_UNAVAILABLE"
    assert len(log) == 1
    assert Settings().source_total_deadline_seconds == 60


def test_already_indexed_sources_ignore_deadline():
    url = "https://files.example/a.txt"
    body = b"abc def"
    resolver, index, provider, log = _setup({url: body})
    resolver.prepare([_pin(url, body)])
    ticks = iter([0.0, 999.0, 999.0])
    resolver.clock = lambda: next(ticks)
    assert resolver.prepare([_pin(url, body)]).knowledge_ids == ["doc-1"]
