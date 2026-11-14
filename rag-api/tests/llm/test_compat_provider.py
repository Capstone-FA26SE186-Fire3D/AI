from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from app.core.config import Settings
from app.llm import compat_provider
from app.llm.base import LlmUsage, ProviderError, RateLimited
from app.llm.compat_provider import CompatChatProvider, SplitProvider, extract_json
from app.llm.factory import get_provider
from app.llm.fake import FakeProvider


def stub_client(monkeypatch, reply):
    seen = {}

    class StubOpenAI:
        def __init__(self, **kw):
            seen["client"] = kw
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        def _create(self, **kw):
            seen["create"] = kw
            return reply(**kw) if callable(reply) else reply

    monkeypatch.setattr(compat_provider, "OpenAI", StubOpenAI)
    return seen


def completion(text, prompt=12, completion_tokens=7, model="gw-model"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion_tokens),
        model=model,
    )


@pytest.mark.parametrize(
    "text",
    ['{"a": 1}', '```json\n{"a": 1}\n```', 'Đây là kết quả:\n{"a": 1}\nXong.', '  {"a": 1}  '],
)
def test_extract_json_tolerates_fences_and_prose(text):
    assert extract_json(text) == {"a": 1}


@pytest.mark.parametrize("text", ["", "không có JSON", "[1, 2]", '{"a": '])
def test_extract_json_rejects_non_objects(text):
    with pytest.raises(ValueError):
        extract_json(text)


def test_generate_puts_schema_in_prompt_and_maps_usage(monkeypatch):
    seen = stub_client(monkeypatch, completion('{"status": "answered"}'))
    p = CompatChatProvider("k", "https://gw.example/v1", "m", 30, "low")
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}

    assert p.generate("Hệ thống", {"q": "é"}, schema, 900) == ({"status": "answered"}, LlmUsage(12, 7, "gw-model"))
    assert seen["client"] == {"api_key": "k", "base_url": "https://gw.example/v1", "timeout": 30, "max_retries": 0}
    sent = seen["create"]
    assert sent["model"] == "m" and sent["max_tokens"] == 900 and sent["reasoning_effort"] == "low"
    assert "response_format" not in sent
    system, user = sent["messages"]
    assert system["content"].startswith("Hệ thống") and '"status"' in system["content"]
    assert user == {"role": "user", "content": '{"q": "é"}'}


def test_no_reasoning_effort_when_blank(monkeypatch):
    seen = stub_client(monkeypatch, completion("{}"))
    CompatChatProvider("k", "u", "m", 1, "").generate("s", {}, {}, 1)
    assert "reasoning_effort" not in seen["create"]


@pytest.mark.parametrize("reply", [completion("nope"), completion(None), completion('{"a": "cut off'),
                                   SimpleNamespace(choices=[], usage=None, model="m")])
def test_unusable_replies_return_empty_object_with_usage(monkeypatch, reply):
    """A billed call whose text is not JSON (often cut at max_tokens) settles as invalid output, not an error."""
    stub_client(monkeypatch, reply)
    data, usage = CompatChatProvider("k", "u", "m", 1).generate("s", {}, {}, 1)
    assert data == {}
    if reply.usage is not None:
        assert usage == LlmUsage(12, 7, "gw-model")


def test_rate_limit_is_rate_limited_and_errors_hide_details(monkeypatch):
    request = httpx.Request("POST", "https://gw.example/v1/chat/completions")

    def limited(**kw):
        raise RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)

    stub_client(monkeypatch, limited)
    waits = []
    with pytest.raises(RateLimited):
        CompatChatProvider("k", "u", "m", 1, sleep=waits.append).generate("s", {}, {}, 1)
    assert waits == [2.0, 5.0], "two retries before giving up"

    def boom(**kw):
        raise TimeoutError("sk-secret")

    stub_client(monkeypatch, boom)
    with pytest.raises(ProviderError) as err:
        CompatChatProvider("k", "u", "m", 1).generate("s", {}, {}, 1)
    assert "sk-secret" not in str(err.value)


def test_split_provider_answers_with_gateway_and_embeds_with_base(monkeypatch):
    stub_client(monkeypatch, completion('{"x": 2}'))
    base = FakeProvider()
    split = SplitProvider(CompatChatProvider("k", "u", "m", 1), base)
    assert split.generate("s", {}, {}, 1)[0] == {"x": 2}
    assert base.calls == []
    assert split.embed(["a"]) == base.embed(["a"])
    assert split.embedding_model == base.embedding_model
    assert split.name == "openai_compat+fake"


