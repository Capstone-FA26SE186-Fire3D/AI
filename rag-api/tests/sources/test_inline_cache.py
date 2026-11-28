"""Inline content is embedded once per process and reused (no per-question re-embedding)."""
import pytest

from app.answering.retrieval import retrieve
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.base import RateLimited
from app.llm.fake import FakeProvider
from app.sources.embedding_cache import EmbeddingCache
from app.sources.resolver import SourceResolver
from app.sources.warmer import SourceWarmer
from app.v2.errors import AdapterRefusal
from app.v2.schemas import SourcePin


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


def lesson(text="Rút chốt, hướng loa phun vào gốc lửa."):
    return SourcePin(
        kind="LearnPost", document_id="post-1", document_version="v1", title="Bài học", content_hash="h1",
        content={"title": "Bình chữa cháy", "summary": "Cách dùng bình chữa cháy xách tay",
                 "blocks": [{"type": "paragraph", "text": text}]},
    )


def library(blocks: int):
    return SourcePin(
        kind="LibraryVersion", document_id="item-1", document_version="1", title="Thư viện", content_hash="lib1",
        content={"kind": "Equipment", "code": "CO2", "payload": {f"muc{i}": f"Nội dung số {i} " * 80 for i in range(blocks)}},
    )


def setup(provider=None, sync_chunks=20, background=True):
    index, provider = MemoryIndex(), provider or CountingProvider()
    settings = Settings(_env_file=None, inline_sync_chunks=sync_chunks)
    warmer = SourceWarmer(index, provider, settings, background=background)
    warmer.start = lambda: None  # tests drive the queue by hand
    return SourceResolver(index, provider, settings, warmer=warmer), index, provider, warmer


def drain(warmer):
    while warmer.pending():
        key, pin = next(iter(warmer._queue.items()))
        warmer.run_one(key, pin)


def test_cache_lru_and_lengths():
    cache = EmbeddingCache(max_items=2)
    cache.put_many("m", ["a", "b"], [[1.0], [2.0]])
    assert cache.get_many("m", ["a"]) == [[1.0]]  # a is now most recent
    cache.put_many("m", ["c"], [[3.0]])
    assert cache.get_many("m", ["a", "b", "c"]) == [[1.0], None, [3.0]]
    assert cache.get_many("other-model", ["a"]) == [None]
    with pytest.raises(ValueError):
        cache.put_many("m", ["x"], [])


def test_small_inline_embedded_once_then_reused():
    resolver, index, provider, warmer = setup()
    first = resolver.prepare([lesson()])
    assert first.inline_chunks and len(first.inline_chunks) == len(first.inline_embeddings)
    assert len(provider.embedded) == 1 and warmer.pending() == 0
    second = resolver.prepare([lesson()])
    assert len(second.inline_chunks) == len(first.inline_chunks) and not second.limitations
    assert len(provider.embedded) == 1  # nothing re-embedded
    hits = retrieve("bình chữa cháy", second, index, provider)
    assert hits and hits[0].chunk.document_id == "post-1"


def test_edited_text_embeds_only_the_changed_chunk():
    resolver, _, provider, _ = setup()
    resolver.prepare([lesson()])
    resolver.prepare([lesson("Kéo chốt an toàn rồi bóp cò.")])
    assert provider.embedded[1] < provider.embedded[0]


def test_large_inline_waits_for_warmer_then_is_reused():
    resolver, _, provider, warmer = setup(sync_chunks=1)
    with pytest.raises(AdapterRefusal) as err:
        resolver.prepare([library(5)])
    assert err.value.code == "AI_SOURCES_PREPARING" and provider.embedded == []
    drain(warmer)
    calls = len(provider.embedded)
    ready = resolver.prepare([library(5)])
    assert ready.inline_chunks and not ready.limitations
    assert len(provider.embedded) == calls


def test_partly_cached_inline_is_used_with_a_limitation():
    resolver, _, _, warmer = setup(sync_chunks=1)
    full = library(5)
    with pytest.raises(AdapterRefusal):
        resolver.prepare([library(2)])  # same first chunks, different hash
    drain(warmer)
    prepared = resolver.prepare([full])
    assert prepared.inline_chunks
    assert prepared.limitations == ["Nguồn Thư viện mới dùng được một phần, phần còn lại đang được chuẩn bị."]
    assert warmer.pending() == 1


def test_large_inline_preparing_does_not_block_a_ready_source():
    resolver, _, _, _ = setup(sync_chunks=3)
    prepared = resolver.prepare([lesson(), library(5)])
    assert {c.document_id for c in prepared.inline_chunks} == {"post-1"}
    assert prepared.limitations == ["Nguồn Thư viện đang được chuẩn bị, chưa dùng cho câu hỏi này."]


def test_rate_limited_direct_embed_falls_back_to_warmer():
    resolver, _, _, warmer = setup(provider=CountingProvider(fail=1))
    with pytest.raises(AdapterRefusal) as err:
        resolver.prepare([lesson()])
    assert err.value.code == "AI_SOURCES_PREPARING" and warmer.pending() == 1
    drain(warmer)
    assert resolver.prepare([lesson()]).inline_chunks


