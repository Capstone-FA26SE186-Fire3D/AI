"""Inline content with a hash is embedded once and reused from the index (no per-question re-embedding)."""
import pytest

from app.answering.retrieval import retrieve
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.base import RateLimited
from app.llm.fake import FakeProvider
from app.sources.resolver import SourceResolver
from app.sources.warmer import SourceWarmer
from app.v2.errors import AdapterRefusal
from app.v2.schemas import SourcePin

POST = "11111111-1111-4111-8111-111111111111"
ITEM = "22222222-2222-4222-8222-222222222222"


class CountingProvider(FakeProvider):
    def __init__(self, fail: int = 0):
        super().__init__()
        self.embedded: list[int] = []
        self.fail = fail

    def embed(self, texts):
        if self.fail:
            self.fail -= 1
            raise RateLimited("quota", 0)
        self.embedded.append(len(texts))
        return super().embed(texts)


def lesson(hash_="h1", doc=POST, version="v1"):
    return SourcePin(
        kind="LearnPost", document_id=doc, document_version=version, title="Bài học", content_hash=hash_,
        content={"title": "Bình chữa cháy", "summary": "Cách dùng bình chữa cháy xách tay",
                 "blocks": [{"type": "paragraph", "text": "Rút chốt, hướng loa phun vào gốc lửa."}]},
    )


def library(blocks: int, hash_="lib1"):
    return SourcePin(
        kind="LibraryVersion", document_id=ITEM, document_version="1", title="Thư viện", content_hash=hash_,
        content={"kind": "Equipment", "code": "CO2", "payload": {f"muc{i}": f"Nội dung số {i} " * 80 for i in range(blocks)}},
    )


def setup(provider=None, sync_chunks=20, background=False):
    index, provider = MemoryIndex(), provider or CountingProvider()
    settings = Settings(_env_file=None, inline_sync_chunks=sync_chunks, embed_items_per_minute=10_000, embed_tokens_per_minute=10_000_000)
    warmer = SourceWarmer(index, provider, settings, background=background)
    return SourceResolver(index, provider, settings, warmer=warmer), index, provider, warmer


def test_small_inline_embedded_once_then_reused():
    resolver, index, provider, _ = setup()
    first = resolver.prepare([lesson()])
    assert first.knowledge_ids == [POST] and not first.inline_chunks
    assert len(provider.embedded) == 1
    second = resolver.prepare([lesson()])
    assert second.knowledge_ids == [POST]
    assert len(provider.embedded) == 1  # nothing re-embedded
    hits = retrieve("bình chữa cháy", second, index, provider)
    assert hits and hits[0].chunk.document_id == POST


def test_changed_hash_embeds_again():
    resolver, _, provider, _ = setup()
    resolver.prepare([lesson("h1")])
    resolver.prepare([lesson("h2", version="v2")])
    assert len(provider.embedded) == 2


def test_large_inline_goes_to_warmer_and_is_used_once_ready():
    resolver, index, provider, warmer = setup(sync_chunks=1, background=True)
    with pytest.raises(AdapterRefusal) as err:
        resolver.prepare([library(5)])
    assert err.value.code == "AI_SOURCES_PREPARING" and provider.embedded == []
    assert warmer.pending() == 1
    key, pin = next(iter(warmer._queue.items()))
    warmer.run_one(key, pin)
    ready = resolver.prepare([library(5)])
    assert ready.knowledge_ids == [ITEM] and not ready.limitations


def test_large_inline_preparing_does_not_block_a_ready_source():
    resolver, _, _, _ = setup(sync_chunks=3, background=True)
    prepared = resolver.prepare([lesson(), library(5)])
    assert prepared.knowledge_ids == [POST]
    assert prepared.limitations == ["Nguồn Thư viện đang được chuẩn bị, chưa dùng cho câu hỏi này."]


def test_direct_embed_rate_limited_falls_back_to_warmer():
    resolver, _, provider, warmer = setup(provider=CountingProvider(fail=1), background=True)
    with pytest.raises(AdapterRefusal) as err:
        resolver.prepare([lesson()])
    assert err.value.code == "AI_SOURCES_PREPARING"
    assert warmer.pending() == 1


@pytest.mark.parametrize("pin", [
    lesson(hash_=None),
    lesson(doc="lp-not-a-uuid"),
])
def test_without_hash_or_uuid_embeds_per_question(pin):
    resolver, _, provider, _ = setup()
    for _ in range(2):
        prepared = resolver.prepare([pin])
        assert prepared.inline_chunks and prepared.knowledge_ids == []
    assert len(provider.embedded) == 2


def test_restart_does_not_requeue_inline_sources():
    resolver, index, provider, warmer = setup(sync_chunks=1, background=True)
    with pytest.raises(AdapterRefusal):
        resolver.prepare([library(5)])
    key, pin = next(iter(warmer._queue.items()))
    index.add_chunks(ITEM, "1", "lib1", provider.embedding_model, 99, [], [])  # leave it incomplete
    fresh = SourceWarmer(index, provider, Settings(_env_file=None), background=True)
    fresh._requeue_incomplete()
    assert fresh.pending() == 0
