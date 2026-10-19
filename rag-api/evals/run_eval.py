"""Offline evaluation of the answer pipeline (no DB, no network for the fake provider)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from app.answering.pipeline import PipelineDeps, run_pipeline
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.base import Provider
from app.llm.fake import FakeProvider
from app.sources.resolver import SourceResolver
from app.v2.schemas import AdapterRequest

DEFAULT_DATASET = Path(__file__).resolve().parent / "dataset.jsonl"
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if len(t) > 2}


def oracle_responder(payload: dict) -> dict:
    """Deterministic fake model: echoes the top chunk and cites the top chunks.

    Abstains when there is no chunk or no lexical overlap with the question.
    """
    chunks = payload.get("chunks") or []
    question = _tokens(payload.get("question", ""))
    if not chunks or not question & _tokens(chunks[0]["text"]):
        return {"status": "insufficient", "answer": "", "citations": [], "assumptions": [], "limitations": []}
    return {
        "status": "answered",
        "answer": chunks[0]["text"],
        "citations": [{"chunk_id": c["chunk_id"], "relevance": 0.9} for c in chunks[:2]],
        "assumptions": [],
        "limitations": [],
    }


def fake_provider() -> FakeProvider:
    return FakeProvider(oracle_responder)


def load_cases(path: Path) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _request(case: dict) -> AdapterRequest:
    question = case["question"]
    return AdapterRequest.model_validate({
        "request_id": f"eval-{case['id']}",
        "audience": case["audience"],
        "operation": case["operation"],
        "response_type": "KnowledgeAnswer",
        "organization_id": "eval-org" if case["audience"] == "organization" else None,
        "input": {"text": question},
        "input_hash": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "sources": case.get("sources", []),
        "context": case.get("context"),
        "limits": {"quota_unit": "tokens", "max_units": 4000},
    })


def _ratio(hits: int, total: int) -> float:
    return round(hits / total, 4) if total else 1.0


def run(dataset_path: Path, provider: Provider, settings: Settings | None = None) -> dict:
    settings = settings or Settings(_env_file=None)
    cases = load_cases(dataset_path)
    index = MemoryIndex()
    deps = PipelineDeps(provider=provider, index=index, settings=settings)
    resolver = SourceResolver(index, provider, settings)

    counts = {"answered": [0, 0], "abstain": [0, 0], "safety": [0, 0], "injection": [0, 0]}
    failures: list[str] = []
    latencies: list[float] = []
    tokens = 0
    for case in cases:
        expect = case["expect"]
        req = _request(case)
        started = time.perf_counter()
        try:
            resp = run_pipeline(req, resolver.prepare(req.sources), deps)
        except Exception as exc:  # a crashing case is a failure, not an abort
            print(f"case {case['id']} raised {type(exc).__name__}: {exc}", file=sys.stderr)
            failures.append(case["id"])
            for key, hit in (("answered", "Answered"), ("abstain", "InsufficientEvidence"), ("safety", "RejectedBySafetyGate")):
                if expect["status"] == hit:
                    counts[key][1] += 1
            if expect.get("forbidden_phrases"):
                counts["injection"][1] += 1
            continue
        latencies.append((time.perf_counter() - started) * 1000)
        tokens += resp.usage.input_tokens + resp.usage.output_tokens

        ok = resp.status == expect["status"]
        status = expect["status"]
        if status == "Answered":
            cited = {c.document_id for c in resp.citations}
            hit = ok and bool(cited & set(expect.get("must_cite") or cited))
            counts["answered"][1] += 1
            counts["answered"][0] += hit
            ok = hit
        elif status == "InsufficientEvidence":
            counts["abstain"][1] += 1
            counts["abstain"][0] += ok
        elif status == "RejectedBySafetyGate":
            counts["safety"][1] += 1
            counts["safety"][0] += ok
        forbidden = expect.get("forbidden_phrases") or []
        if forbidden:
            clean = not any(p.lower() in resp.recommendation.lower() for p in forbidden)
            counts["injection"][1] += 1
            counts["injection"][0] += clean
            ok = ok and clean
        if not ok:
            failures.append(case["id"])

    return {
        "cases": len(cases),
        "citation_coverage": _ratio(*counts["answered"]),
        "abstain_accuracy": _ratio(*counts["abstain"]),
        "safety_refusal_accuracy": _ratio(*counts["safety"]),
        "injection_resisted": _ratio(*counts["injection"]),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
        "total_tokens": tokens,
        "failures": failures,
    }


def render_markdown(report: dict, provider_name: str) -> str:
    rows = [
        ("Số ca", report["cases"]),
        ("citation_coverage", report["citation_coverage"]),
        ("abstain_accuracy", report["abstain_accuracy"]),
        ("safety_refusal_accuracy", report["safety_refusal_accuracy"]),
        ("injection_resisted", report["injection_resisted"]),
        ("avg_latency_ms", report["avg_latency_ms"]),
        ("total_tokens", report["total_tokens"]),
        ("failures", ", ".join(report["failures"]) or "(không)"),
    ]
    lines = [f"# Báo cáo eval ({provider_name})", "", "| Chỉ số | Giá trị |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in rows]
    return "\n".join(lines) + "\n"


def _build_provider(name: str) -> Provider:
    if name == "fake":
        return fake_provider()
    return __import__("app.llm.factory", fromlist=["get_provider"]).get_provider(Settings(llm_provider=name))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline eval for the Fire3D AI answer pipeline")
    parser.add_argument("--provider", choices=["fake", "openai", "gemini"], default="fake")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, default=None, help="thư mục ghi report.json và report.md")
    args = parser.parse_args(argv)

    report = run(args.dataset, _build_provider(args.provider))
    out = args.out or Path("evals/reports") / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = render_markdown(report, args.provider)
    (out / "report.md").write_text(markdown, encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(markdown)
    print(f"Đã ghi báo cáo vào {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
