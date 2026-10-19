from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as uel
import ifcopenshell.util.unit as uunit

_SKIP = (
    "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcProject", "IfcSpace",
    "IfcOpeningElement", "IfcAnnotation",
)


@dataclass
class Storey:
    id: str
    name: str
    elevation_m: float
    ifc_global_id: str


@dataclass
class Element:
    global_id: str
    ifc_class: str
    name: str | None
    long_name: str | None
    object_type: str | None
    type_name: str | None
    predefined_type: str | None
    storey_id: str | None
    psets: dict = field(default_factory=dict)
    material_names: list[str] = field(default_factory=list)
    type_class: str | None = None  # e.g. IfcSanitaryTerminalType (IFC2X3 FlowTerminal hint)


@dataclass
class SpaceInfo:
    global_id: str
    name: str | None
    long_name: str | None
    category: str | None
    storey_id: str | None


@dataclass
class IfcModelInfo:
    schema: str
    app: str | None
    unit_scale: float
    storeys: list[Storey] = field(default_factory=list)
    spaces: list[SpaceInfo] = field(default_factory=list)
    elements: list[Element] = field(default_factory=list)


def _check_step_header(path: Path) -> None:
    with open(path, "rb") as fh:
        head = fh.read(256)
    head = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not head.startswith(b"ISO-10303-21;"):
        raise ValueError("IFC_UNSUPPORTED_FORMAT")


def _storey_of(entity, storey_ids: dict[int, str]) -> str | None:
    cur = entity
    for _ in range(16):
        parent = uel.get_container(cur) or uel.get_aggregate(cur)
        if parent is None:
            return None
        if parent.is_a("IfcBuildingStorey"):
            return storey_ids.get(parent.id())
        cur = parent
    return None


def _material_names(entity) -> list[str]:
    try:
        mat = uel.get_material(entity, should_skip_usage=True)
    except Exception:
        return []
    if mat is None:
        return []
    names: list[str] = []

    def add(m):
        n = getattr(m, "Name", None) if m is not None else None
        if n:
            names.append(str(n))

    if mat.is_a("IfcMaterial"):
        add(mat)
    elif mat.is_a("IfcMaterialLayerSet"):
        for layer in mat.MaterialLayers or []:
            add(layer.Material)
    elif mat.is_a("IfcMaterialConstituentSet"):
        for c in mat.MaterialConstituents or []:
            add(c.Material)
    elif mat.is_a("IfcMaterialProfileSet"):
        for p in mat.MaterialProfiles or []:
            add(p.Material)
    elif mat.is_a("IfcMaterialList"):
        for m in mat.Materials or []:
            add(m)
    return names


def _predefined(entity) -> str | None:
    pt = getattr(entity, "PredefinedType", None)
    return str(pt) if pt else None


def read_model(path: Path) -> tuple[ifcopenshell.file, IfcModelInfo]:
    path = Path(path)
    _check_step_header(path)
    try:
        model = ifcopenshell.open(str(path))
    except Exception as exc:
        raise ValueError("IFC_UNSUPPORTED_FORMAT") from exc

    scale = float(uunit.calculate_unit_scale(model))
    app = None
    try:
        app = model.header.file_name.originating_system or None
    except Exception:
        pass

    raw = []
    for s in model.by_type("IfcBuildingStorey"):
        raw.append((round((s.Elevation or 0.0) * scale, 6), s))
    raw.sort(key=lambda t: (t[0], t[1].id()))
    below = [t for t in raw if t[0] < 0][::-1]  # nearest ground first -> B1
    above = [t for t in raw if t[0] >= 0]
    ids: dict[int, str] = {}
    for n, (_, s) in enumerate(below, 1):
        ids[s.id()] = f"B{n}"
    for n, (_, s) in enumerate(above, 1):
        ids[s.id()] = f"L{n}"
    storeys = [Storey(ids[s.id()], s.Name or ids[s.id()], elev, s.GlobalId) for elev, s in raw]

    spaces = [
        SpaceInfo(sp.GlobalId, sp.Name, sp.LongName, None, _storey_of(sp, ids))
        for sp in model.by_type("IfcSpace")
    ]

    elements: list[Element] = []
    for e in model.by_type("IfcProduct"):
        if any(e.is_a(c) for c in _SKIP):
            continue
        try:
            t = uel.get_type(e)
        except Exception:
            t = None
        try:
            psets = uel.get_psets(e, psets_only=True)
        except Exception:
            psets = {}
        elements.append(
            Element(
                global_id=e.GlobalId,
                ifc_class=e.is_a(),
                name=e.Name,
                long_name=getattr(e, "LongName", None),
                object_type=getattr(e, "ObjectType", None),
                type_name=t.Name if t is not None else None,
                predefined_type=_predefined(e) or (_predefined(t) if t is not None else None),
                storey_id=_storey_of(e, ids),
                psets=psets,
                material_names=_material_names(e),
                type_class=t.is_a() if t is not None else None,
            )
        )
    return model, IfcModelInfo(model.schema, app, scale, storeys, spaces, elements)
