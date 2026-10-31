import hashlib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.answering.pipeline import PipelineDeps
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.base import ProviderError
from app.llm.fake import FakeProvider
from app.main import create_app
from app.requests.service import RequestService
from app.requests.store import make_store
from app.sources.resolver import SourceResolver

HASH = "c" * 64
ANSWER = "/v2/organization/answer"


def _body(rid="req-1", input_hash=HASH, text="bình chữa cháy dùng thế nào", **over):
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


class Env:
    def __init__(self, tmp_path, responder=_cite, api_key="", http=None):
        self.settings = Settings(
            llm_provider="fake", database_url=f"sqlite:///{tmp_path / 'router.db'}",
            recovery_interval_seconds=0, ai_api_key=api_key,
        )
        self.provider = FakeProvider(responder)
        index = MemoryIndex()
        self.store = make_store(self.settings.database_url)
        self.service = RequestService(
            self.store, SourceResolver(index, self.provider, self.settings, http=http),
            PipelineDeps(self.provider, index, self.settings),
        )
        self.client = TestClient(create_app(self.settings, service=self.service))

    def post(self, body, path=ANSWER, rid=None, headers=None):
        h = {"X-Request-Id": rid if rid is not None else body["request_id"]}
        h.update(headers or {})
        return self.client.post(path, json=body, headers=h)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_post_answer_then_lookup_same_body(env):
    resp = env.post(_body())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["request_id"] == "req-1" and data["status"] == "Answered"
    assert data["citations"][0]["document_id"] == "lp-1"
    looked = env.client.get("/v2/requests/req-1")
    assert looked.status_code == 200
    assert looked.json() == data


def test_replay_same_input_returns_stored_without_provider_call(env):
    first = env.post(_body())
    second = env.post(_body())
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(env.provider.calls) == 1


def test_same_id_different_hash_conflict_409(env):
    env.post(_body())
    resp = env.post(_body(input_hash="d" * 64))
    assert resp.status_code == 409
    assert resp.json()["code"] == "AI_REQUEST_CONFLICT"
    assert set(resp.json()) == {"code", "message"}


def test_in_progress_post_409(env):
    env.store.insert_received("req-1", "Answer", "organization", HASH, _body())
    resp = env.post(_body())
    assert resp.status_code == 409 and resp.json()["code"] == "AI_REQUEST_IN_PROGRESS"
    assert env.provider.calls == []


def test_lookup_unknown_404(env):
    resp = env.client.get("/v2/requests/nope")
    assert resp.status_code == 404
    assert resp.json()["code"] == "AI_REQUEST_NOT_FOUND"


def test_lookup_processing_202(env):
    env.store.insert_received("req-9", "Answer", "organization", HASH, _body("req-9"))
    assert env.client.get("/v2/requests/req-9").status_code == 202
    env.store.mark_processing("req-9")
    resp = env.client.get("/v2/requests/req-9")
    assert resp.status_code == 202
    assert resp.json() == {"request_id": "req-9", "status": "Processing"}


def test_hash_mismatch_refusal_deletes_row(tmp_path):
    url = "https://files.example/a.txt"
    http = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=b"noi dung khac", headers={"content-type": "text/plain"})))
    env = Env(tmp_path, http=http)
    body = _body(sources=[{
        "kind": "KnowledgeSource", "document_id": "doc-1", "document_version": "v1",
        "content_hash": hashlib.sha256(b"noi dung goc").hexdigest(), "source_uri": url,
    }])
    resp = env.post(body)
    assert resp.status_code == 422
    assert resp.json()["code"] == "AI_SOURCE_HASH_MISMATCH"
    assert env.client.get("/v2/requests/req-1").status_code == 404
    assert env.provider.calls == []


def test_provider_crash_after_processing_returns_500_and_lookup_202(tmp_path):
    def boom(payload):
        raise ProviderError("timeout")

    env = Env(tmp_path, boom)
    resp = env.post(_body())
    assert resp.status_code == 500
    assert resp.json()["code"] == "AI_OUTCOME_UNKNOWN"
    assert env.client.get("/v2/requests/req-1").status_code == 202
    assert env.store.get("req-1").status == "Processing"


def test_infra_error_before_processing_503_and_row_deleted(env, monkeypatch):
    def broken(pins):
        raise RuntimeError("index down")

    monkeypatch.setattr(env.service.resolver, "prepare", broken)
    resp = env.post(_body())
    assert resp.status_code == 503 and resp.json()["code"] == "AI_TEMPORARILY_UNAVAILABLE"
    assert env.store.get("req-1") is None