def test_factory_builds_split_only_when_chat_provider_set():
    gw = dict(chat_provider="openai_compat", chat_base_url="https://gw.example/v1", chat_api_key="k", chat_model="m")
    assert get_provider(Settings(llm_provider="fake", _env_file=None)).name == "fake"
    split = get_provider(Settings(llm_provider="fake", **gw, _env_file=None))
    assert isinstance(split, SplitProvider) and split.embedding_model == "fake-embed-64"
    assert split.chat.reasoning_effort == "low"
    with pytest.raises(ProviderError, match="not configured"):
        get_provider(Settings(llm_provider="fake", **{**gw, "chat_api_key": ""}, _env_file=None))
    with pytest.raises(ProviderError, match="unknown chat provider"):
        get_provider(Settings(llm_provider="fake", chat_provider="other", _env_file=None))


def test_rate_limit_retries_then_succeeds_and_honours_retry_after(monkeypatch):
    request = httpx.Request("POST", "https://gw.example/v1/chat/completions")
    calls = []

    def flaky(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise RateLimitError("busy", response=httpx.Response(429, request=request, headers={"retry-after": "30"}), body=None)
        return completion('{"ok": true}')

    stub_client(monkeypatch, flaky)
    waits = []
    data, _ = CompatChatProvider("k", "u", "m", 1, sleep=waits.append).generate("s", {}, {}, 1)
    assert data == {"ok": True} and len(calls) == 2
    assert waits == [10.0], "Retry-After honoured, capped at 10 s"


SCHEMA = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["answered", "insufficient"]}, "answer": {"type": "string"}},
    "required": ["status", "answer"],
    "additionalProperties": False,
}


def test_schema_problem_tolerates_extras_but_not_missing_or_wrong_types():
    from app.llm.compat_provider import schema_problem

    assert schema_problem({"status": "answered", "answer": "x", "extra": 1}, SCHEMA) is None
    assert "answer" in schema_problem({"status": "answered"}, SCHEMA)
    assert "status" in schema_problem({"status": "maybe", "answer": "x"}, SCHEMA)
    assert "rỗng" in schema_problem({}, SCHEMA)
    assert schema_problem({}, {}) is None, "no schema, nothing to check"


def test_invalid_reply_is_repaired_once_and_usage_covers_both(monkeypatch):
    replies = [completion('{"status": "answered"}', 10, 4), completion('{"status": "answered", "answer": "Dùng bình CO2."}', 12, 6)]
    seen = stub_client(monkeypatch, lambda **kw: (seen.setdefault("systems", []).append(kw["messages"][0]["content"]), replies.pop(0))[1])
    data, usage = CompatChatProvider("k", "u", "m", 1, sleep=lambda s: None).generate("Hệ thống", {}, SCHEMA, 900)
    assert data == {"status": "answered", "answer": "Dùng bình CO2."}
    assert usage == LlmUsage(22, 10, "gw-model")
    assert "không đúng JSON Schema" not in seen["systems"][0]
    assert "không đúng JSON Schema" in seen["systems"][1] and "answer" in seen["systems"][1]


def test_failed_repair_keeps_the_first_answer_and_its_usage(monkeypatch):
    request = httpx.Request("POST", "https://gw.example/v1/chat/completions")
    calls = []

    def reply(**kw):
        calls.append(1)
        if len(calls) == 1:
            return completion("not json at all", 10, 4)
        raise RateLimitError("busy", response=httpx.Response(429, request=request), body=None)

    stub_client(monkeypatch, reply)
    data, usage = CompatChatProvider("k", "u", "m", 1, sleep=lambda s: None).generate("s", {}, SCHEMA, 900)
    assert data == {} and usage == LlmUsage(10, 4, "gw-model"), "billed first call is still reported"


def test_valid_reply_is_not_called_twice(monkeypatch):
    calls = []
    stub_client(monkeypatch, lambda **kw: (calls.append(1), completion('{"status": "insufficient", "answer": ""}'))[1])
    CompatChatProvider("k", "u", "m", 1).generate("s", {}, SCHEMA, 900)
    assert len(calls) == 1


def test_gateway_with_local_embeddings_needs_no_gemini_key():
    split = get_provider(Settings(llm_provider="gemini", gemini_api_key="", embed_provider="local", chat_provider="openai_compat",
                                  chat_base_url="https://gw.example/v1", chat_api_key="k", chat_model="m", _env_file=None))
    assert split.name == "openai_compat+local"
    with pytest.raises(ProviderError, match="not configured"):
        get_provider(Settings(llm_provider="gemini", gemini_api_key="", chat_provider="openai_compat",
                              chat_base_url="https://gw.example/v1", chat_api_key="k", chat_model="m", _env_file=None))
