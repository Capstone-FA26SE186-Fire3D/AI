"""IFC -> triangle meshes in GLB space (metres, Y-up, right-handed)."""
from __future__ import annotations

import logging
import math
import multiprocessing
from dataclasses import dataclass

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement as uplace
import numpy as np

from worker.pipeline.classify import is_mapped, material_key
from worker.pipeline.extract import Element, IfcModelInfo
from worker.pipeline.report import GeometryReport

__all__ = [
    "ElementMesh", "GeometryReport", "COORDINATE_TRANSFORM", "ifc_to_glb_point", "extract_meshes",
    "is_runtime_excluded", "placement_of", "UNASSIGNED", "group_of", "recentre_offset", "extract_space_boxes",
]

log = logging.getLogger("ifc-worker")

UNASSIGNED = "unassigned"

# Docs §5.3 runtime filter: no mesh, metadata kept.
RUNTIME_EXCLUDED = (
    "IfcDuctSegment", "IfcDuctFitting", "IfcPipeSegment", "IfcPipeFitting",
    "IfcCableCarrierSegment", "IfcCableCarrierFitting", "IfcCableSegment", "IfcCableFitting",
    "IfcFlowSegment", "IfcFlowFitting", "IfcAnnotation", "IfcOpeningElement", "IfcSpace",
)
# Model sub-contexts that are not renderable body geometry.
_NON_BODY_IDENTIFIERS = {
    "axis", "footprint", "box", "annotation", "profile", "clearance", "lighting",
    "surveypoints", "reference", "cog",
}


@dataclass
class ElementMesh:
    global_id: str
    ifc_class: str
    storey_id: str | None
    vertices: np.ndarray  # (n, 3) GLB metres, Y-up
    faces: np.ndarray  # (m, 3) int
    material_key: str | None


def ifc_to_glb_point(p) -> tuple[float, float, float]:
    """IFC Z-up axes -> GLB Y-up axes: (x, y, z) -> (x, z, -y). No scaling."""
    x, y, z = (float(v) for v in p)
    return (x, z, -y)


def COORDINATE_TRANSFORM(  # noqa: N802 - contract name
    unit_scale: float, origin_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
) -> list[float]:
    """Column-major 4x4 mapping IFC model coordinates (IFC length units) to GLB metres:
    GLB = axis_swap(ifc * s) - origin_offset (origin_offset is in GLB metres)."""
    s = float(unit_scale)
    ox, oy, oz = (_clean(-float(v)) for v in origin_offset)
    return [s, 0, 0, 0, 0, 0, -s, 0, 0, s, 0, 0, ox, oy, oz, 1]


def _clean(v: float) -> float:
    r = round(v, 6)
    return 0 if r == 0 else r


def group_of(storey_id: str | None, known: set[str]) -> str:
    """Top-level GLB node / triangle-budget key for an element's storey."""
    return storey_id if storey_id in known else UNASSIGNED


def recentre_offset(meshes: list["ElementMesh"], fallback_points: list = ()) -> tuple[float, float, float]:
    """GLB-space origin shift: median of the per-mesh bbox centres on x and z (y stays 0 so elevations
    stay true; the median keeps one far outlier from dragging the whole model out of range); without
    meshes the mean of the fallback points, else 0. Rounded to the millimetre."""
    if meshes:
        centres = [(m.vertices.min(axis=0) + m.vertices.max(axis=0)) / 2.0 for m in meshes]
        c = np.median(np.asarray(centres, dtype=float), axis=0)
    elif len(fallback_points):
        c = np.mean(np.asarray(fallback_points, dtype=float), axis=0)
    else:
        return (0.0, 0.0, 0.0)
    return (round(float(c[0]), 3), 0.0, round(float(c[2]), 3))


def _is_default_mass(el: Element) -> bool:
    if el.ifc_class != "IfcBuildingElementProxy":
        return False
    return any(v.strip().lower() == "default mass" for v in [el.name or ""] + list(el.material_names))


def is_runtime_excluded(entity, el: Element | None = None) -> bool:
    if any(entity.is_a(c) for c in RUNTIME_EXCLUDED):
        return True
    return el is not None and _is_default_mass(el)


def _body_contexts(model: ifcopenshell.file) -> list[int]:
    body, other = [], []
    for ctx in model.by_type("IfcGeometricRepresentationContext"):
        ident = (getattr(ctx, "ContextIdentifier", None) or "").strip().lower()
        ctype = (ctx.ContextType or "").strip().lower()
        if ident == "body":
            body.append(ctx.id())
        elif ctype == "model" and ident not in _NON_BODY_IDENTIFIERS:
            dim = getattr(ctx, "CoordinateSpaceDimension", None)
            if ctx.is_a("IfcGeometricRepresentationSubContext") or dim in (None, 3):
                other.append(ctx.id())
    return body + other  # Body first so it wins over other Model representations


def _has_standard_body(entity) -> bool:
    rep = entity.Representation
    for r in (rep.Representations if rep else []) or []:
        ctx_ident = (getattr(r.ContextOfItems, "ContextIdentifier", None) or "").lower()
        if (r.RepresentationIdentifier or "").lower() == "body" or ctx_ident == "body":
            return True
    return False


