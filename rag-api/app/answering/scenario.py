"""ScenarioDraft anchored to the BE-pinned BIM revision; produces fet3d.editor/1 state BE accepts."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

from jsonschema import Draft202012Validator

from app.answering.pipeline import (
    NO_SOURCE, Grounded, PipelineDeps, _terminal, ground, parse_grounded, vet_text,
)
from app.answering.prompts import DRAFT_SCHEMA, bim_summary
from app.answering.usage import to_usage
from app.answering.validate import clean_list, to_plain_text
from app.sources.resolver import PreparedSources
from app.v2.errors import refuse
from app.v2.schemas import (
    AdapterRequest, AdapterResponse, BimAnchor, BimPin, RuleResult, ScenarioDraftOut, capability_ids,
)

_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "contracts" / "scenario-state.schema.json").read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA)
_KINDS = ("Spawn", "Hazard", "Goal", "Npc", "BlockedElement", "Equipment")
_NEEDS_CAPABILITY = ("Hazard", "Npc", "Equipment")
_MODES = ("Learn", "Guided", "Assessment")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DRAFT_REQUIRED = ("status", "answer", "citations", "assumptions", "limitations", "notes", "bim_anchor_ids", "state")


def _num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _build_object(raw: object, bim: BimPin, caps: dict[str, str | None]) -> tuple[dict | None, str | None]:
    """Return (object, None) or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "không phải đối tượng hợp lệ"
    kind = raw.get("kind")
    if kind not in _KINDS:
        return None, "loại đối tượng không hợp lệ"
    floor_id = raw.get("floorId")
    if floor_id not in {f.id for f in bim.floors}:
        return None, "tầng không thuộc bản BIM đã ghim"
    anchor_id = raw.get("anchorId") or None
    if anchor_id is not None:
        if not any(a.ifc_global_id == anchor_id and a.floor_id == floor_id for a in bim.anchors):
            return None, "anchor không thuộc bản BIM đã ghim trên cùng tầng"
    elif kind == "BlockedElement":
        return None, "phần tử bị chặn thiếu anchor"
    cap_id = raw.get("capabilityId") or None
    capability = None
    if cap_id is not None:
        if cap_id not in caps:
            return None, "capability không có trong runtime đã ghim"
        if caps[cap_id] is None:
            return None, "runtime không cung cấp phiên bản cho capability"
        capability = {"id": cap_id, "version": caps[cap_id]}
    elif kind in _NEEDS_CAPABILITY:
        return None, "thiếu capability bắt buộc"
    pos = raw.get("position")
    if not isinstance(pos, dict) or not all(_num(pos.get(k)) for k in "xyz"):
        return None, "vị trí không hợp lệ"
    obj: dict = {
        "id": raw.get("id"),
        "kind": kind,
        "placement": {
            "floorId": floor_id,
            "position": {k: pos[k] for k in "xyz"},
            "rotation": {"x": 0, "y": 0, "z": 0, "w": 1},
        },
    }
    label = to_plain_text(raw.get("label"), 255)
    if label:
        obj["label"] = label
    if anchor_id is not None:
        obj["anchorId"] = anchor_id
    if capability is not None:
        obj["capability"] = capability
        params: object = {}
        if isinstance(raw.get("parameters"), str):
            try:
                params = json.loads(raw["parameters"])
            except ValueError:
                params = {}
        obj["parameters"] = params if isinstance(params, dict) else {}
    return obj, None


def _object_invalid(obj: dict) -> bool:
    return any(True for _ in _VALIDATOR.iter_errors({"schemaVersion": "fet3d.editor/1", "objects": [obj]}))


def build_state(model_state: dict, bim: BimPin) -> tuple[dict, list[str]]:
    limitations: list[str] = []
    ms = model_state if isinstance(model_state, dict) else {}
    state: dict = {
        "schemaVersion": "fet3d.editor/1",
        "geometry": {"artifactId": bim.geometry.artifact_id, "sha256Hash": bim.geometry.sha256_hash},
    }
    if bim.runtime and bim.runtime.runtime_version:
        state["runtimeVersion"] = bim.runtime.runtime_version

    name = to_plain_text(ms.get("name"), 255)
    if name:
        state["name"] = name
    seconds = ms.get("timeLimitSeconds")
    if isinstance(seconds, int) and not isinstance(seconds, bool):
        state["timeLimitSeconds"] = seconds
    if isinstance(ms.get("learningObjectives"), list):
        objectives = list(dict.fromkeys(clean_list(ms["learningObjectives"])))
        if objectives:
            state["learningObjectives"] = objectives
    instructions = to_plain_text(ms.get("learnerInstructions"), 10000)
    if instructions:
        state["learnerInstructions"] = instructions
    policy = ms.get("modePolicy")
    if isinstance(policy, dict) and isinstance(policy.get("allowedModes"), list):
        modes = [m for m in dict.fromkeys(m for m in policy["allowedModes"] if isinstance(m, str)) if m in _MODES]
        if modes:
            state["modePolicy"] = {"allowedModes": modes}

    caps = capability_ids(bim.runtime)
    objects: list[dict] = []
    seen: set[str] = set()
    for raw in ms.get("objects") if isinstance(ms.get("objects"), list) else []:
        oid = raw.get("id") if isinstance(raw, dict) else None
        label = oid if isinstance(oid, str) and oid else "?"
        obj, reason = _build_object(raw, bim, caps)
        if obj is not None and not (isinstance(oid, str) and _ID.match(oid)):
            obj, reason = None, "mã đối tượng không hợp lệ"
        if obj is not None and oid in seen:
            obj, reason = None, "mã đối tượng bị trùng"
        if obj is not None and _object_invalid(obj):
            obj, reason = None, "không đúng định dạng kịch bản"
        if obj is None:
            limitations.append(f"Đã loại đối tượng {label}: {reason}.")
            continue
        seen.add(oid)
        objects.append(obj)
    if objects:
        state["objects"] = objects

    for _ in range(len(state) + 1):
        errors = [e for e in _VALIDATOR.iter_errors(state) if e.path]
        if not errors:
            break
        for field in {e.path[0] for e in errors}:
            if field in state:
                del state[field]
                limitations.append(f"Đã bỏ trường {field} vì không đúng định dạng kịch bản.")
    return state, limitations


