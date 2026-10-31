import math
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.llm import gemini_provider, openai_provider
from app.llm.base import LlmUsage, ProviderError
from app.llm.factory import get_provider
from app.llm.fake import FakeProvider


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_fake_embeddings_similar_for_shared_words():
    q, a, b = FakeProvider().embed(["lối thoát hiểm", "thoát hiểm", "bình chữa cháy"])
    assert cos(q, a) > cos(q, b)
    assert math.isclose(cos(q, q), 1.0)
    assert FakeProvider().embed(["lối thoát hiểm"])[0] == q


def test_fake_generate_records_calls_and_usage():
    fake = FakeProvider()
    result, usage = fake.generate("sys", {"q": "x"}, {}, 100)
    assert result["status"] == "insufficient"
    assert fake.calls == [{"q": "x"}]
    assert usage.model_version == "fake-1" and usage.input_tokens > 0 and usage.output_tokens > 0
    assert fake.embedding_model == "fake-embed-64"


def test_fake_responder_list_and_callable():
    fake = FakeProvider([{"a": 1}])
    assert fake.generate("s", {}, {}, 1)[0] == {"a": 1}
    with pytest.raises(ProviderError):
        fake.generate("s", {}, {}, 1)
    assert FakeProvider(lambda p: {"echo": p["k"]}).generate("s", {"k": 2}, {}, 1)[0] == {"echo": 2}


def test_openai_provider_maps_usage(monkeypatch):
    seen = {}

    class StubOpenAI:
        def __init__(self, **kw):
            seen.update(kw)
            self.responses = SimpleNamespace(create=self._create)

        def _create(self, **kw):
            seen["create"] = kw
            return SimpleNamespace(output_text='{"a":1}', usage=SimpleNamespace(input_tokens=10, output_tokens=5), model="gpt-x")

    monkeypatch.setattr(openai_provider, "OpenAI", StubOpenAI)
    p = openai_provider.OpenAIProvider("k", "m", "e", 45)
    assert p.generate("sys", {"a": "é"}, {"type": "object"}, 50) == ({"a": 1}, LlmUsage(10, 5, "gpt-x"))
    assert seen["max_retries"] == 0 and seen["create"]["store"] is False


def test_openai_provider_invalid_json_raises_provider_error(monkeypatch):
    class StubOpenAI:
        def __init__(self, **kw):
            self.responses = SimpleNamespace(create=lambda **k: SimpleNamespace(output_text="nope", usage=None, model="m"))

    monkeypatch.setattr(openai_provider, "OpenAI", StubOpenAI)
    with pytest.raises(ProviderError):
        openai_provider.OpenAIProvider("k", "m", "e", 1).generate("s", {}, {}, 1)


def test_openai_sdk_error_is_provider_error(monkeypatch):
    def boom(**k):
        raise TimeoutError("secret-key")

    class StubOpenAI:
        def __init__(self, **kw):
            self.responses = SimpleNamespace(create=boom)

    monkeypatch.setattr(openai_provider, "OpenAI", StubOpenAI)
    with pytest.raises(ProviderError) as e:
        openai_provider.OpenAIProvider("k", "m", "e", 1).generate("s", {}, {}, 1)
    assert "secret-key" not in str(e.value)


def test_gemini_provider_maps_usage(monkeypatch):
    seen = {}

    class Models:
        def generate_content(self, **kw):
            seen.update(kw)
            return SimpleNamespace(text='{"a":1}', usage_metadata=SimpleNamespace(prompt_token_count=7, candidates_token_count=3), model_version=None)

        def embed_content(self, **kw):
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])

    class StubClient:
        def __init__(self, **kw):
            self.models = Models()

    monkeypatch.setattr(gemini_provider.genai, "Client", StubClient)
    p = gemini_provider.GeminiProvider("k", "gem", "emb", 45)
    assert p.generate("sys", {"a": 1}, {"type": "object"}, 50) == ({"a": 1}, LlmUsage(7, 3, "gem"))
    assert seen["config"].response_json_schema == {"type": "object"}
    assert p.embed(["x"]) == [[0.1, 0.2]]


