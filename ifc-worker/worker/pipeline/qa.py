from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from worker.pipeline.classify import Candidate
from worker.pipeline.extract import IfcModelInfo
from worker.pipeline.report import GeometryReport

Severity = Literal["Info", "Warning", "Error", "Critical"]
MAX_IDS = 100
TRIANGLE_BUDGET = 150_000
_BLOCKING_PREFIXES = ("IfcWall", "IfcSlab", "IfcDoor", "IfcStair")


@dataclass
class QaIssue:
    code: str
    severity: Severity
    message: str
    ifc_global_ids: list[str] = field(default_factory=list)


def run_qa(
    info: IfcModelInfo,
    candidates: dict[str, Candidate],
    geometry_report: GeometryReport | None,
) -> list[QaIssue]:
    issues: list[QaIssue] = []

    def add(code, sev, msg, ids=None):
        issues.append(QaIssue(code, sev, msg, list(ids or [])[:MAX_IDS]))

    has_door = any(e.ifc_class == "IfcDoor" for e in info.elements)
    if not has_door and not info.spaces:
        add("IFC_NOT_ARCHITECTURAL", "Error", "Model has no doors and no spaces; it does not look architectural.")
    if not info.storeys:
        add("IFC_NO_STOREYS", "Error", "Model has no IfcBuildingStorey.")
    if not info.spaces:
        add("IFC_NO_SPACES", "Error", "Model has no IfcSpace.")
    unnamed = [s.global_id for s in info.spaces if not (s.name or s.long_name)]
    if unnamed:
        add("IFC_SPACE_UNNAMED", "Warning", f"{len(unnamed)} space(s) have no name.", unnamed)

    keys = [c.catalog_key for c in candidates.values()]
    if "door.exit" not in keys:
        add("IFC_EXIT_UNKNOWN", "Warning", "No exit door could be identified.")
    if not any(k.startswith(("extinguisher.", "alarm.", "suppression.")) for k in keys):
        add("IFC_NO_FIRE_EQUIPMENT", "Warning", "No fire equipment found in the model.")
    if not any(k.startswith("water.") for k in keys):
        add("IFC_NO_WATER_SOURCE", "Warning", "No water source found in the model.")

    low = [gid for gid, c in candidates.items() if c.confidence < 0.9]
    if low:
        add("IFC_LOW_CONFIDENCE_DEVICE", "Warning", f"{len(low)} device(s) need confirmation.", low)

    def is_default_mass(e) -> bool:
        if e.ifc_class != "IfcBuildingElementProxy":
            return False
        vals = [e.name or ""] + list(e.material_names)
        return any(v.strip().lower() == "default mass" for v in vals)

    mass = [e.global_id for e in info.elements if is_default_mass(e)]
    if mass:
        add("IFC_DEFAULT_MASS_PRESENT", "Info", f"{len(mass)} Default Mass proxy element(s) will be skipped.", mass)

    if geometry_report is not None:
        blocking = [g for g, c in geometry_report.missing_body if c.startswith(_BLOCKING_PREFIXES)]
        other = [g for g, c in geometry_report.missing_body if not c.startswith(_BLOCKING_PREFIXES)]
        if blocking:
            add("IFC_NO_BODY_GEOMETRY", "Error",
                f"{len(blocking)} wall/slab/door/stair element(s) have no Body geometry.", blocking)
        if other:
            add("IFC_NO_BODY_GEOMETRY", "Warning", f"{len(other)} element(s) have no Body geometry.", other)
        if geometry_report.nonstandard_context:
            add("IFC_BODY_NONSTANDARD_CONTEXT", "Info", "Body geometry found outside the Model context.",
                geometry_report.nonstandard_context)
        for storey, tris in sorted(geometry_report.triangles_per_storey.items()):
            if tris > TRIANGLE_BUDGET:
                add("IFC_TRIANGLE_BUDGET_EXCEEDED", "Warning",
                    f"Storey {storey} has {tris} triangles (budget {TRIANGLE_BUDGET}).")
        if geometry_report.unmapped_materials:
            names = ", ".join(sorted(set(geometry_report.unmapped_materials))[:20])
            add("IFC_UNMAPPED_MATERIAL", "Info", f"Unmapped materials: {names}.")
    return issues


def outcome(issues: list[QaIssue]) -> Literal["Passed", "Failed"]:
    return "Failed" if any(i.severity in ("Error", "Critical") for i in issues) else "Passed"
