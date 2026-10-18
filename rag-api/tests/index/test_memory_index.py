from app.index.memory import MemoryIndex
from app.sources.chunking import Chunk


def _chunks(doc, version="v1"):
    return [Chunk(f"{doc}-{i}", doc, version, i, f"bình chữa cháy {i}", {}, "Toàn văn") for i in range(2)]


def _fill(idx, doc, h="h1", model="m1"):
    idx.replace(doc, "v1", h, model, _chunks(doc), [[1.0, 0.0], [0.9, 0.1]])


def test_search_limited_to_document_ids():
    idx = MemoryIndex()
    _fill(idx, "A")
    _fill(idx, "B")
    out = idx.search("bình chữa cháy", [1.0, 0.0], ["A"], "m1", 5)
    assert out and all(s.chunk.document_id == "A" for s in out)
    assert idx.search("bình", [1.0, 0.0], [], "m1", 5) == []


def test_has_current_by_hash_and_model():
    idx = MemoryIndex()
    _fill(idx, "A")
    assert idx.has_current("A", "h1", "m1")
    assert not idx.has_current("A", "h2", "m1")
    assert not idx.has_current("A", "h1", "m2")
    assert not idx.has_current("B", "h1", "m1")


def test_other_model_not_returned_and_prune_is_noop():
    idx = MemoryIndex()
    _fill(idx, "A")
    assert idx.search("bình", [1.0, 0.0], ["A"], "other", 5) == []
    idx.eligible["A"] = False
    assert idx.prune_ineligible() == 0
