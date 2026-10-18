import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.answering.pipeline import PipelineDeps, run_pipeline
from app.answering.scenario import build_bim_anchors, build_state, rule_results_from_flags
from app.core.config import Settings
from app.index.memory import MemoryIndex
from app.llm.fake import FakeProvider
from app.sources.resolver import SourceResolver
from app.v2.errors import AdapterRefusal
from app.v2.schemas import AdapterRequest, BimPin, SourcePin

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts" / "scenario-state.schema.json").read_text(encoding="utf-8"))
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "v2" / "organization-scenario-draft.json").read_text(encoding="utf-8"))

DOOR = "3cUkl32yn9qRSPvBJVyWYp"
SPACE = "1hOSvn6df7F8_7GcBWlRGQ"
L2_DOOR = "1hOSvn6df7F8_7GcBWlRGR"
FLOOR1 = "2O2Fr$t4X7Zf8NOew3FLOH"

BIM = {
    **FIXTURE["bim"],
    "floors": [
        {"id": "L1", "name": "Tầng 1", "elevationMeters": 0, "ifcGlobalId": FLOOR1},
        {"id": "L2", "name": "Tầng 2", "elevationMeters": 3, "ifcGlobalId": None},
    ],
    "anchors": [
        {"ifcGlobalId": DOOR, "nodeId": "door_101", "floorId": "L1", "semanticType": "IfcDoor"},
        {"ifcGlobalId": SPACE, "nodeId": "space_1", "floorId": "L1", "semanticType": "IfcSpace"},
        {"ifcGlobalId": L2_DOOR, "nodeId": "door_201", "floorId": "L2", "semanticType": "IfcDoor"},
    ],
    "qualityFlags": [],
    "runtime": {
        "runtimeVersion": "1.4.0", "protocolVersion": "1",
        "capabilities": ["fire.source", {"id": "npc.evacuee", "version": "2.1.0"}, {"id": "equipment.extinguisher", "version": "1.0.0"}],
        "capabilityContracts": {},
    },
}
POST = SourcePin(
    kind="LearnPost", document_id="lp-1", document_version="3", title="Thoát hiểm",
    content={"title": "Kịch bản sơ tán tầng 1", "summary": "Tạo kịch bản sơ tán qua cửa thoát hiểm tầng 1"},
)


def _req(bim=BIM, pins=(POST,), text="Tạo kịch bản sơ tán tầng 1", units=50000):
    return AdapterRequest(
        request_id="r1", audience="organization", operation="ScenarioDraft", response_type="ScenarioDraft",
        organization_id="org", input={"text": text}, input_hash="a" * 64, sources=list(pins), bim=bim,
        limits={"quota_unit": "tokens", "max_units": units},
    )


def _obj(**over):
    base = {"id": "spawn-1", "kind": "Spawn", "label": "Phòng 101", "anchorId": None, "floorId": "L1",
            "position": {"x": 1, "y": 0, "z": 2}, "capabilityId": None, "parameters": "{}"}
    base.update(over)
    return base


def _draft(payload, objects=None, anchor_ids=(DOOR,), geometry_attack=False, **over):
    cid = payload["chunks"][0]["chunk_id"]
    state = {
        "name": "Sơ tán tầng 1", "timeLimitSeconds": 600, "learningObjectives": ["Thoát hiểm an toàn"],
        "learnerInstructions": "Rời toà nhà qua cửa thoát.", "modePolicy": {"allowedModes": ["Learn", "Guided"]},
        "objects": objects if objects is not None else [_obj(), _obj(id="goal", kind="Goal", anchorId=DOOR)],
    }
    if geometry_attack:
        state["geometry"] = {"artifactId": "evil", "sha256Hash": "0" * 64}
    out = {
        "status": "answered", "answer": "Bản nháp.", "citations": [{"chunk_id": cid, "relevance": 0.9}],
        "assumptions": [], "limitations": [], "notes": "Bản nháp **sơ tán** tầng 1.",
        "bim_anchor_ids": list(anchor_ids), "state": state,
    }
    out.update(over)
    return out


def _run(req, responder):
    provider = FakeProvider(responder)
    index = MemoryIndex()
    settings = Settings()
    prepared = SourceResolver(index, provider, settings).prepare(req.sources)
    return run_pipeline(req, prepared, PipelineDeps(provider, index, settings)), provider


def _pin(**over):
    return BimPin.model_validate({**BIM, **over})


def test_draft_pins_geometry_even_if_model_changes_it():
    resp, _ = _run(_req(), lambda p: _draft(p, geometry_attack=True))
    assert resp.status == "NeedsUserEdit"
    geo = resp.scenario_draft.state["geometry"]
    assert geo == {"artifactId": BIM["geometry"]["artifactId"], "sha256Hash": BIM["geometry"]["sha256Hash"]}
    assert resp.scenario_draft.state["schemaVersion"] == "fet3d.editor/1"
    assert resp.scenario_draft.state["runtimeVersion"] == "1.4.0"
    assert resp.recommendation == resp.scenario_draft.notes and "**" not in resp.recommendation
    assert resp.citations and resp.bim_anchors[0].revision_id == BIM["revisionId"]


def test_object_with_unknown_anchor_removed_with_limitation():
    objs = [_obj(), _obj(id="goal-bad", kind="Goal", anchorId="ZZZZZZZZZZZZZZZZZZZZZZ"),
            _obj(id="goal-wrong-floor", kind="Goal", anchorId=L2_DOOR)]
    resp, _ = _run(_req(), lambda p: _draft(p, objects=objs))
    ids = [o["id"] for o in resp.scenario_draft.state["objects"]]
    assert ids == ["spawn-1"]
    assert any("goal-bad" in l for l in resp.limitations) and any("goal-wrong-floor" in l for l in resp.limitations)