def _settings(context_ids: list[int]):
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)  # world coordinates, already converted to metres
    s.set("disable-opening-subtractions", False)
    if context_ids:
        s.set("context-ids", context_ids)
    return s


def placement_of(entity, unit_scale: float) -> tuple[tuple[float, float, float], float] | None:
    """World placement origin in GLB metres and rotation about GLB Y in degrees."""
    if getattr(entity, "ObjectPlacement", None) is None:
        return None
    try:
        m = uplace.get_local_placement(entity.ObjectPlacement)
    except Exception:  # noqa: BLE001
        return None
    origin = ifc_to_glb_point(np.asarray(m[:3, 3], dtype=float) * unit_scale)
    # IFC rotation about +Z maps to rotation about GLB +Y with the same angle
    rot = math.degrees(math.atan2(float(m[1, 0]), float(m[0, 0])))
    return origin, (0.0 if abs(rot) < 1e-9 else rot)


def extract_meshes(
    model: ifcopenshell.file, info: IfcModelInfo, materials: dict
) -> tuple[list[ElementMesh], GeometryReport]:
    report = GeometryReport()
    wanted: dict[str, tuple[Element, object]] = {}
    for el in info.elements:
        try:
            ent = model.by_guid(el.global_id)
        except RuntimeError:
            continue
        if is_runtime_excluded(ent, el) or ent.Representation is None:
            continue
        wanted[el.global_id] = (el, ent)

    meshes: dict[str, ElementMesh] = {}
    if wanted:
        it = ifcopenshell.geom.iterator(
            _settings(_body_contexts(model)), model, multiprocessing.cpu_count(),
            include=[ent for _, ent in wanted.values()],
        )
        if it.initialize():
            while True:
                shape = it.get()
                gid = shape.guid
                if gid in wanted and gid not in meshes:
                    el, _ = wanted[gid]
                    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
                    faces = np.asarray(shape.geometry.faces, dtype=np.int64).reshape(-1, 3)
                    if len(verts) and len(faces):
                        glb = np.column_stack((verts[:, 0], verts[:, 2], -verts[:, 1]))
                        key = material_key(el.material_names, el.ifc_class, el.predefined_type, materials)
                        meshes[gid] = ElementMesh(gid, el.ifc_class, el.storey_id, glb, faces, key)
                if not it.next():
                    break

    unmapped: set[str] = set()
    known = {st.id for st in info.storeys}
    for gid, (el, ent) in wanted.items():
        mesh = meshes.get(gid)
        if mesh is None:
            report.missing_body.append((gid, el.ifc_class))
            continue
        if not _has_standard_body(ent):
            report.nonstandard_context.append(gid)
        if not is_mapped(el.material_names, materials):
            unmapped.update(n for n in el.material_names if not is_mapped([n], materials))
        storey = group_of(mesh.storey_id, known)
        report.triangles_per_storey[storey] = report.triangles_per_storey.get(storey, 0) + len(mesh.faces)
    report.unmapped_materials = sorted(unmapped)
    ordered = [meshes[g] for g in wanted if g in meshes]
    log.info("extracted %d meshes, %d missing body", len(ordered), len(report.missing_body))
    return ordered, report


def extract_space_boxes(
    model: ifcopenshell.file, info: IfcModelInfo
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], list[tuple[str, str]]]:
    """Axis-aligned boxes of IfcSpace volumes in GLB space (metres, Y-up, right-handed, before recentring),
    built with the same settings and axis swap as the element meshes.

    Returns ({global_id: (min, max)}, missing) where `missing` lists (global_id, "IfcSpace") for spaces
    without usable geometry; those get no box (never a fabricated one)."""
    wanted: dict[str, object] = {}
    missing: list[tuple[str, str]] = []
    seen: set[str] = set()
    for sp in info.spaces:
        if sp.global_id in seen:
            continue
        seen.add(sp.global_id)
        try:
            ent = model.by_guid(sp.global_id)
        except RuntimeError:
            ent = None
        if ent is None or ent.Representation is None:
            missing.append((sp.global_id, "IfcSpace"))
            continue
        wanted[sp.global_id] = ent

    boxes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    if wanted:
        it = ifcopenshell.geom.iterator(
            _settings(_body_contexts(model)), model, multiprocessing.cpu_count(), include=list(wanted.values()),
        )
        if it.initialize():
            while True:
                shape = it.get()
                gid = shape.guid
                if gid in wanted and gid not in boxes:
                    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
                    if len(verts) and len(shape.geometry.faces) and np.all(np.isfinite(verts)):
                        glb = np.column_stack((verts[:, 0], verts[:, 2], -verts[:, 1]))
                        lo, hi = glb.min(axis=0), glb.max(axis=0)
                        if np.all(hi - lo > 1e-9):  # a flat or point "volume" is not a usable room box
                            boxes[gid] = (lo, hi)
                if not it.next():
                    break
    missing.extend((g, "IfcSpace") for g in wanted if g not in boxes)
    return boxes, missing
