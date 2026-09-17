import pytest

from app.pccc.advisory import create_pccc_advisory
from app.schemas.pccc import PcccAnalysisRequest
from app.schemas.rag import SourceChunk


class RecordingModel:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[dict] = []

    def complete(self, system_prompt: str, payload: dict) -> dict:
        self.calls.append({"system_prompt": system_prompt, "payload": payload})
        return self.result


def sample_request() -> PcccAnalysisRequest:
    return PcccAnalysisRequest.model_validate(
        {
            "building": {"name": "Tòa A"},
            "floors": [{"id": "L1", "number": 1, "name": "Tầng 1"}],
            "elements": [{"id": "exit-1", "element_type": "exit", "floor_id": "L1"}],
        }
    )


def approved_sources() -> list[SourceChunk]:
    return [SourceChunk(document_name="qcvn.pdf", chunk_index=0, content="Lối thoát", source_id="qcvn.pdf:0")]


def valid_result() -> dict:
    return {
        "model_name": "fake",
        "advisories": [
            {
                "priority": "needs_review",
                "location": {"floor_id": "L1", "element_id": "exit-1"},
                "recommendation": "Kỹ sư kiểm tra lối thoát.",
                "reasoning": "Dữ liệu BIM cần được xác minh.",
                "evidence": {"bim_element_ids": ["exit-1"], "knowledge_sources": [{"source_id": "qcvn.pdf:0", "document_name": "qcvn.pdf", "chunk_index": 0, "version": "2023"}]},
                "missing_data": [],
                "requires_engineer_verification": True,
                "draft_annotation": {"floor_id": "L1", "element_id": "exit-1", "message": "Kiểm tra lối thoát"},
            }
        ],
    }


def test_does_not_call_model_without_approved_sources() -> None:
    model = RecordingModel(valid_result())

    with pytest.raises(ValueError, match="approved PCCC knowledge"):
        create_pccc_advisory(sample_request(), [], model)

    assert model.calls == []


def test_rejects_model_advice_with_unknown_evidence() -> None:
    result = valid_result()
    result["advisories"][0]["evidence"]["bim_element_ids"] = ["invented"]

    with pytest.raises(ValueError, match="unknown BIM element"):
        create_pccc_advisory(sample_request(), approved_sources(), RecordingModel(result))


def test_passes_only_compact_evidence_bound_payload_to_model() -> None:
    model = RecordingModel(valid_result())

    response = create_pccc_advisory(sample_request(), approved_sources(), model)

    assert response.advisories[0].requires_engineer_verification is True
    assert model.calls[0]["payload"]["knowledge"][0]["source_id"] == "qcvn.pdf:0"
