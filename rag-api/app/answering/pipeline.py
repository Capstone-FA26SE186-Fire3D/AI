"""Grounded KnowledgeAnswer pipeline (Organization and Trainee)."""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.answering.prompts import ANSWER_SCHEMA, build_payload, system_prompt
from app.answering.retrieval import retrieve
from app.answering.safety import check_output, check_request
from app.answering.usage import context_budget, estimate_tokens, to_usage
from app.answering.validate import build_citations, clean_list, to_plain_text
from app.core.config import Settings
from app.index.base import KnowledgeIndex
from app.llm.base import LlmUsage, Provider
from app.sources.resolver import PreparedSources
from app.v2.schemas import AdapterRequest, AdapterResponse

_REQUIRED = ("status", "answer", "citations", "assumptions", "limitations")
NO_SOURCE = "Không có nguồn đã duyệt phù hợp để trả lời câu hỏi này."
INVALID_OUTPUT = "Kết quả AI không hợp lệ."


@dataclass
class PipelineDeps:
    provider: Provider
    index: KnowledgeIndex
    settings: Settings


def _terminal(req, status, recommendation, limits_text, llm: LlmUsage | None, assumptions=None) -> AdapterResponse:
    return AdapterResponse(
        request_id=req.request_id, response_type=req.response_type, status=status,
        recommendation=recommendation, scenario_draft=None, bim_anchors=[], citations=[], rule_results=[],
        confidence="low", assumptions=assumptions or [], limitations=limits_text,
        usage=to_usage(llm, req.limits),
    )


def run_pipeline(req: AdapterRequest, prepared: PreparedSources, deps: PipelineDeps) -> AdapterResponse:
    # Raises AI_QUOTA_UNIT_UNSUPPORTED before any provider call.
    budget = context_budget(req.limits, deps.settings.max_output_tokens)
    if req.operation == "ScenarioDraft":
        from app.answering.scenario import run_scenario_draft

        return run_scenario_draft(req, prepared, deps)

    limitations = list(prepared.limitations)
    blocked = check_request(req.input.text)
    if blocked:
        return _terminal(req, "RejectedBySafetyGate", blocked, limitations, None)

    chunks = retrieve(req.input.text, prepared, deps.index, deps.provider)
    if not chunks:
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, limitations, None)
    if budget is None:
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, limitations + ["Hạn mức không đủ để xử lý."], None)

    context = req.context or {}
    kind = context.get("kind") if isinstance(context.get("kind"), str) else None
    system = system_prompt(req.audience, req.operation, kind)
    titles = {doc_id: pin.title for doc_id, pin in prepared.pins.items() if pin.title}
    extra = {"context": req.context} if req.context else None
    chunks = sorted(chunks, key=lambda sc: sc.score, reverse=True)

    def payload_for(selected):
        return build_payload(req.input.text, selected, extra, titles)

    while chunks and estimate_tokens(system + json.dumps(payload_for(chunks), ensure_ascii=False)) > budget:
        chunks = chunks[:-1]
    if not chunks:
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, limitations + ["Hạn mức không đủ để xử lý."], None)

    payload = payload_for(chunks)
    max_out = deps.settings.max_output_tokens
    if req.limits.quota_unit == "tokens":
        est_in = estimate_tokens(system + json.dumps(payload, ensure_ascii=False))
        max_out = min(max_out, req.limits.max_units - est_in)
        if max_out < 1:
            return _terminal(req, "InsufficientEvidence", NO_SOURCE, limitations + ["Hạn mức không đủ để xử lý."], None)

    raw, llm = deps.provider.generate(system, payload, ANSWER_SCHEMA, max_out)

    if (
        not isinstance(raw, dict)
        or any(k not in raw for k in _REQUIRED)
        or raw["status"] not in ("answered", "insufficient")
        or not isinstance(raw["answer"], str)
    ):
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, limitations + [INVALID_OUTPUT], llm)

    assumptions = clean_list(raw["assumptions"]) if isinstance(raw["assumptions"], list) else []
    model_limits = clean_list(raw["limitations"]) if isinstance(raw["limitations"], list) else []
    all_limits = (limitations + model_limits)[:20]
    citations = build_citations(raw["citations"], {sc.chunk.chunk_id: sc for sc in chunks})
    if raw["status"] == "insufficient" or not citations:
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, all_limits, llm, assumptions)

    answer = to_plain_text(raw["answer"], 8000)
    if not answer:
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, all_limits, llm, assumptions)
    blocked_out = check_output(answer)
    if blocked_out:
        return _terminal(req, "RejectedBySafetyGate", blocked_out, all_limits, llm)

    if len(citations) >= 2 and not all_limits:
        confidence = "high"
    else:
        confidence = "medium"
    return AdapterResponse(
        request_id=req.request_id, response_type=req.response_type, status="Answered",
        recommendation=answer, scenario_draft=None, bim_anchors=[], citations=citations, rule_results=[],
        confidence=confidence, assumptions=assumptions, limitations=all_limits, usage=to_usage(llm, req.limits),
    )
