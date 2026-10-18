import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.answering.pipeline import PipelineDeps
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.base import ProviderError
from app.llm.fake import FakeProvider
from app.requests.service import RequestService
from app.requests.store import make_store
from app.sources.resolver import SourceResolver
from app.v2.schemas import AdapterRequest

HASH = "b" * 64


def _body(rid="req-1", text="bình chữa cháy dùng thế nào", input_hash=HASH, **over):
    body = {
        "request_id": rid, "audience": "organization", "operation": "Answer", "response_type": "KnowledgeAnswer",
        "organization_id": "org-1", "input": {"text": text}, "input_hash": input_hash,
        "sources": [{
            "kind": "LearnPost", "document_id": "lp-1", "document_version": "3", "title": "Bài học",
            "content": {"title": "Bình chữa cháy", "summary": "Cách dùng bình chữa cháy xách tay"},
        }],
        "limits": {"quota_unit": "tokens", "max_units": 20000},
    }
    body.update(over)
    return body


def _cite(payload):
    cid = payload["chunks"][0]["chunk_id"]
    return {"status": "answered", "answer": "Dùng bình theo hướng dẫn.",
            "citations": [{"chunk_id": cid, "relevance": 0.9}], "assumptions": [], "limitations": []}


def _service(db_url, responder=_cite, store=None):
    settings = Settings(llm_provider="fake", database_url=db_url, recovery_interval_seconds=0, ai_api_key="")
    provider = FakeProvider(responder)
    index = MemoryIndex()
    store = store or make_store(db_url)
    return RequestService(store, SourceResolver(index, provider, settings), PipelineDeps(provider, index, settings)), provider


@pytest.fixture
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'svc.db'}"


def test_recover_once_completes_stale_and_sums_usage(db_url):
    """A run that crashes after provider.generate leaves its usage persisted; recovery adds to it."""
    service, provider = _service(db_url)
    req = AdapterRequest.model_validate(_body())
    store = service.store
    original_complete = store.complete

    def crash(*a, **k):
        raise RuntimeError("process died after generate")

    store.complete = crash
    status, body = service.submit("organization/answer", req)
    assert status == 500 and body["code"] == "AI_OUTCOME_UNKNOWN"
    assert len(provider.calls) == 1
    first = store.get(req.request_id).usage_total
    assert store.get(req.request_id).status == "Processing"
    assert first["provider_units"] > 0
    assert first["provider_units"] == first["input_tokens"] + first["output_tokens"]
    store.complete = original_complete

    future = datetime.now(timezone.utc) + timedelta(seconds=service.deps.settings.request_stale_seconds + 5)
    assert service.recover_once(future) == 1
    assert len(provider.calls) == 2

    rec = store.get(req.request_id)
    assert rec.status == "Completed"
    total = rec.usage_total
    # FakeProvider usage is deterministic for the same payload: two identical calls.
    assert total["provider_units"] == 2 * first["provider_units"]
    assert total["input_tokens"] == 2 * first["input_tokens"]
    assert total["output_tokens"] == 2 * first["output_tokens"]
    assert rec.response["usage"] == total
    status, body = service.lookup(req.request_id)
    assert status == 200 and body["usage"]["provider_units"] == total["provider_units"]


def test_recover_once_purges_stale_received_and_leaves_failures(db_url):
    def boom(payload):
        raise ProviderError("down")

    service, provider = _service(db_url, boom)
    store = service.store
    store.insert_received("recv", "Answer", "organization", HASH, _body("recv"))
    store.insert_received("proc", "Answer", "organization", HASH, _body("proc"))
    store.mark_processing("proc")
    future = datetime.now(timezone.utc) + timedelta(seconds=400)
    assert service.recover_once(future) == 0
    assert store.get("recv") is None
    assert store.get("proc").status == "Processing"
    assert len(provider.calls) == 1  # failed once, not re-claimed in the same pass


def _slow(payload):
    time.sleep(0.3)
    return _cite(payload)


