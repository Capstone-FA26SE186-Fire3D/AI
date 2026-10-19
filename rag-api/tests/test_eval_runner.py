from pathlib import Path

from evals.run_eval import fake_provider, run

DATASET = Path(__file__).resolve().parents[1] / "evals" / "dataset.jsonl"
KEYS = {
    "cases", "citation_coverage", "abstain_accuracy", "safety_refusal_accuracy",
    "injection_resisted", "avg_latency_ms", "total_tokens", "failures",
}


def test_eval_runner_fake_provider():
    report = run(DATASET, fake_provider())
    assert KEYS <= set(report)
    assert report["cases"] >= 16
    assert report["safety_refusal_accuracy"] == 1.0
    assert report["abstain_accuracy"] == 1.0
    assert report["injection_resisted"] == 1.0
    assert report["citation_coverage"] == 1.0
    assert report["failures"] == []
    assert report["total_tokens"] > 0
