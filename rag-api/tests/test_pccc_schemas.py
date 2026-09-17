from pydantic import ValidationError
import pytest

from app.schemas.pccc import Advisory, PcccAnalysisRequest


def test_advisory_requires_bim_and_knowledge_evidence() -> None:
    with pytest.raises(ValidationError):
        Advisory(
            priority="high",
            location={"floor_id": "L2"},
            recommendation="Rà soát khu vực",
            reasoning="Thiếu dữ liệu thiết bị.",
            evidence=[],
            missing_data=[],
            requires_engineer_verification=True,
            draft_annotation={"floor_id": "L2", "message": "Rà soát"},
        )


def test_analysis_request_limits_embedded_image_size() -> None:
    with pytest.raises(ValidationError):
        PcccAnalysisRequest.model_validate(
            {
                "building": {"name": "Tòa A"},
                "floors": [],
                "elements": [],
                "images": [
                    {"mime_type": "image/png", "data_base64": "x" * 15_000_000}
                ],
            }
        )
