import json
import math

from app.answering.pipeline import PipelineDeps, run_pipeline
from app.answering.prompts import ANSWER_SCHEMA
from app.answering.usage import context_budget, estimate_tokens
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.fake import FakeProvider
from app.sources.resolver import SourceResolver
from app.v2.schemas import AdapterRequest, Limits, SourcePin


def test_estimate_is_conservative_for_vietnamese():
    assert estimate_tokens("a" * 25) == 10 + 300
    assert estimate_tokens("") == 300


def test_context_budget_keeps_15_percent_margin():
    assert context_budget(Limits(quota_unit="tokens", max_units=10000), 1500) == math.floor(8500 * 0.85)
    assert context_budget(Limits(quota_unit="tokens", max_units=1700), 1500) is None


def test_prompt_trimmed_to_margin_budget():
    long = "Lối thoát hiểm phải thông thoáng, có chiếu sáng sự cố và biển chỉ dẫn. " * 30
    pins = [SourcePin(kind="LearnPost", document_id=f"lp-{i}", document_version="1", title=f"Bài {i}",
                      content={"title": "Lối thoát hiểm", "summary": long}) for i in range(8)]
    req = AdapterRequest(
        request_id="r1", audience="organization", operation="Answer", response_type="KnowledgeAnswer",
        organization_id="org", input={"text": "lối thoát hiểm"}, input_hash="a" * 64, sources=pins,
        limits={"quota_unit": "tokens", "max_units": 3000},
    )
    seen = {}
    provider = FakeProvider(lambda p: {"status": "insufficient", "answer": "", "citations": [],
                                       "assumptions": [], "limitations": []})
    orig = provider.generate

    def spy(system, payload, schema, max_output_tokens):
        seen["text"] = system + json.dumps(payload, ensure_ascii=False)
        seen["max_out"] = max_output_tokens
        return orig(system, payload, schema, max_output_tokens)

    provider.generate = spy
    settings = Settings()
    index = MemoryIndex()
    prepared = SourceResolver(index, provider, settings).prepare(req.sources)
    run_pipeline(req, prepared, PipelineDeps(provider, index, settings))
    budget = math.floor((3000 - settings.max_output_tokens) * 0.85)
    assert math.ceil(len(seen["text"]) / 2.5) + 300 <= budget
    assert seen["max_out"] == settings.max_output_tokens
    assert ANSWER_SCHEMA  # schema overhead is covered by the fixed 300-token allowance
