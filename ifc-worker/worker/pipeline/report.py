from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GeometryReport:
    missing_body: list[tuple[str, str]] = field(default_factory=list)  # (global_id, ifc_class)
    nonstandard_context: list[str] = field(default_factory=list)  # global ids
    triangles_per_storey: dict[str, int] = field(default_factory=dict)
    unmapped_materials: list[str] = field(default_factory=list)
