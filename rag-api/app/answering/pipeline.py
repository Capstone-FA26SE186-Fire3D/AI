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


@dataclass
class Grounded:
    raw: object
    llm: LlmUsage
    chunks: list
    limitations: list[str]


@dataclass
class Parsed:
    raw: dict
    llm: LlmUsage
    assumptions: list[str]
    limitations: list[str]
    citations: list


def ground(
    req: AdapterRequest, prepared: PreparedSources, deps: PipelineDeps, budget: int | None,
    schema: dict, extra: dict | None = None,
) -> Grounded | AdapterResponse:
    """Safety check, scoped retrieval, budget trim and the provider call; a terminal response on any early exit."""
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

    raw, llm = deps.provider.generate(system, payload, schema, max_out)
    return Grounded(raw, llm, chunks, limitations)


def parse_grounded(req: AdapterRequest, g: Grounded, required: tuple[str, ...] = _REQUIRED) -> Parsed | AdapterResponse:
    """Validate the common answer fields and citations; terminal InsufficientEvidence when the model gave no grounded answer."""
    raw = g.raw
    if (
        not isinstance(raw, dict)
        or any(k not in raw for k in required)
        or raw["status"] not in ("answered", "insufficient")
        or not isinstance(raw["answer"], str)
    ):
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, g.limitations + [INVALID_OUTPUT], g.llm)

    assumptions = clean_list(raw["assumptions"]) if isinstance(raw["assumptions"], list) else []
    model_limits = clean_list(raw["limitations"]) if isinstance(raw["limitations"], list) else []
    all_limits = (g.limitations + model_limits)[:20]
    citations = build_citations(raw["citations"], {sc.chunk.chunk_id: sc for sc in g.chunks})
    if raw["status"] == "insufficient" or not citations:
        return _terminal(req, "InsufficientEvidence", NO_SOURCE, all_limits, g.llm, assumptions)
    return Parsed(raw, g.llm, assumptions, all_limits, citations)


def vet_text(req: AdapterRequest, text: object, p: Parsed) -> tuple[str, AdapterResponse | None]:
    """Plain-text the recommendation and run the output safety check; (text, terminal-or-None)."""
    plain = to_plain_text(text, 8000)
    if not plain:
        return "", _terminal(req, "InsufficientEvidence", NO_SOURCE, p.limitations, p.llm, p.assumptions)
    blocked_out = check_output(plain)
    if blocked_out:
        return "", _terminal(req, "RejectedBySafetyGate", blocked_out, p.limitations, p.llm)
    return plain, None


def run_pipeline(req: AdapterRequest, prepared: PreparedSources, deps: PipelineDeps) -> AdapterResponse:
    # Raises AI_QUOTA_UNIT_UNSUPPORTED before any provider call.
    budget = context_budget(req.limits, deps.settings.max_output_tokens)
    if req.operation == "ScenarioDraft":
        from app.answering.scenario import run_scenario_draft

        return run_scenario_draft(req, prepared, deps, budget)

    extra = {"context": req.context} if req.context else None
    g = ground(req, prepared, deps, budget, ANSWER_SCHEMA, extra)
    if isinstance(g, AdapterResponse):
        return g
    p = parse_grounded(req, g)
    if isinstance(p, AdapterResponse):
        return p
    answer, terminal = vet_text(req, p.raw["answer"], p)
    if terminal:
        return terminal

    confidence = "high" if len(p.citations) >= 2 and not p.limitations else "medium"
    return AdapterResponse(
        request_id=req.request_id, response_type=req.response_type, status="Answered",
        recommendation=answer, scenario_draft=None, bim_anchors=[], citations=p.citations, rule_results=[],
        confidence=confidence, assumptions=p.assumptions, limitations=p.limitations, usage=to_usage(g.llm, req.limits),
    )
