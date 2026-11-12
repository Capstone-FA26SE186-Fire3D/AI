from app.answering.prompts import system_prompt
from app.answering.retrieval import retrieve
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.fake import FakeProvider
from app.sources.criteria import criterion_text, metric_label, snapshot_sections
from app.sources.render import inline_sections
from app.sources.resolver import SourceResolver
from app.v2.schemas import SourcePin

ASSESSMENT = {
    "sessionId": "s-1", "mode": "Assessment", "outcome": "NotPassed", "reason": "MANDATORY_CRITERION_FAILED", "scorePercent": 40,
    "criteria": [
        {"id": "exit", "metric": "reached_exit", "value": 1, "operator": "eq", "threshold": 1, "mandatory": True,
         "weight": 1, "passed": True, "reason": None, "label": "Thoát ra ngoài"},
        {"id": "time", "metric": "completion_time_seconds", "value": 212.5, "operator": "lte", "threshold": 180,
         "mandatory": True, "weight": 1, "passed": False, "reason": None},
        {"id": "nose", "metric": "nose_covered_in_smoke", "operator": "gte", "threshold": 1, "mandatory": False,
         "weight": 1, "passed": False, "reason": "METRIC_UNAVAILABLE"},
    ],
    "metrics": {"reached_exit": 1, "completion_time_seconds": 212.5, "wrong_exits": 2},
}


def test_result_criteria_read_as_sentences_with_outcome():
    texts = [t for t, _ in snapshot_sections(ASSESSMENT)]
    exit_line = next(t for t in texts if t.startswith("Tiêu chí 1"))
    assert "Thoát ra ngoài" in exit_line and "bắt buộc" in exit_line and "ĐẠT" in exit_line and "= 1" in exit_line
    time_line = next(t for t in texts if t.startswith("Tiêu chí 2"))
    assert "Thời gian thoát hiểm" in time_line and "≤ 180" in time_line and "CHƯA ĐẠT" in time_line and "212.5" in time_line
    nose_line = next(t for t in texts if t.startswith("Tiêu chí 3"))
    assert "chưa đủ dữ liệu" in nose_line and "bắt buộc" not in nose_line
    assert "Chỉ số đã đo: Số lần đi nhầm lối (wrong_exits) = 2." in texts
    assert any(t.startswith("outcome: NotPassed") for t in texts)


def test_training_criteria_have_no_threshold_or_result():
    text = criterion_text(1, {"label": "Che mũi khi có khói", "description": "Dùng khăn ướt che mũi miệng.", "metric": "nose_covered_in_smoke"})
    assert text == ("Tiêu chí 1: Che mũi khi có khói; mô tả: Dùng khăn ướt che mũi miệng.; "
                    "đo bằng: Che mũi miệng khi có khói (nose_covered_in_smoke).")
    assert "yêu cầu" not in text and "kết quả" not in text
    assert criterion_text(2, {"metric": "unknown_metric"}).startswith("Tiêu chí 2: unknown_metric")
    assert metric_label(None) == "Chỉ số"


def test_learn_result_without_criteria_still_lists_metrics():
    sections = snapshot_sections({"mode": "Learn", "outcome": "NotAssessed", "criteria": None, "metrics": {"distance_meters": 48.25}})
    texts = [t for t, _ in sections]
    assert "Chỉ số đã đo: Quãng đường di chuyển (mét) (distance_meters) = 48.25." in texts
    assert not any(t.startswith("Tiêu chí") for t in texts)


def test_inline_rendering_uses_one_section_per_criterion():
    pin = SourcePin(kind="SessionResult", document_id="s-1", document_version="s-1", content=ASSESSMENT)
    sections = inline_sections(pin)
    criteria = [s for s in sections if s.locator.get("field") == "criteria"]
    assert [s.locator["criterion"] for s in criteria] == ["exit", "time", "nose"]


def test_context_snapshot_always_reaches_the_model():
    """Every criterion of the result is passed on, even when the question shares no words with it."""
    big = dict(ASSESSMENT, criteria=[dict(ASSESSMENT["criteria"][1], id=f"c{i}", label=f"Tiêu chí số {i}") for i in range(12)])
    pins = [
        SourcePin(kind="SessionResult", document_id="s-1", document_version="s-1", title="Kết quả", content=big),
        SourcePin(kind="LearnPost", document_id="lp-1", document_version="1", title="Bài học",
                  content={"title": "Bình chữa cháy", "summary": "Cách dùng bình chữa cháy xách tay"}),
    ]
    provider, index = FakeProvider(), MemoryIndex()
    prepared = SourceResolver(index, provider, Settings(_env_file=None)).prepare(pins)
    hits = retrieve("bình chữa cháy", prepared, index, provider, top_k=3)
    result_ids = {h.chunk.chunk_id for h in hits if h.chunk.document_id == "s-1"}
    all_result_chunks = {c.chunk_id for c in prepared.inline_chunks if c.document_id == "s-1"}
    assert result_ids == all_result_chunks
    assert hits[0].chunk.document_id == "s-1" and hits[0].score == 1.0
    assert any(h.chunk.document_id == "lp-1" for h in hits), "ranked sources still follow"


def test_prompts_walk_criteria_and_never_guess_thresholds():
    result = system_prompt("trainee", "TraineeAnswer", "Result")
    assert "không chấm lại" in result and "từng tiêu chí" in result and "Học/Diễn tập" in result
    training = system_prompt("trainee", "TraineeAnswer", "Training")
    assert "từng tiêu chí" in training and "Không đoán ngưỡng" in training
    assert "Loại ngữ cảnh: Learn." in system_prompt("trainee", "TraineeAnswer", "Learn")
