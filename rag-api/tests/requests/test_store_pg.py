import time
from datetime import datetime, timezone

import pytest
from app.requests.store import make_store

pytestmark = pytest.mark.pgvector


def test_postgres_store_against_migration(pg_dsn):
    store = make_store(pg_dsn)
    assert store.insert_received("pg1", "ask", "org", "a" * 64, {"q": "xin chào"}) is True
    assert store.insert_received("pg1", "ask", "org", "a" * 64, {"q": "x"}) is False
    store.mark_processing("pg1")
    rec = store.get("pg1")
    assert rec.status == "Processing" and rec.attempts == 1
    cutoff = datetime.now(timezone.utc)
    time.sleep(0.05)
    claimed = store.claim_stale(cutoff)
    assert claimed is not None and claimed.request_id == "pg1" and claimed.attempts == 2
    assert store.claim_stale(cutoff) is None
    store.complete("pg1", {"answer": "ok"}, {"total_tokens": 7})
    rec = store.get("pg1")
    assert rec.status == "Completed" and rec.response == {"answer": "ok"}
    assert rec.usage_total == {"total_tokens": 7} and rec.payload == {"q": "xin chào"}
    store.delete("pg1")
    assert store.get("pg1") is None