def _race(submit_a, submit_b):
    results = []
    barrier = threading.Barrier(2)

    def run(fn):
        barrier.wait()
        results.append(fn())

    threads = [threading.Thread(target=run, args=(f,)) for f in (submit_a, submit_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    return results


def test_concurrent_duplicate_posts_call_provider_once(db_url):
    service, provider = _service(db_url, _slow)
    req = AdapterRequest.model_validate(_body())
    results = _race(lambda: service.submit("organization/answer", req),
                    lambda: service.submit("organization/answer", req))
    assert len(provider.calls) == 1
    codes = sorted((s, b.get("code")) for s, b in results)
    assert codes[0] == (200, None)
    assert codes[1] in ((200, None), (409, "AI_REQUEST_IN_PROGRESS"))


def test_in_process_duplicate_does_not_wait_and_gets_409(db_url):
    in_provider = threading.Event()
    release = threading.Event()

    def gated(payload):
        in_provider.set()
        assert release.wait(5)
        return _cite(payload)

    service, provider = _service(db_url, gated)
    req = AdapterRequest.model_validate(_body())
    first = []
    t = threading.Thread(target=lambda: first.append(service.submit("organization/answer", req)))
    t.start()
    try:
        assert in_provider.wait(5)
        started = time.perf_counter()
        status, body = service.submit("organization/answer", req)
        assert time.perf_counter() - started < 1  # non-blocking
        assert (status, body["code"]) == (409, "AI_REQUEST_IN_PROGRESS")
    finally:
        release.set()
        t.join(5)
    assert first[0][0] == 200
    assert len(provider.calls) == 1
    assert service.submit("organization/answer", req) == (200, first[0][1])  # replay after completion


def test_concurrent_posts_across_processes_rely_on_primary_key(db_url):
    # Two services (separate in-process locks) over one database simulate two workers.
    service_a, provider_a = _service(db_url, _slow)
    service_b, provider_b = _service(db_url, _slow, store=make_store(db_url))
    req = AdapterRequest.model_validate(_body())
    results = _race(lambda: service_a.submit("organization/answer", req),
                    lambda: service_b.submit("organization/answer", req))
    assert len(provider_a.calls) + len(provider_b.calls) == 1
    codes = sorted((s, b.get("code")) for s, b in results)
    assert codes[0][0] == 200
    assert codes[1] in ((200, None), (409, "AI_REQUEST_IN_PROGRESS"))


def test_complete_by_other_worker_returns_stored_response(db_url):
    service, _ = _service(db_url)
    req = AdapterRequest.model_validate(_body())
    store = service.store
    original_complete = store.complete
    stored = {}

    def racing_complete(request_id, response, usage_total):
        # Another worker (e.g. recovery) completes first with its own response.
        other = dict(response, recommendation="kết quả của worker khác")
        stored["other"] = other
        assert original_complete(request_id, other, usage_total) is True
        return original_complete(request_id, response, usage_total)

    store.complete = racing_complete
    status, body = service.submit("organization/answer", req)
    assert status == 200
    assert body["recommendation"] == "kết quả của worker khác"
    assert store.get(req.request_id).response == stored["other"]


def test_recovery_loop_ticks_and_stops():
    from app.requests.recovery import RecoveryLoop

    ticked = threading.Event()

    class Stub(RequestService):
        def __init__(self):
            pass

        def recover_once(self, now):
            assert now.tzinfo is not None
            ticked.set()
            return 0

    loop = RecoveryLoop(Stub(), 0.05)
    loop.start()
    assert ticked.wait(2)
    loop.stop()
    assert loop._thread is None

    failing = RecoveryLoop(lambda: (_ for _ in ()).throw(RuntimeError("no provider")), 0.05)
    assert failing.tick() == 0  # unbuildable service is skipped, not fatal


def _stale_row(service, rid, body, attempts):
    store = service.store
    store.insert_received(rid, body["operation"], body["audience"], body["input_hash"], body)
    store.mark_processing(rid)
    with store._engine.begin() as conn:
        conn.execute(update(store._t).where(store._t.c.request_id == rid).values(attempts=attempts))


_UNAVAILABLE_SOURCE = [{"kind": "KnowledgeSource", "document_id": "doc-x", "document_version": "v1"}]


def _future(service):
    return datetime.now(timezone.utc) + timedelta(seconds=service.deps.settings.request_stale_seconds + 5)


def test_recovery_past_cap_completes_insufficient_evidence(db_url):
    service, provider = _service(db_url)
    _stale_row(service, "capped", _body("capped"), attempts=3)  # claim -> 4 > cap 3
    assert service.recover_once(_future(service)) == 1
    assert provider.calls == []  # not re-run past the cap
    status, body = service.lookup("capped")
    assert status == 200
    assert body["status"] == "InsufficientEvidence" and body["confidence"] == "low"
    assert body["citations"] == [] and body["response_type"] == "KnowledgeAnswer"
    assert "AI_RECOVERY_ATTEMPTS_EXHAUSTED" in body["limitations"][0]
    assert body["usage"] == {"provider_units": 0, "input_tokens": 0, "output_tokens": 0, "model_version": "none"}
    assert service.store.get("capped").status == "Completed"


def test_recovery_refusal_on_last_attempt_completes_terminal(db_url):
    service, provider = _service(db_url)
    _stale_row(service, "last", _body("last", sources=_UNAVAILABLE_SOURCE), attempts=2)  # claim -> 3 == cap
    assert service.recover_once(_future(service)) == 1
    status, body = service.lookup("last")
    assert status == 200 and body["status"] == "InsufficientEvidence"
    assert "AI_SOURCE_UNAVAILABLE" in body["limitations"][0]


def test_recovery_refusal_before_cap_leaves_processing(db_url):
    service, provider = _service(db_url)
    _stale_row(service, "early", _body("early", sources=_UNAVAILABLE_SOURCE), attempts=1)  # claim -> 2 < cap
    assert service.recover_once(_future(service)) == 0
    rec = service.store.get("early")
    assert rec.status == "Processing" and rec.attempts == 2
    assert service.lookup("early")[0] == 202
