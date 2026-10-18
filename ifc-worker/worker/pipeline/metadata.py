"""fet3d.editor/1 geometry metadata and fet3d.building/1 building metadata."""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Iterable
from pathlib import Path

import jsonschema
import numpy as np

from worker.pipeline.classify import Candidate
from worker.pipeline.extract import IfcModelInfo, Storey
from worker.pipeline.geometry import COORDINATE_TRANSFORM
from worker.pipeline.qa import QaIssue

log = logging.getLogger("ifc-worker")

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
GLOBAL_ID = re.compile(r"^[0-9A-Za-z_$]{22}$")
_SEMANTIC_TYPE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,99}$")
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
SYNTHETIC_FLOOR = {"id": "L1", "name": "Unassigned", "elevationMeters": 0, "transform": IDENTITY}
MIN_EXTENT = 0.01
MAX_SEMANTIC = 100_000
MAX_INTERACTABLES = 5000


@lru_cache(maxsize=None)
def _schema(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _validate(doc: dict, name: str) -> None:
    jsonschema.validate(doc, _schema(name), format_checker=jsonschema.FormatChecker())


def valid_global_id(gid: str | None) -> bool:
    return bool(gid) and GLOBAL_ID.match(gid) is not None


def candidate_id(gid: str) -> str:
    """Stable interactable id "ifc:<GlobalId>". The schema id pattern does not allow "$" (valid in
    GlobalIds), so it is replaced by "-", which GlobalIds never contain (the mapping stays injective)."""
    return "ifc:" + gid.replace("$", "-")


def _num(v: float) -> float:
    r = round(float(v), 6)
    return 0.0 if r == 0 else r


def floors_of(storeys: list[Storey]) -> list[dict]:
    if not storeys:
        return [dict(SYNTHETIC_FLOOR, transform=list(IDENTITY))]
    floors = []
    seen: set[str] = set()
    for s in storeys:
        t = list(IDENTITY)
        t[13] = _num(s.elevation_m)
        floor = {"id": s.id, "name": (s.name or s.id)[:255], "elevationMeters": _num(s.elevation_m), "transform": t}
        if valid_global_id(s.ifc_global_id) and s.ifc_global_id not in seen:  # BE rejects duplicate GlobalIds
            seen.add(s.ifc_global_id)
            floor["ifcGlobalId"] = s.ifc_global_id
        floors.append(floor)
    return floors


def _resolver(info: IfcModelInfo, storeys: list[Storey]):
    """Returns (floor_id_for(storey_id), elevation_of(floor_id)). Missing/unknown storey -> lowest floor."""
    floors = floors_of(storeys)
    ids = {f["id"] for f in floors}
    lowest = floors[0]["id"]  # storeys come sorted by elevation
    elev = {f["id"]: float(f["elevationMeters"]) for f in floors}

    def floor_for(storey_id: str | None) -> str:
        return storey_id if storey_id in ids else lowest

    return floor_for, elev


_ANCHOR_CLASSES = ("IfcDoor", "IfcStair", "IfcStairFlight", "IfcRamp", "IfcRampFlight")


def geometry_metadata(
    info: IfcModelInfo,
    storeys: list[Storey],
    node_map: dict[str, str],
    extra_ids: dict[str, tuple[str, str | None]],
    *,
    origin_offset: tuple[float, float, float] = (0.0, 0.0, 0.0),
    candidate_ids: Iterable[str] = (),
    qa_ids: Iterable[str] = (),
) -> dict:
    """`extra_ids`: GlobalId -> (semanticType, storey id or None) for ids without a GLB node
    (spaces -> nodeId "space:<id>", anything else -> "meta:<id>").

    Entries are ordered by importance before the 100000 cap (BE also uses only the first 5000 as
    anchors): candidates, doors/stairs/ramps, spaces, QA ids, then every other node.
    `origin_offset` is the GLB-space shift already subtracted from the meshes (recentring)."""
    floor_for, _ = _resolver(info, storeys)
    by_el = {e.global_id: e for e in info.elements}
    spaces = {s.global_id: s for s in info.spaces}
    cands = set(candidate_ids)
    qas = set(qa_ids)

    entries: list[tuple[str, str, str, str | None]] = []
    for gid, node in node_map.items():
        el = by_el.get(gid)
        sem = el.ifc_class if el else (extra_ids.get(gid, ("IfcProduct", None))[0])
        storey = el.storey_id if el else extra_ids.get(gid, (None, None))[1]
        entries.append((gid, node, sem, storey))
    for gid, (sem, storey) in extra_ids.items():
        if gid in node_map:
            continue
        if gid in spaces:
            entries.append((gid, f"space:{gid}", sem or "IfcSpace", storey or spaces[gid].storey_id))
        else:
            el = by_el.get(gid)
            entries.append((gid, f"meta:{gid}", sem or (el.ifc_class if el else "IfcProduct"),
                            storey or (el.storey_id if el else None)))

    def rank(entry) -> int:
        gid, _, sem, _ = entry
        if gid in cands:
            return 0
        if sem.startswith(_ANCHOR_CLASSES):
            return 1
        if gid in spaces:
            return 2
        if gid in qas:
            return 3
        return 4

    entries.sort(key=rank)  # stable

    mapping: list[dict] = []
    seen_gids: set[str] = set()
    seen_nodes: set[str] = set()
    skipped = 0
    for gid, node, sem, storey in entries:
        if gid in seen_gids:
            continue
        if (not valid_global_id(gid) or node in seen_nodes or len(node) > 256
                or not _SEMANTIC_TYPE.match(sem or "") or len(mapping) >= MAX_SEMANTIC):
            skipped += 1
            continue
        seen_gids.add(gid)
        seen_nodes.add(node)
        mapping.append({"ifcGlobalId": gid, "nodeId": node, "floorId": floor_for(storey), "semanticType": sem})
    if skipped:
        log.warning("semanticMapping: skipped %d invalid, duplicate or over-cap entries", skipped)

    doc = {
        "schemaVersion": "fet3d.editor/1",
        "units": "m",
        "upAxis": "Y",
        "handedness": "right",
        "coordinateTransform": COORDINATE_TRANSFORM(info.unit_scale, origin_offset),
        "floors": floors_of(storeys),
        "semanticMapping": mapping,
    }
    _validate(doc, "geometry-metadata.schema.json")
    return doc


def _pset_value(psets: dict, key: str):
    for props in (psets or {}).values():
        if isinstance(props, dict) and key in props:
            return props[key]
    return None


def _bool_or_none(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1", ".t.")
    return bool(v)


def building_metadata(
    info: IfcModelInfo,
    candidates: dict[str, Candidate],
    positions: dict[str, tuple[np.ndarray, np.ndarray]],
    materials_used: dict[str, set[str]],
    issues: list[QaIssue],
    source_sha256: str,
    rotations: dict[str, float] | None = None,
) -> dict:
    """`positions`: GlobalId -> (min, max) GLB-space bbox in metres. A degenerate box (min == max)
    is a placement-only point: the interactable gets a position but no bbox."""
    floor_for, elev = _resolver(info, info.storeys)
    by_el = {e.global_id: e for e in info.elements}
    rotations = rotations or {}

    source = {"role": "architecture", "sha256": source_sha256, "schema": info.schema}
    if info.app:
        source["app"] = info.app

    storeys, seen_storey = [], set()
    for s in info.storeys:
        item = {"id": s.id, "name": s.name, "elevation": _num(s.elevation_m)}
        if s.ifc_global_id not in seen_storey:
            seen_storey.add(s.ifc_global_id)
            item["ifcGlobalId"] = s.ifc_global_id
        storeys.append(item)
    spaces, seen_space = [], set()
    for s in info.spaces:
        if s.global_id in seen_space:  # keep first; BE rejects duplicates (QA IFC_DUPLICATE_GLOBALID)
            continue
        seen_space.add(s.global_id)
        spaces.append({"ifcGlobalId": s.global_id, "name": s.name, "longName": s.long_name,
                       "category": s.category, "storey": floor_for(s.storey_id)})
    spaces = spaces[:20000]

    portals = []
    for e in info.elements:
        if not e.ifc_class.startswith("IfcDoor"):
            continue
        cand = candidates.get(e.global_id)
        portals.append({
            "ifcGlobalId": e.global_id, "type": "door",
            "fireExit": _bool_or_none(_pset_value(e.psets, "FireExit")),
            "isExternal": _bool_or_none(_pset_value(e.psets, "IsExternal")),
            "exitInferred": bool(cand and cand.catalog_key == "door.exit" and cand.source == "inferred"),
        })
    portals = portals[:20000]

    interactables = []
    for gid, cand in candidates.items():
        el = by_el.get(gid)
        box = positions.get(gid)
        if el is None or box is None or not valid_global_id(gid):
            continue  # no fabricated geometry
        lo, hi = (np.asarray(b, dtype=float) for b in box)
        floor = floor_for(el.storey_id)
        centre = (lo + hi) / 2.0
        item = {
            "id": candidate_id(gid), "ifcGlobalId": gid, "catalogKey": cand.catalog_key, "source": cand.source,
            "ifcClass": el.ifc_class, "confidence": _num(cand.confidence), "floorId": floor,
            "position": [_num(centre[0]), _num(centre[1] - elev[floor]), _num(centre[2])],
        }
        if gid in rotations:
            item["rotationY"] = _num(rotations[gid])
        size = hi - lo
        if np.any(size > 1e-9):
            # [width (x), depth (z), height (y)]
            item["bbox"] = [_num(max(MIN_EXTENT, size[0])), _num(max(MIN_EXTENT, size[2])),
                            _num(max(MIN_EXTENT, size[1]))]
        interactables.append(item)
        if len(interactables) >= MAX_INTERACTABLES:
            log.warning("interactables truncated at %d", MAX_INTERACTABLES)
            break

    mats = {k: {"libraryKey": k, "ifcNames": sorted(v)} for k, v in sorted(materials_used.items())}
    qa = [{"code": i.code, "severity": i.severity, "elements": list(i.ifc_global_ids)} for i in issues[:5000]]

    doc = {
        "schemaVersion": "fet3d.building/1",
        "sources": [source],
        "units": "m",
        "storeys": storeys,
        "spaces": spaces,
        "portals": portals,
        "interactables": interactables,
        "materials": mats,
        "qaIssues": qa,
    }
    _validate(doc, "building-metadata.schema.json")
    return doc