def build_bim_anchors(ids: list[str], bim: BimPin) -> list[BimAnchor]:
    anchors = {a.ifc_global_id: a.semantic_type for a in bim.anchors}
    floors = {f.ifc_global_id for f in bim.floors if f.ifc_global_id}
    out: list[BimAnchor] = []
    seen: set[str] = set()
    for gid in ids if isinstance(ids, list) else []:
        if not isinstance(gid, str) or gid in seen:
            continue
        if gid in anchors:
            entity = anchors[gid]
        elif gid in floors:
            entity = "IfcBuildingStorey"
        else:
            continue
        seen.add(gid)
        out.append(BimAnchor(ifc_global_id=gid, entity_type=entity, revision_id=bim.revision_id))
    return out


_FLAG_RULES = {
    "EXIT_MAPPING_MISSING": ("exit-mapping", "Mô hình chưa xác định được lối thoát (cửa, cầu thang, dốc); cần kiểm tra thủ công."),
    "FLOOR_MAPPING_INCOMPLETE": ("floor-mapping", "Ánh xạ tầng của mô hình chưa đầy đủ; một số phần tử có thể thiếu tầng."),
    "SEMANTIC_MAPPING_EMPTY": ("semantic-mapping", "Mô hình không có ánh xạ ngữ nghĩa; không có anchor để gắn đối tượng."),
    "RUNTIME_CATALOG_EMPTY": ("runtime-catalog", "Danh mục runtime trống; không thể dùng capability cho Hazard, Npc, Equipment."),
    "ANCHORS_TRUNCATED": ("anchors-truncated", "Danh sách anchor bị cắt bớt; có thể thiếu phần tử của mô hình."),
    "IFC_EXIT_UNKNOWN": ("ifc-exit", "Không rõ lối thoát trong dữ liệu IFC; cần kiểm tra thủ công."),
}
_EXIT_FLAGS = ("EXIT_MAPPING_MISSING", "IFC_EXIT_UNKNOWN")


def rule_results_from_flags(bim: BimPin) -> list[RuleResult]:
    codes = {q.code for q in bim.quality_flags}
    results = [
        RuleResult(rule_id=_FLAG_RULES[c][0], outcome="flag", reason=_FLAG_RULES[c][1]) for c in _FLAG_RULES if c in codes
    ]
    if not any(c in codes for c in _EXIT_FLAGS) and any(a.semantic_type == "IfcDoor" for a in bim.anchors):
        results.append(RuleResult(
            rule_id="exit-mapping", outcome="pass",
            reason="Mô hình có cửa được ánh xạ; đây chỉ là quan sát, không phải kết luận tuân thủ.",
        ))
    return results


def run_scenario_draft(
    req: AdapterRequest, prepared: PreparedSources, deps: PipelineDeps, budget: int | None
) -> AdapterResponse:
    bim = req.bim
    if bim is None:
        raise refuse("AI_REVISION_NOT_PINNED", "ScenarioDraft requires a pinned BIM revision")
    rules = rule_results_from_flags(bim)

    def done(resp: AdapterResponse) -> AdapterResponse:
        resp.rule_results = rules
        return resp

    g = ground(req, prepared, deps, budget, DRAFT_SCHEMA, {"bim": bim_summary(bim)})
    if not isinstance(g, Grounded):
        return done(g)
    p = parse_grounded(req, g, _DRAFT_REQUIRED)
    if isinstance(p, AdapterResponse):
        return done(p)

    notes_raw = p.raw["notes"] if isinstance(p.raw["notes"], str) and p.raw["notes"].strip() else p.raw["answer"]
    notes, terminal = vet_text(req, notes_raw, p)
    if terminal:
        return done(terminal)

    anchors = build_bim_anchors(p.raw["bim_anchor_ids"], bim)
    if not anchors:
        return done(_terminal(
            req, "InsufficientEvidence", NO_SOURCE,
            p.limitations + ["Bản nháp không dựa trên anchor nào của BIM đã ghim."], g.llm, p.assumptions,
        ))

    state, state_limits = build_state(p.raw["state"], bim)
    return done(AdapterResponse(
        request_id=req.request_id, response_type=req.response_type, status="NeedsUserEdit",
        recommendation=notes, scenario_draft=ScenarioDraftOut(state=state, notes=notes), bim_anchors=anchors,
        citations=p.citations, rule_results=rules, confidence="medium", assumptions=p.assumptions,
        limitations=(p.limitations + state_limits)[:20], usage=to_usage(g.llm, req.limits),
    ))
