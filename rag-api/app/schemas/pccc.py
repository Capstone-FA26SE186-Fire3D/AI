from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


ElementType = Literal[
    "door",
    "stair",
    "exit",
    "corridor",
    "extinguisher",
    "hydrant",
    "detector",
    "sprinkler",
    "emergency_light",
    "exit_sign",
    "fire_door",
    "fire_compartment",
    "other",
]


class BuildingInfo(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    occupancy: str | None = Field(default=None, max_length=255)
    jurisdiction: str = Field(default="VN", min_length=2, max_length=32)
    fire_height_meters: float | None = Field(default=None, ge=0)
    total_floors: int | None = Field(default=None, ge=0, le=500)


class SpaceInput(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    occupancy: str | None = Field(default=None, max_length=255)
    area_sqm: float | None = Field(default=None, ge=0)


class FloorInput(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    number: int = Field(ge=-20, le=500)
    name: str = Field(min_length=1, max_length=255)
    area_sqm: float | None = Field(default=None, ge=0)
    elevation_meters: float | None = None
    spaces: list[SpaceInput] = Field(default_factory=list, max_length=10000)


class BimElement(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    element_type: ElementType
    name: str | None = Field(default=None, max_length=500)
    floor_id: str | None = Field(default=None, max_length=255)
    space_id: str | None = Field(default=None, max_length=255)
    coordinates: tuple[float, float, float] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class BimSource(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    file_type: str = Field(min_length=1, max_length=20)
    revision_id: str | None = Field(default=None, max_length=255)


class BimImage(BaseModel):
    mime_type: Literal["image/png", "image/jpeg"]
    data_base64: str = Field(min_length=1, max_length=14_000_000)
    floor_id: str | None = Field(default=None, max_length=255)


class BuildingAnalysisInput(BaseModel):
    building: BuildingInfo
    floors: list[FloorInput] = Field(default_factory=list, max_length=500)
    elements: list[BimElement] = Field(default_factory=list, max_length=100_000)
    source: BimSource | None = None


class KnowledgeDocumentMetadata(BaseModel):
    approved: Literal[True]
    jurisdiction: str = Field(default="VN", min_length=2, max_length=32)
    version: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=255)


class KnowledgeSource(BaseModel):
    source_id: str = Field(min_length=1, max_length=500)
    document_name: str = Field(min_length=1, max_length=500)
    chunk_index: int = Field(ge=0)
    version: str = Field(min_length=1, max_length=100)


class Evidence(BaseModel):
    bim_element_ids: list[str] = Field(min_length=1, max_length=100)
    knowledge_sources: list[KnowledgeSource] = Field(min_length=1, max_length=20)


class Location(BaseModel):
    floor_id: str = Field(min_length=1, max_length=255)
    space_id: str | None = Field(default=None, max_length=255)
    element_id: str | None = Field(default=None, max_length=255)


class DraftAnnotation(BaseModel):
    floor_id: str = Field(min_length=1, max_length=255)
    space_id: str | None = Field(default=None, max_length=255)
    element_id: str | None = Field(default=None, max_length=255)
    message: str = Field(min_length=1, max_length=2000)


class Advisory(BaseModel):
    priority: Literal["critical", "high", "medium", "low", "needs_review"]
    location: Location
    recommendation: str = Field(min_length=1, max_length=2000)
    reasoning: str = Field(min_length=1, max_length=4000)
    evidence: Evidence
    missing_data: list[str] = Field(default_factory=list, max_length=100)
    requires_engineer_verification: Literal[True] = True
    draft_annotation: DraftAnnotation


class PcccAnalysisRequest(BuildingAnalysisInput):
    question: str = Field(
        default="Rà soát các khu vực cần kỹ sư PCCC xác minh.",
        min_length=1,
        max_length=4000,
    )
    images: list[BimImage] = Field(default_factory=list, max_length=20)

    @field_validator("images")
    @classmethod
    def image_floor_ids_must_exist(cls, images: list[BimImage], info: Any) -> list[BimImage]:
        floor_ids = {floor.id for floor in info.data.get("floors", [])}
        invalid = [image.floor_id for image in images if image.floor_id and image.floor_id not in floor_ids]
        if invalid:
            raise ValueError("Each image floor_id must reference a submitted floor")
        return images


class PcccAnalysisResponse(BaseModel):
    advisories: list[Advisory] = Field(default_factory=list, max_length=100)
    model_name: str = Field(min_length=1, max_length=100)
    disclaimer: str = Field(
        default="Khuyến nghị hỗ trợ; cần kỹ sư PCCC có thẩm quyền xác minh.",
        min_length=1,
        max_length=1000,
    )


class BimInspectionResponse(BaseModel):
    building: BuildingAnalysisInput
    warnings: list[str] = Field(default_factory=list, max_length=100)
    missing_data: list[str] = Field(default_factory=list, max_length=100)
