"""Geometry job: IFC -> preview.glb (fet3d.editor/1) + building_metadata.json (fet3d.building/1)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from worker.blender import optimize_glb
from worker.gate_client import ClaimResult
from worker.pipeline.classify import Candidate, classify_element, classify_space, load_keywords
from worker.pipeline.extract import read_model
from worker.pipeline.geometry import extract_meshes, extract_space_boxes, placement_of, recentre_offset
from worker.pipeline.glb import build_glb
from worker.pipeline.metadata import building_metadata, geometry_metadata, valid_global_id
from worker.pipeline.qa import MAX_IDS, QaIssue, outcome, run_qa
from worker.runner import OutputFile

log = logging.getLogger("ifc-worker")

CONFIG = Path(__file__).resolve().parents[2] / "config"
COORD_LIMIT = 100_000.0  # BE BuildingMetadataValidator rejects position/bbox components beyond this


def duplicate_global_ids(info) -> list[str]:
    """GlobalIds used by more than one storey/space/element (first occurrence order)."""
    seen: set[str] = set()
    dupes: list[str] = []
    for gid in [s.ifc_global_id for s in info.storeys] + [s.global_id for s in info.spaces] +             [e.global_id for e in info.elements]:
        if gid in seen and gid not in dupes:
            dupes.append(gid)
        seen.add(gid)
    return dupes


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


def process_ifc(source: Path, workdir: Path, claim: ClaimResult, settings=None) -> list[OutputFile]:
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
    space_raw, space_missing = extract_space_boxes(model, info)
    report.missing_body.extend(space_missing)  # QA IFC_NO_BODY_GEOMETRY (Warning); no bbox is written

    # Placements of candidates (GLB metres, before recentring).
    placements: dict[str, tuple[tuple[float, float, float], float]] = {}
    for gid in raw_candidates:
        try:
            ent = model.by_guid(gid)
        except RuntimeError:
            continue
        placed = placement_of(ent, info.unit_scale)
        if placed is not None:
            placements[gid] = placed

    # Recentre: survey/shared coordinates (e.g. VN-2000, hundreds of km) would put the preview far from
    # the origin and produce positions BE rejects (|n| > 1e5). The shift goes into coordinateTransform.
    offset = recentre_offset(meshes, [p for p, _ in placements.values()])
    off = np.asarray(offset, dtype=float)
    for m in meshes:
        m.vertices = m.vertices - off

    workdir = Path(workdir)
    glb_path = workdir / "preview.glb"
    node_map = build_glb(meshes, info.storeys, glb_path)
    if settings is not None and settings.blender_path:
        optimize_glb(glb_path, settings)  # optional lightmap UVs; runner hashes the final file

    # Interactable positions: mesh bbox, else placement origin; none -> not a candidate.
    mesh_by_id = {m.global_id: m for m in meshes}
    positions: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    rotations = {g: rot for g, (_, rot) in placements.items()}
    out_of_range: list[str] = []
    for gid in raw_candidates:
        mesh = mesh_by_id.get(gid)
        if mesh is not None:
            box = (mesh.vertices.min(axis=0), mesh.vertices.max(axis=0))
        elif gid in placements:
            pt = np.asarray(placements[gid][0], dtype=float) - off
            box = (pt, pt)
        else:
            continue
        if max(np.abs(box[0]).max(), np.abs(box[1]).max(), (box[1] - box[0]).max()) > COORD_LIMIT:
            out_of_range.append(gid)  # defensive: BE rejects |n| > 1e5 m
            continue
        positions[gid] = box
    candidates = {g: c for g, c in raw_candidates.items() if g in positions and valid_global_id(g)}

    # Space boxes in the GLB frame: same axis swap and the same recentring offset as the meshes.
    space_boxes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for gid, (lo, hi) in space_raw.items():
        box = (lo - off, hi - off)
        if max(np.abs(box[0]).max(), np.abs(box[1]).max()) > COORD_LIMIT:
            out_of_range.append(gid)
            continue
        space_boxes[gid] = box

    issues = run_qa(info, candidates, report)
    if out_of_range:
        issues.append(QaIssue("IFC_COORDINATES_OUT_OF_RANGE", "Error",
                              f"{len(out_of_range)} element(s) lie more than {int(COORD_LIMIT)} m from the model centre.",
                              out_of_range[:MAX_IDS]))
    dupes = duplicate_global_ids(info)
    if dupes:
        issues.append(QaIssue("IFC_DUPLICATE_GLOBALID", "Warning",
                              f"{len(dupes)} GlobalId(s) are used more than once; only the first occurrence is kept.",
                              dupes[:MAX_IDS]))
    result = outcome(issues)

    materials_used: dict[str, set[str]] = {}
    by_el = {e.global_id: e for e in info.elements}
    for m in meshes:
        if m.material_key:
            materials_used.setdefault(m.material_key, set()).update(by_el[m.global_id].material_names)

    space_storey: dict[str, str | None] = {}
    for sp in info.spaces:
        space_storey.setdefault(sp.global_id, sp.storey_id)
    storey_by_gid: dict[str, str] = {}
    for st in info.storeys:
        storey_by_gid.setdefault(st.ifc_global_id, st.id)
    extra_ids: dict[str, tuple[str, str | None]] = {}

    def note(gid: str) -> None:
        if gid in node_map or gid in extra_ids:
            return
        if gid in space_storey:
            extra_ids[gid] = ("IfcSpace", space_storey[gid])
        elif gid in storey_by_gid:
            extra_ids[gid] = ("IfcBuildingStorey", storey_by_gid[gid])
        elif gid in by_el:
            extra_ids[gid] = (by_el[gid].ifc_class, by_el[gid].storey_id)

    for gid in space_storey:
        note(gid)
    for gid in candidates:
        note(gid)
    for i in issues:
        for gid in i.ifc_global_ids:
            note(gid)

    qa_ids = [g for i in issues for g in i.ifc_global_ids]
    geo_md = geometry_metadata(info, info.storeys, node_map, extra_ids, origin_offset=offset,
                               candidate_ids=list(candidates), qa_ids=qa_ids)
    bld_md = building_metadata(info, candidates, positions, materials_used, issues, claim.source_hash, rotations,
                               space_boxes=space_boxes, node_map=node_map)

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
