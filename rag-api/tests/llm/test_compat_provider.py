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


@pytest.mark.parametrize("reply", [completion("nope"), completion(None), SimpleNamespace(choices=[], usage=None, model="m")])
def test_bad_replies_are_provider_errors(monkeypatch, reply):
    stub_client(monkeypatch, reply)
    with pytest.raises(ProviderError):
        CompatChatProvider("k", "u", "m", 1).generate("s", {}, {}, 1)


def test_rate_limit_is_rate_limited_and_errors_hide_details(monkeypatch):
    request = httpx.Request("POST", "https://gw.example/v1/chat/completions")

    def limited(**kw):
        raise RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)

    stub_client(monkeypatch, limited)
    with pytest.raises(RateLimited):
        CompatChatProvider("k", "u", "m", 1).generate("s", {}, {}, 1)

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