def test_capability_not_in_runtime_removed():
    objs = [
        _obj(id="fire-x", kind="Hazard", capabilityId="fire.unknown"),
        _obj(id="fire-nover", kind="Hazard", capabilityId="fire.source"),
        _obj(id="hz-none", kind="Hazard"),
        _obj(id="npc-1", kind="Npc", capabilityId="npc.evacuee", parameters='{"behaviour": "panic"}'),
        _obj(id="npc-badjson", kind="Npc", capabilityId="npc.evacuee", parameters="not json"),
    ]
    resp, _ = _run(_req(), lambda p: _draft(p, objects=objs))
    state_objs = {o["id"]: o for o in resp.scenario_draft.state["objects"]}
    assert set(state_objs) == {"npc-1", "npc-badjson"}
    assert state_objs["npc-1"]["capability"] == {"id": "npc.evacuee", "version": "2.1.0"}
    assert state_objs["npc-1"]["parameters"] == {"behaviour": "panic"}
    assert state_objs["npc-badjson"]["parameters"] == {}
    for oid in ("fire-x", "fire-nover", "hz-none"):
        assert any(oid in l for l in resp.limitations)


def test_bim_anchors_only_from_pin():
    resp, _ = _run(_req(), lambda p: _draft(p, anchor_ids=["unknown-id", DOOR, FLOOR1, DOOR]))
    assert [(a.ifc_global_id, a.entity_type) for a in resp.bim_anchors] == [(DOOR, "IfcDoor"), (FLOOR1, "IfcBuildingStorey")]
    resp, _ = _run(_req(), lambda p: _draft(p, anchor_ids=["unknown-id"]))
    assert resp.status == "InsufficientEvidence" and resp.scenario_draft is None and resp.bim_anchors == []


def test_missing_bim_refused_revision_not_pinned():
    provider = FakeProvider(lambda p: _draft(p))
    req = _req(bim=None)
    index = MemoryIndex()
    prepared = SourceResolver(index, provider, Settings()).prepare(req.sources)
    with pytest.raises(AdapterRefusal) as exc:
        run_pipeline(req, prepared, PipelineDeps(provider, index, Settings()))
    assert exc.value.code == "AI_REVISION_NOT_PINNED" and exc.value.status_code == 422
    assert provider.calls == []


def test_rule_results_flag_exit_mapping_missing():
    bim = {**BIM, "qualityFlags": [{"code": "EXIT_MAPPING_MISSING", "severity": "Warning"}]}
    rules = rule_results_from_flags(BimPin.model_validate(bim))
    assert [(r.rule_id, r.outcome) for r in rules] == [("exit-mapping", "flag")]
    ok = rule_results_from_flags(_pin())
    assert [(r.rule_id, r.outcome) for r in ok] == [("exit-mapping", "pass")]
    # attached even to InsufficientEvidence
    resp, _ = _run(_req(bim=bim), lambda p: _draft(p, status="insufficient"))
    assert resp.status == "InsufficientEvidence"
    assert [r.outcome for r in resp.rule_results] == ["flag"]


def test_state_passes_vendored_schema():
    resp, _ = _run(_req(), lambda p: _draft(p, objects=[
        _obj(), _obj(id="goal", kind="Goal", anchorId=DOOR),
        _obj(id="blocked", kind="BlockedElement", anchorId=SPACE),
        _obj(id="blocked-none", kind="BlockedElement"),
        _obj(id="spawn-1"),  # duplicate id
        _obj(id="bad floor", floorId="L9"),
    ]))
    state = resp.scenario_draft.state
    assert not list(Draft202012Validator(SCHEMA).iter_errors(state))
    assert [o["id"] for o in state["objects"]] == ["spawn-1", "goal", "blocked"]
    assert all(o["placement"]["rotation"] == {"x": 0, "y": 0, "z": 0, "w": 1} for o in state["objects"])


def test_invalid_top_level_field_dropped_with_limitation():
    state, limits = build_state({"name": "x", "timeLimitSeconds": 10**9, "objects": []}, _pin())
    assert "timeLimitSeconds" not in state and state["name"] == "x"
    assert any("timeLimitSeconds" in l for l in limits)
    assert not list(Draft202012Validator(SCHEMA).iter_errors(state))


def test_raw_ifc_not_in_payload():
    many = [{"ifcGlobalId": f"{i:022d}", "nodeId": f"n{i}", "floorId": "L1", "semanticType": "IfcWall"} for i in range(500)]
    bim = {**BIM, "anchors": many + BIM["anchors"]}
    _, provider = _run(_req(bim=bim), lambda p: _draft(p))
    payload = provider.calls[0]
    text = json.dumps(payload, ensure_ascii=False)
    assert BIM["geometry"]["sha256Hash"] not in text
    assert "coordinateTransform" not in text and "annotations" not in text and "geometry" not in payload["bim"]
    anchors = payload["bim"]["anchors"]
    assert len(anchors) == 300
    assert {a["ifcGlobalId"] for a in anchors} >= {DOOR, SPACE, L2_DOOR}  # priority types kept over walls


def test_draft_schema_is_strict_openai_compatible():
    from app.answering.prompts import DRAFT_SCHEMA

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node["properties"]) == set(node["required"])
                assert node["properties"], "no free-form objects"
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(DRAFT_SCHEMA)


def test_build_bim_anchors_helper():
    assert build_bim_anchors([], _pin()) == []
    assert build_bim_anchors("nope", _pin()) == []  # type: ignore[arg-type]