def test_gemini_invalid_json_raises_provider_error(monkeypatch):
    class StubClient:
        def __init__(self, **kw):
            self.models = SimpleNamespace(generate_content=lambda **k: SimpleNamespace(text="x", usage_metadata=None, model_version="v"))

    monkeypatch.setattr(gemini_provider.genai, "Client", StubClient)
    with pytest.raises(ProviderError):
        gemini_provider.GeminiProvider("k", "g", "e", 1).generate("s", {}, {}, 1)


def test_factory_requires_key():
    with pytest.raises(ProviderError, match="not configured"):
        get_provider(Settings(llm_provider="openai", openai_api_key="", _env_file=None))
    with pytest.raises(ProviderError, match="not configured"):
        get_provider(Settings(llm_provider="gemini", gemini_api_key="", _env_file=None))
    assert get_provider(Settings(llm_provider="fake", _env_file=None)).name == "fake"
    assert get_provider(Settings(llm_provider="openai", openai_api_key="k", _env_file=None)).name == "openai"


def test_gemini_embed_batches_of_100_in_order(monkeypatch):
    calls = []

    class Models:
        def embed_content(self, **kw):
            calls.append(list(kw["contents"]))
            return SimpleNamespace(embeddings=[SimpleNamespace(values=[float(t)]) for t in kw["contents"]])

    class StubClient:
        def __init__(self, **kw):
            self.models = Models()

    monkeypatch.setattr(gemini_provider.genai, "Client", StubClient)
    texts = [str(i) for i in range(250)]
    out = gemini_provider.GeminiProvider("k", "g", "e", 1).embed(texts)
    assert [len(c) for c in calls] == [100, 100, 50]
    assert out == [[float(i)] for i in range(250)]


def test_openai_embed_batches_of_512_in_order(monkeypatch):
    calls = []

    def create(**kw):
        calls.append(list(kw["input"]))
        return SimpleNamespace(data=[SimpleNamespace(embedding=[float(t)]) for t in kw["input"]])

    class StubOpenAI:
        def __init__(self, **kw):
            self.embeddings = SimpleNamespace(create=create)

    monkeypatch.setattr(openai_provider, "OpenAI", StubOpenAI)
    texts = [str(i) for i in range(1100)]
    out = openai_provider.OpenAIProvider("k", "m", "e", 1).embed(texts)
    assert [len(c) for c in calls] == [512, 512, 76]
    assert out == [[float(i)] for i in range(1100)]


def _gemini_stub(monkeypatch, meta):
    seen = {}

    class Models:
        def generate_content(self, **kw):
            seen.update(kw)
            return SimpleNamespace(text='{"a":1}', usage_metadata=meta, model_version="m")

    class StubClient:
        def __init__(self, **kw):
            seen["client"] = kw
            self.models = Models()

    monkeypatch.setattr(gemini_provider.genai, "Client", StubClient)
    return seen


def test_gemini_25_disables_thinking_and_counts_thoughts(monkeypatch):
    meta = SimpleNamespace(prompt_token_count=7, candidates_token_count=3, thoughts_token_count=40)
    seen = _gemini_stub(monkeypatch, meta)
    p = gemini_provider.GeminiProvider("k", "gemini-2.5-flash", "e", 45)
    _, usage = p.generate("s", {}, {"type": "object"}, 50)
    assert seen["config"].thinking_config.thinking_budget == 0
    assert usage == LlmUsage(7, 43, "m")
    assert seen["client"]["http_options"].retry_options.attempts == 1


def test_gemini_other_models_keep_default_thinking(monkeypatch):
    meta = SimpleNamespace(prompt_token_count=7, candidates_token_count=3)
    seen = _gemini_stub(monkeypatch, meta)
    _, usage = gemini_provider.GeminiProvider("k", "gemini-2.0-flash", "e", 45).generate("s", {}, {}, 50)
    assert seen["config"].thinking_config is None
    assert usage == LlmUsage(7, 3, "m")


def test_gemini_retry_delay_parsed_from_429_details():
    from app.llm.gemini_provider import retry_delay

    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure"},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"},
    ]}}
    assert retry_delay(body) == 37.0
    assert retry_delay({"error": {"details": [{"retryDelay": "1.5s"}]}}) == 1.5
    assert retry_delay({"error": {"message": "quota"}}) is None
    assert retry_delay(None) is None
