import time
from datetime import datetime, timedelta, timezone

import pytest
from app.requests.store import RequestStore, make_store


@pytest.fixture
def store(tmp_path):
    return make_store(f"sqlite:///{tmp_path / 'req.db'}")


def _insert(store, rid="r1"):
    return store.insert_received(rid, "ask", "org", "a" * 64, {"q": "xin chào"})


def test_insert_twice_returns_false(store):
    assert _insert(store) is True
    assert _insert(store) is False


def test_lifecycle_received_processing_completed(store):
    assert store.get("r1") is None
    _insert(store)
    rec = store.get("r1")
    assert rec.status == "Received" and rec.attempts == 0
    assert rec.processing_started_at is None
    assert rec.created_at.tzinfo is not None

    store.mark_processing("r1")
    rec = store.get("r1")
    assert rec.status == "Processing" and rec.attempts == 1
    assert rec.processing_started_at.utcoffset() == timedelta(0)

    resp = {"answer": "Bình chữa cháy đặt gần lối thoát"}
    store.complete("r1", resp, {"total_tokens": 7})
    rec = store.get("r1")
    assert rec.status == "Completed" and rec.attempts == 1
    assert rec.response == resp and rec.usage_total == {"total_tokens": 7}
    assert rec.payload == {"q": "xin chào"}

    store.delete("r1")
    assert store.get("r1") is None


def test_claim_stale_only_old_processing(store):
    _insert(store, "old")
    store.mark_processing("old")
    cutoff = datetime.now(timezone.utc)
    time.sleep(0.02)
    _insert(store, "fresh")
    store.mark_processing("fresh")
    _insert(store, "recv")  # Received rows are never claimed

    claimed = store.claim_stale(cutoff)
    assert claimed is not None and claimed.request_id == "old"
    assert claimed.attempts == 2
    assert store.claim_stale(cutoff) is None  # already claimed; fresh not stale
    assert store.get("fresh").attempts == 1


def test_claim_is_compare_and_set(store):
    _insert(store)
    store.mark_processing("r1")
    cutoff = datetime.now(timezone.utc)
    time.sleep(0.02)
    assert store.claim_stale(cutoff).attempts == 2
    assert store.claim_stale(cutoff) is None
    assert store.get("r1").attempts == 2


def test_purge_stale_received_keeps_processing(store):
    _insert(store, "recv")
    _insert(store, "proc")
    store.mark_processing("proc")
    cutoff = datetime.now(timezone.utc) + timedelta(seconds=1)
    assert store.purge_stale_received(cutoff) == 1
    assert store.get("recv") is None
    assert store.get("proc") is not None


def test_mark_processing_only_from_received(store):
    assert store.mark_processing("missing") is False
    _insert(store)
    assert store.mark_processing("r1") is True
    assert store.mark_processing("r1") is False  # already Processing
    assert store.get("r1").attempts == 1
    assert store.complete("r1", {"a": 1}, {"t": 1}) is True
    assert store.mark_processing("r1") is False  # Completed stays Completed
    assert store.get("r1").status == "Completed"


def test_complete_only_from_processing(store):
    _insert(store)
    assert store.complete("r1", {"a": 1}, {"t": 1}) is False  # still Received
    assert store.get("r1").status == "Received"
    store.mark_processing("r1")
    assert store.complete("r1", {"a": 1}, {"t": 1}) is True
    assert store.complete("r1", {"a": 2}, {"t": 2}) is False  # no overwrite
    rec = store.get("r1")
    assert rec.response == {"a": 1} and rec.usage_total == {"t": 1}
