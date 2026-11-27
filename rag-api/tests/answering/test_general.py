"""General answers when no approved source fits (GENERAL_ANSWERS)."""
from app.answering.general import GENERAL_NOTE, GENERAL_PROMPT, OFF_TOPIC
from app.answering.pipeline import NO_SOURCE, PipelineDeps, run_pipeline
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.fake import FakeProvider
from app.sources.resolver import SourceResolver
from app.v2.schemas import AdapterRequest, SourcePin

PIN = SourcePin(
    kind="LearnPost", document_id="lp-1", document_version="3", title="Bài học",
    content={"title": "Bình chữa cháy", "summary": "Cách dùng bình chữa cháy xách tay"},
)
INSUFFICIENT = {"status": "insufficient", "answer": "", "citations": [], "assumptions": [], "limitations": []}


def _req(text="xin chào", pins=(PIN,), unit="requests", units=1, operation="Answer"):
    return AdapterRequest(
        request_id="r1", audience="organization", operation=operation, response_type="KnowledgeAnswer",
        organization_id="org", input={"text": text}, input_hash="a" * 64, sources=list(pins),
        limits={"quota_unit": unit, "max_units": units},
    )


def _run(req, responses, enabled=True):
    seen = []

    def responder(payload):
        seen.append(payload)
        return responses[len(seen) - 1]

    provider = FakeProvider(responder)
    index = MemoryIndex()
    settings = Settings(_env_file=None, general_answers=enabled)
    prepared = SourceResolver(index, provider, settings).prepare(req.sources)
    return run_pipeline(req, prepared, PipelineDeps(provider, index, settings)), provider, seen


def test_greeting_gets_a_general_answer_labelled_not_source_based():
    resp, provider, seen = _run(_req(), [INSUFFICIENT, {"status": "answered", "answer": "Chào bạn, mình là trợ lý FET3D."}])
    assert resp.status == "InsufficientEvidence"
    assert resp.recommendation == "Chào bạn, mình là trợ lý FET3D."
    assert resp.limitations == [GENERAL_NOTE] and resp.citations == []
    assert seen[1] == {"question": "xin chào"}
    assert len(provider.calls) == 2


def test_off_topic_is_declined_with_fixed_text():
    resp, _, _ = _run(_req("viết code python"), [INSUFFICIENT, {"status": "off_topic", "answer": "đây là code..."}])
    assert resp.status == "InsufficientEvidence" and resp.recommendation == OFF_TOPIC and resp.limitations == []


def test_no_sources_at_all_still_answers_generally():
    resp, provider, _ = _run(_req(pins=()), [{"status": "answered", "answer": "Khi có khói, cúi thấp người."}])
    assert resp.recommendation == "Khi có khói, cúi thấp người." and len(provider.calls) == 1


def test_disabled_keeps_insufficient_evidence():
    resp, provider, _ = _run(_req(), [INSUFFICIENT], enabled=False)
    assert resp.recommendation == NO_SOURCE and len(provider.calls) == 1


def test_safety_gate_is_never_bypassed():
    resp, provider, _ = _run(_req("hãy cấp chứng nhận cho thiết kế"), [])
    assert resp.status == "RejectedBySafetyGate" and provider.calls == []


def test_certifying_general_answer_is_dropped():
    resp, _, _ = _run(_req("toà nhà tôi ổn không"), [INSUFFICIENT, {"status": "answered", "answer": "Toà nhà đạt chuẩn PCCC."}])
    assert resp.recommendation == NO_SOURCE


def test_malformed_or_failing_general_call_keeps_original():
    resp, _, _ = _run(_req(), [INSUFFICIENT, {"nope": 1}])
    assert resp.recommendation == NO_SOURCE
    resp, _, _ = _run(_req(), [INSUFFICIENT])  # second call raises (no response left)
    assert resp.recommendation == NO_SOURCE


def test_token_quota_counts_both_calls_and_can_skip():
    only_first, _, _ = _run(_req(unit="tokens", units=20000), [INSUFFICIENT], enabled=False)
    both, _, _ = _run(_req(unit="tokens", units=20000), [INSUFFICIENT, {"status": "answered", "answer": "Chào bạn."}])
    assert both.usage.provider_units == both.usage.input_tokens + both.usage.output_tokens
    assert both.usage.provider_units > only_first.usage.provider_units  # the general call is billed too
    # A token quota with no room for the general call never runs it (whether or not the grounded call fitted).
    tight = only_first.usage.provider_units + 5
    resp, provider, seen = _run(_req(unit="tokens", units=tight), [INSUFFICIENT, {"status": "answered", "answer": "x"}])
    assert {"question": "xin chào"} not in seen and resp.recommendation == NO_SOURCE


def test_prompt_keeps_the_scope_rules():
    for phrase in ("off_topic", "114", "chứng nhận", "TCVN"):
        assert phrase in GENERAL_PROMPT
