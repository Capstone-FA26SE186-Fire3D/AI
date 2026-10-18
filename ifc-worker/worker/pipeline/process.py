"""Geometry job: IFC -> preview.glb (fet3d.editor/1) + building_metadata.json (fet3d.building/1)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from worker.gate_client import ClaimResult
from worker.pipeline.classify import Candidate, classify_element, classify_space, load_keywords
from worker.pipeline.extract import read_model
from worker.pipeline.geometry import extract_meshes, placement_of
from worker.pipeline.glb import build_glb
from worker.pipeline.metadata import building_metadata, geometry_metadata, valid_global_id
from worker.pipeline.qa import QaIssue, outcome, run_qa
from worker.runner import OutputFile

log = logging.getLogger("ifc-worker")

CONFIG = Path(__file__).resolve().parents[2] / "config"


class UnprocessableIfc(Exception):
    """The source is not a readable IFC; no outputs are produced and the runner fails the attempt."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.issue = {"severity": "Error", "code": code, "message": message}


def issue_dict(i: QaIssue) -> dict:
    d = {"severity": i.severity, "code": i.code, "message": i.message}
    ids = [g for g in i.ifc_global_ids if valid_global_id(g)][:100]
    if ids:
        d["ifcGlobalIds"] = ids
    return d


def process_ifc(source: Path, workdir: Path, claim: ClaimResult) -> list[OutputFile]:
    try:
        model, info = read_model(source)
    except ValueError as exc:
        if "IFC_UNSUPPORTED_FORMAT" in str(exc):
            raise UnprocessableIfc("IFC_UNSUPPORTED_FORMAT", "Source is not a readable IFC STEP file.") from exc
        raise

    keywords = load_keywords(CONFIG / "keywords.v1.json")
    materials = load_keywords(CONFIG / "materials.v1.json")

    for sp in info.spaces:
        sp.category = classify_space(sp, keywords)
    raw_candidates: dict[str, Candidate] = {}
    for el in info.elements:
        c = classify_element(el, keywords)
        if c is not None:
            raw_candidates[el.global_id] = c

    meshes, report = extract_meshes(model, info, materials)
    workdir = Path(workdir)
    glb_path = workdir / "preview.glb"
    node_map = build_glb(meshes, info.storeys, glb_path)

    # Interactable positions: mesh bbox, else placement origin; none -> not a candidate.
    mesh_by_id = {m.global_id: m for m in meshes}
    positions: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    rotations: dict[str, float] = {}
    for gid in raw_candidates:
        try:
            ent = model.by_guid(gid)
        except RuntimeError:
            ent = None
        placed = placement_of(ent, info.unit_scale) if ent is not None else None
        if placed is not None:
            rotations[gid] = placed[1]
        mesh = mesh_by_id.get(gid)
        if mesh is not None:
            positions[gid] = (mesh.vertices.min(axis=0), mesh.vertices.max(axis=0))
        elif placed is not None:
            p = np.asarray(placed[0], dtype=float)
            positions[gid] = (p, p)
    candidates = {g: c for g, c in raw_candidates.items() if g in positions and valid_global_id(g)}

    issues = run_qa(info, candidates, report)
    result = outcome(issues)

    materials_used: dict[str, set[str]] = {}
    by_el = {e.global_id: e for e in info.elements}
    for m in meshes:
        if m.material_key:
            materials_used.setdefault(m.material_key, set()).update(by_el[m.global_id].material_names)

    space_storey = {s.global_id: s.storey_id for s in info.spaces}
    extra_ids: dict[str, tuple[str, str | None]] = {}

    def note(gid: str) -> None:
        if gid in node_map or gid in extra_ids:
            return
        if gid in space_storey:
            extra_ids[gid] = ("IfcSpace", space_storey[gid])
        elif gid in by_el:
            extra_ids[gid] = (by_el[gid].ifc_class, by_el[gid].storey_id)

    for gid in space_storey:
        note(gid)
    for gid in candidates:
        note(gid)
    for i in issues:
        for gid in i.ifc_global_ids:
            note(gid)

    geo_md = geometry_metadata(info, info.storeys, node_map, extra_ids)
    bld_md = building_metadata(info, candidates, positions, materials_used, issues, claim.source_hash, rotations)

    bld_path = workdir / "building_metadata.json"
    bld_path.write_text(json.dumps(bld_md, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    issue_list = [issue_dict(i) for i in issues]
    log.info("processed IFC: %d meshes, %d candidates, outcome %s", len(meshes), len(candidates), result)
    return [
        OutputFile(path=glb_path, artifact_type="preview_glb", schema_version="fet3d.editor/1", metadata=geo_md,
                   outcome=result, issues=list(issue_list), content_type="model/gltf-binary"),
        OutputFile(path=bld_path, artifact_type="building_metadata", schema_version="fet3d.building/1",
                   metadata=bld_md, outcome=result, issues=list(issue_list), content_type="application/json"),
    ]
