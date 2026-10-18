"""Pydantic models for the BE->AI FastAPI adapter contract v2.

Request/response bodies are snake_case; the pinned `bim` object keeps BE camelCase
(accepted via aliases as well as field names). Unknown fields are ignored.
"""
from __future__ import annotations

from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class SourcePin(_Model):
    kind: Literal["KnowledgeSource", "LibraryVersion", "LearnPost", "TrainingSnapshot", "SessionResult"]
    document_id: str
    document_version: str
    title: str | None = None
    version_label: str | None = None
    content_hash: str | None = None
    source_uri: str | None = None
    content: dict | None = None
    content_omitted: bool = False


class BimFloor(_Model):
    id: str
    name: str
    elevation_meters: float = Field(default=0.0, alias="elevationMeters")
    ifc_global_id: str | None = Field(default=None, alias="ifcGlobalId")


class BimAnchorPin(_Model):
    ifc_global_id: str = Field(alias="ifcGlobalId")
    node_id: str | None = Field(default=None, alias="nodeId")
    floor_id: str = Field(alias="floorId")
    semantic_type: str = Field(alias="semanticType")


class QualityFlag(_Model):
    code: str
    severity: str
    message: str | None = None
    ifc_global_id: str | None = Field(default=None, alias="ifcGlobalId")


class RuntimePin(_Model):
    runtime_version: str | None = Field(default=None, alias="runtimeVersion")
    capabilities: list[Any] = Field(default_factory=list)
    capability_contracts: dict = Field(default_factory=dict, alias="capabilityContracts")


class BimGeometry(_Model):
    artifact_id: str = Field(alias="artifactId")
    sha256_hash: str = Field(alias="sha256Hash")
    schema_version: str = Field(alias="schemaVersion")


class BimPin(_Model):
    revision_id: str = Field(alias="revisionId")
    geometry: BimGeometry
    floors: list[BimFloor]
    anchors: list[BimAnchorPin]
    quality_flags: list[QualityFlag] = Field(default_factory=list, alias="qualityFlags")
    runtime: RuntimePin | None = None


class Limits(_Model):
    quota_unit: str
    max_units: int = Field(ge=1)


class InputText(_Model):
    text: str = Field(min_length=1)


class AdapterRequest(_Model):
    request_id: str
    audience: Literal["organization", "trainee"]
    operation: Literal["Answer", "ScenarioDraft", "TraineeAnswer"]
    response_type: Literal["KnowledgeAnswer", "ScenarioDraft"]
    organization_id: str | None = None
    input: InputText
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    sources: list[SourcePin] = Field(default_factory=list)
    bim: BimPin | None = None
    learn_context: dict | None = None
    context: dict | None = None
    limits: Limits
    attempt: int = 1


class Citation(_Model):
    document_id: str
    document_version: str
    chunk_id: str
    excerpt_locator: str
    relevance: float = Field(ge=0, le=1)


class BimAnchor(_Model):
    ifc_global_id: str
    entity_type: str
    revision_id: str


class RuleResult(_Model):
    rule_id: str
    outcome: Literal["flag", "pass", "not_evaluable"]
    reason: str


class Usage(_Model):
    provider_units: int = Field(ge=0)
    input_tokens: int
    output_tokens: int
    model_version: str


class ScenarioDraftOut(_Model):
    state: dict
    notes: str


class AdapterResponse(_Model):
    request_id: str
    response_type: Literal["KnowledgeAnswer", "ScenarioDraft"]
    status: Literal["Answered", "NeedsUserEdit", "InsufficientEvidence", "RejectedBySafetyGate"]
    recommendation: str
    scenario_draft: ScenarioDraftOut | None = None
    bim_anchors: list[BimAnchor] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    rule_results: list[RuleResult] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    usage: Usage


class RouteSpec(NamedTuple):
    audience: str
    operation: str
    response_type: str
    requires_bim: bool
    organization_id_null: bool


ROUTES: dict[str, RouteSpec] = {
    "organization/answer": RouteSpec("organization", "Answer", "KnowledgeAnswer", False, False),
    "organization/scenario-draft": RouteSpec("organization", "ScenarioDraft", "ScenarioDraft", True, False),
    "trainee/answer": RouteSpec("trainee", "TraineeAnswer", "KnowledgeAnswer", False, True),
}
