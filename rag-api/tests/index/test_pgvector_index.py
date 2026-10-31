import uuid

import psycopg
import pytest
from app.index.pgvector import PgVectorIndex
from app.sources.chunking import Chunk

pytestmark = pytest.mark.pgvector


@pytest.fixture
def idx(pg_dsn):
    return PgVectorIndex(pg_dsn)


def _source(pg_dsn, status="Approved"):
    sid = str(uuid.uuid4())
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO knowledge_sources(id, organization_id, status) VALUES (%s, %s, %s)",
            (sid, str(uuid.uuid4()), status),
        )
    return sid


def _chunks(doc, version="v1", n=2, prefix="bình chữa cháy"):
    return [Chunk("x", doc, version, i, f"{prefix} {i}", {"page": i + 1}, "Trang") for i in range(n)]


def _emb(n=2):
    return [[1.0, 0.0, 0.0] if i == 0 else [0.8, 0.2, 0.0] for i in range(n)]


def test_replace_and_search_scoped(pg_dsn, idx):
    a, b = _source(pg_dsn), _source(pg_dsn)
    idx.replace(a, "va", "ha", "m1", _chunks(a, "va"), _emb())
    idx.replace(b, "vb", "hb", "m1", _chunks(b, "vb"), _emb())
    out = idx.search("bình chữa cháy", [1.0, 0.0, 0.0], [a, "not-a-uuid"], "m1", 5)
    assert out and all(s.chunk.document_id == a for s in out)
    first = out[0]
    assert first.score == 1.0 and first.chunk.document_version == "va"
    assert first.chunk.locator["page"] in (1, 2)
    assert first.chunk.excerpt_locator.startswith("Trang")
    uuid.UUID(first.chunk.chunk_id)
    assert idx.search("bình", [1.0, 0.0, 0.0], ["junk"], "m1", 5) == []
    assert idx.has_current(a, "ha", "m1") and not idx.has_current(a, "ha", "m2")


def test_replace_drops_old_version_chunks(pg_dsn, idx):
    a = _source(pg_dsn)
    idx.replace(a, "v1", "h1", "m1", _chunks(a, "v1", 3), _emb(3))
    idx.replace(a, "v2", "h2", "m1", _chunks(a, "v2", 1, "mới"), _emb(1))
    with psycopg.connect(pg_dsn) as conn:
        n = conn.execute("SELECT count(*) FROM knowledge_chunks WHERE source_id=%s", (a,)).fetchone()[0]
    assert n == 1
    out = idx.search("mới", [1.0, 0.0, 0.0], [a], "m1", 5)
    assert [s.chunk.document_version for s in out] == ["v2"]
    assert not idx.has_current(a, "h1", "m1")


def test_other_embedding_model_not_returned(pg_dsn, idx):
    a = _source(pg_dsn)
    idx.replace(a, "v1", "h1", "m1", _chunks(a), _emb())
    assert idx.search("bình chữa cháy", [1.0, 0.0, 0.0], [a], "m2", 5) == []


def test_prune_ineligible_removes_retired(pg_dsn, idx):
    a = _source(pg_dsn)
    idx.replace(a, "v1", "h1", "m1", _chunks(a), _emb())
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("UPDATE knowledge_sources SET status='Retired' WHERE id=%s", (a,))
    assert idx.prune_ineligible() > 0
    assert idx.search("bình", [1.0, 0.0, 0.0], [a], "m1", 5) == []


def test_indexer_role_exists(pg_dsn):
    with psycopg.connect(pg_dsn) as conn:
        row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname='fet3d_ai_indexer'").fetchone()
    assert row is not None


def test_add_chunks_in_batches_complete_and_resume(pg_dsn, idx):
    a = _source(pg_dsn)
    chunks, embs = _chunks(a, "v1", 3), [[1.0, 0.0, 0.0], [0.8, 0.2, 0.0], [0.6, 0.4, 0.0]]
    idx.add_chunks(a, "v1", "h1", "m1", 3, chunks[:1], embs[:1], source_uri="https://kb/a.pdf", title="A")
    assert not idx.has_current(a, "h1", "m1")
    assert idx.indexed_chunks(a, "h1", "m1") == {0}
    [pending] = idx.incomplete_sources("m1")
    assert (pending.document_id, pending.content_hash, pending.source_uri, pending.title) == (a, "h1", "https://kb/a.pdf", "A")
    idx.add_chunks(a, "v1", "h1", "m1", 3, chunks[:2], embs[:2], source_uri="https://kb/a.pdf")  # repeat is harmless
    idx.add_chunks(a, "v1", "h1", "m1", 3, chunks[2:], embs[2:], source_uri="https://kb/a.pdf")
    assert idx.has_current(a, "h1", "m1")
    assert idx.incomplete_sources("m1") == []
    idx.add_chunks(a, "v2", "h2", "m1", 1, _chunks(a, "v2", 1), _emb(1))
    assert not idx.has_current(a, "h1", "m1") and idx.has_current(a, "h2", "m1")