def test_bearer_required_when_configured(tmp_path):
    env = Env(tmp_path, api_key="s3cret")
    missing = env.post(_body())
    assert missing.status_code == 401 and missing.json()["code"] == "AI_UNAUTHORIZED"
    wrong = env.post(_body(), headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    assert env.client.get("/v2/requests/x").status_code == 401
    ok = env.post(_body(), headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200
    assert env.client.get("/v2/requests/req-1", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_route_mismatch_trainee_with_org_id(env):
    body = _body(audience="trainee", operation="TraineeAnswer", organization_id="org-1")
    resp = env.post(body, path="/v2/trainee/answer")
    assert resp.status_code == 422 and resp.json()["code"] == "AI_ROUTE_MISMATCH"
    assert env.store.get("req-1") is None
    wrong_route = env.post(_body(), path="/v2/trainee/answer")
    assert wrong_route.status_code == 422 and wrong_route.json()["code"] == "AI_ROUTE_MISMATCH"


def test_trainee_answer_ok(env):
    resp = env.post(_body(audience="trainee", operation="TraineeAnswer", organization_id=None),
                    path="/v2/trainee/answer")
    assert resp.status_code == 200, resp.text


def test_scenario_draft_without_bim_refused_before_insert(env):
    body = _body(operation="ScenarioDraft", response_type="ScenarioDraft")
    resp = env.post(body, path="/v2/organization/scenario-draft")
    assert resp.status_code == 422 and resp.json()["code"] == "AI_REVISION_NOT_PINNED"
    assert env.store.get("req-1") is None


def test_unsupported_quota_unit_refused_before_insert(env):
    resp = env.post(_body(limits={"quota_unit": "credits", "max_units": 5}))
    assert resp.status_code == 422 and resp.json()["code"] == "AI_QUOTA_UNIT_UNSUPPORTED"
    assert env.store.get("req-1") is None


def test_x_request_id_mismatch_422(env):
    resp = env.post(_body(), rid="other")
    assert resp.status_code == 422 and resp.json()["code"] == "AI_REQUEST_ID_MISMATCH"
    missing = env.client.post(ANSWER, json=_body())
    assert missing.status_code == 422 and missing.json()["code"] == "AI_REQUEST_ID_MISMATCH"
    assert env.provider.calls == []


def test_invalid_body_422(env):
    resp = env.client.post(ANSWER, content=b"{not json", headers={"X-Request-Id": "req-1",
                                                                  "Content-Type": "application/json"})
    assert resp.status_code == 422 and resp.json()["code"] == "AI_REQUEST_INVALID"
    resp = env.post(_body(input_hash="short"))
    assert resp.status_code == 422 and resp.json()["code"] == "AI_REQUEST_INVALID"
    assert set(resp.json()) == {"code", "message"}


def test_ready_with_injected_service(env):
    resp = env.client.get("/ready")
    assert resp.status_code == 200 and resp.json() == {"status": "ready"}


def test_ready_503_when_provider_unconfigured(tmp_path):
    settings = Settings(llm_provider="openai", openai_api_key="", database_url=f"sqlite:///{tmp_path / 'r.db'}",
                        recovery_interval_seconds=0, ai_api_key="")
    client = TestClient(create_app(settings))
    assert client.get("/ready").status_code == 503
    resp = client.post(ANSWER, json=_body(), headers={"X-Request-Id": "req-1"})
    assert resp.status_code == 503 and resp.json()["code"] == "AI_TEMPORARILY_UNAVAILABLE"


def test_ready_default_service_fake_provider(tmp_path):
    settings = Settings(llm_provider="fake", database_url=f"sqlite:///{tmp_path / 'r.db'}",
                        recovery_interval_seconds=0, ai_api_key="")
    client = TestClient(create_app(settings))
    assert client.get("/ready").status_code == 200


def test_production_requires_knowledge_database():
    with pytest.raises(RuntimeError):
        create_app(Settings(environment="production", ai_api_key="k", knowledge_database_url=""))


def _knowledge(body, doc="doc-1"):
    return {"kind": "KnowledgeSource", "document_id": doc, "document_version": "v1", "title": "QCVN",
            "content_hash": hashlib.sha256(body).hexdigest(), "source_uri": "https://files.example/a.txt"}


def _background_env(tmp_path, body):
    from app.sources.warmer import SourceWarmer

    http = httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=body, headers={"content-type": "text/plain"})))
    env = Env(tmp_path, http=http)
    resolver = env.service.resolver
    warmer = SourceWarmer(resolver.index, env.provider, env.settings, http)
    warmer.start = lambda: None  # drained by hand below
    resolver.warmer = warmer
    return env, warmer


def _drain(warmer):
    while warmer._queue:
        key, pin = next(iter(warmer._queue.items()))
        warmer.run_one(key, pin)


def test_unprepared_source_returns_503_preparing_then_answers(tmp_path):
    body = "Bình chữa cháy xách tay dùng theo hướng dẫn.".encode()
    env, warmer = _background_env(tmp_path, body)
    req = _body(sources=[_knowledge(body)])
    resp = env.post(req)
    assert resp.status_code == 503
    assert resp.json()["code"] == "AI_SOURCES_PREPARING"
    assert env.client.get("/v2/requests/req-1").status_code == 404
    assert env.provider.calls == []
    _drain(warmer)
    resp = env.post(req)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "Answered"


def test_warm_endpoint_queues_and_reports(tmp_path):
    body = b"Loi thoat nan phai thong thoang."
    env, warmer = _background_env(tmp_path, body)
    sources = [_knowledge(body), {"kind": "LearnPost", "document_id": "lp", "document_version": "1"}]
    resp = env.client.post("/v2/sources/warm", json={"sources": sources})
    assert resp.status_code == 202
    assert resp.json()["sources"] == [
        {"document_id": "doc-1", "state": "queued"},
        {"document_id": "lp", "state": "failed", "code": "AI_SOURCE_UNAVAILABLE"},
    ]
    _drain(warmer)
    resp = env.client.post("/v2/sources/warm", json={"sources": sources[:1]})
    assert resp.json()["sources"] == [{"document_id": "doc-1", "state": "ready"}]
    assert env.client.post("/v2/sources/warm", json={"sources": []}).status_code == 422


def test_warm_endpoint_requires_key(tmp_path):
    env = Env(tmp_path, api_key="secret")
    resp = env.client.post("/v2/sources/warm", json={"sources": [_knowledge(b"x")]})
    assert resp.status_code == 401