def test_inline_without_hash_or_uri_is_queued_not_refused():
    resolver, _, _, warmer = setup(provider=CountingProvider(fail=1))
    pin = lesson().model_copy(update={"content_hash": None})
    with pytest.raises(AdapterRefusal) as err:
        resolver.prepare([pin])
    assert err.value.code == "AI_SOURCES_PREPARING" and warmer.pending() == 1


def test_direct_embedding_budget_is_shared_by_all_inline_sources():
    resolver, _, provider, warmer = setup(sync_chunks=3)
    pins = [lesson().model_copy(update={"document_id": f"post-{i}", "content": {"title": f"Bài {i} bình chữa cháy"}})
            for i in range(6)]
    prepared = resolver.prepare(pins)
    assert sum(provider.embedded) == 3  # not 6: the budget is per question, not per source
    assert warmer.pending() == 3 and len(prepared.inline_chunks) == 3


def test_direct_embedding_stops_after_a_provider_error():
    resolver, _, provider, warmer = setup(provider=CountingProvider(fail=1), sync_chunks=20)
    pins = [lesson().model_copy(update={"document_id": f"post-{i}", "content": {"title": f"Bài {i}"}}) for i in range(4)]
    with pytest.raises(AdapterRefusal):
        resolver.prepare(pins)
    assert provider.embedded == [] and warmer.pending() == 4


# ---- AI#43: the cache survives a restart when it has a path ----------------------------------------------------------


def test_cache_persists_and_reloads_in_lru_order(tmp_path):
    path = tmp_path / "data" / "inline.npz"
    cache = EmbeddingCache(max_items=10, path=path, save_interval=3600)
    cache.put_many("m", ["a", "b"], [[1.0, 0.0], [0.0, 1.0]])
    cache.put_many("other", ["a"], [[0.5, 0.5, 0.5]])
    cache.get_many("m", ["a"])  # a becomes the most recent of model m
    assert not path.exists()  # inside save_interval: nothing written yet
    assert cache.flush() and path.is_file()
    assert not cache.flush()  # unchanged since the last write

    again = EmbeddingCache(max_items=2, path=path)
    assert len(again) == 2  # the oldest entry (m/b) is dropped to fit the new limit
    assert again.get_many("m", ["a", "b"]) == [[1.0, 0.0], None]
    assert again.get_many("other", ["a"]) == [[0.5, 0.5, 0.5]]


def test_put_writes_once_interval_passed(tmp_path):
    now = [0.0]
    path = tmp_path / "inline.npz"
    cache = EmbeddingCache(path=path, save_interval=5, clock=lambda: now[0])
    cache.put_many("m", ["a"], [[1.0]])
    assert not path.exists()
    now[0] = 6.0
    cache.put_many("m", ["b"], [[2.0]])
    assert path.is_file()
    assert EmbeddingCache(path=path).get_many("m", ["a", "b"]) == [[1.0], [2.0]]


@pytest.mark.parametrize("content", [b"", b"not a zip", None])
def test_unreadable_or_foreign_file_starts_empty(tmp_path, content):
    path = tmp_path / "inline.npz"
    if content is None:
        import numpy as np

        np.savez(path, format=np.array("something-else/9"), models=np.array([], dtype="<U1"))
    else:
        path.write_bytes(content)
    cache = EmbeddingCache(path=path)
    assert len(cache) == 0
    cache.put_many("m", ["a"], [[1.0]])
    assert cache.flush()
    assert EmbeddingCache(path=path).get_many("m", ["a"]) == [[1.0]]


def test_failed_write_keeps_serving_and_retries(tmp_path, monkeypatch):
    path = tmp_path / "inline.npz"
    cache = EmbeddingCache(path=path, save_interval=3600)
    cache.put_many("m", ["a"], [[1.0]])
    monkeypatch.setattr(cache, "_write", lambda entries: (_ for _ in ()).throw(OSError("disk full")))
    assert not cache.flush()
    assert cache.get_many("m", ["a"]) == [[1.0]]
    monkeypatch.undo()
    assert cache.flush() and path.is_file()


def test_warmer_restart_reuses_saved_lessons(tmp_path):
    path = str(tmp_path / "inline.npz")
    provider = CountingProvider()
    settings = Settings(_env_file=None, inline_sync_chunks=0, inline_cache_path=path)
    warmer = SourceWarmer(MemoryIndex(), provider, settings, background=False)
    resolver = SourceResolver(warmer.index, provider, settings, warmer=warmer)
    first = resolver.prepare([lesson()])
    assert first.inline_chunks and provider.embedded  # embedded by the (foreground) warmer, then written to disk
    warmer.stop()

    restarted_provider = CountingProvider()
    warmer2 = SourceWarmer(MemoryIndex(), restarted_provider, settings, background=False)
    resolver2 = SourceResolver(warmer2.index, restarted_provider, settings, warmer=warmer2)
    second = resolver2.prepare([lesson()])
    assert len(second.inline_chunks) == len(first.inline_chunks)
    assert restarted_provider.embedded == []  # nothing embedded again after the restart
