import json
from pathlib import Path
from typing import Any

import ifcopenshell

from app.schemas.pccc import (
    BimElement,
    BimInspectionResponse,
    BimSource,
    BuildingAnalysisInput,
    BuildingInfo,
    FloorInput,
    SpaceInput,
)


VISUAL_ONLY_SUFFIXES = {".glb", ".pdf", ".png", ".jpg", ".jpeg"}
SUPPORTED_SUFFIXES = {".ifc", ".gltf", *VISUAL_ONLY_SUFFIXES}


def inspect_bim_upload(filename: str, content: bytes, max_bytes: int) -> BimInspectionResponse:
    if len(content) > max_bytes:
        raise ValueError("BIM upload exceeds the maximum allowed size")
    suffix = Path(filename).suffix.lower()
    if suffix == ".rvt":
        raise ValueError("RVT is not supported. Export the model to IFC or GLB/GLTF first.")
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError("Unsupported BIM type. Use IFC, GLB/GLTF, PDF, PNG or JPG.")
    if suffix == ".ifc":
        return _inspect_ifc(filename, content)
    if suffix == ".gltf":
        return _inspect_gltf(filename, content)
    return _visual_reference_response(filename, suffix)


def _base_building(filename: str, suffix: str) -> BuildingAnalysisInput:
    return BuildingAnalysisInput(
        building=BuildingInfo(name=Path(filename).stem),
        source=BimSource(filename=filename, file_type=suffix.removeprefix(".").upper()),
    )


def _visual_reference_response(filename: str, suffix: str) -> BimInspectionResponse:
    return BimInspectionResponse(
        building=_base_building(filename, suffix),
        warnings=["This file is accepted as a visual reference only."],
        missing_data=["No structured BIM elements were extracted from the visual reference."],
    )


def _inspect_gltf(filename: str, content: bytes) -> BimInspectionResponse:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("GLTF must contain valid UTF-8 JSON") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("nodes", []), list):
        raise ValueError("GLTF must contain a nodes array")
    building = _base_building(filename, ".gltf")
    for index, node in enumerate(payload["nodes"]):
        if not isinstance(node, dict):
            continue
        name = str(node.get("name") or f"node-{index}")
        building.elements.append(
            BimElement(
                id=str(node.get("extras", {}).get("id") or f"node-{index}"),
                element_type=_classify_element(name),
                name=name,
                properties=_primitive_properties(node.get("extras")),
            )
        )
    missing = [] if building.elements else ["The GLTF contains no readable nodes."]
    return BimInspectionResponse(building=building, missing_data=missing)


def _inspect_ifc(filename: str, content: bytes) -> BimInspectionResponse:
    try:
        model = ifcopenshell.file.from_string(content.decode("utf-8"))
    except (UnicodeDecodeError, RuntimeError) as error:
        raise ValueError("IFC could not be parsed") from error
    building_entity = next(iter(model.by_type("IfcBuilding")), None)
    building = _base_building(filename, ".ifc")
    if building_entity and getattr(building_entity, "Name", None):
        building.building.name = str(building_entity.Name)
    storey_ids: set[str] = set()
    for index, storey in enumerate(model.by_type("IfcBuildingStorey")):
        storey_id = str(getattr(storey, "GlobalId", None) or f"storey-{index}")
        storey_ids.add(storey_id)
        building.floors.append(
            FloorInput(
                id=storey_id,
                number=index,
                name=str(getattr(storey, "Name", None) or f"Storey {index}"),
                elevation_meters=_as_float(getattr(storey, "Elevation", None)),
            )
        )
    floor_by_id = {floor.id: floor for floor in building.floors}
    for index, space in enumerate(model.by_type("IfcSpace")):
        floor_id = _container_id(space, storey_ids)
        if floor_id in floor_by_id:
            floor_by_id[floor_id].spaces.append(
                SpaceInput(
                    id=str(getattr(space, "GlobalId", None) or f"space-{index}"),
                    name=str(getattr(space, "Name", None) or f"Space {index}"),
                )
            )
    for index, product in enumerate(model.by_type("IfcProduct")):
        if product.is_a("IfcSpace") or product.is_a("IfcBuildingStorey"):
            continue
        entity_name = product.is_a()
        name = str(getattr(product, "Name", None) or entity_name)
        element_type = _ifc_element_type(entity_name, name)
        if element_type == "other":
            continue
        building.elements.append(
            BimElement(
                id=str(getattr(product, "GlobalId", None) or f"element-{index}"),
                element_type=element_type,
                name=name,
                floor_id=_container_id(product, storey_ids),
                properties={"ifc_type": entity_name},
            )
        )
    missing = []
    if not building.floors:
        missing.append("No IFC building storeys were found.")
    if not building.elements:
        missing.append("No recognized PCCC-relevant IFC elements were found.")
    return BimInspectionResponse(building=building, missing_data=missing)


def _container_id(product: Any, storey_ids: set[str]) -> str | None:
    for relation in getattr(product, "ContainedInStructure", []) or []:
        structure = getattr(relation, "RelatingStructure", None)
        structure_id = getattr(structure, "GlobalId", None)
        if structure_id and str(structure_id) in storey_ids:
            return str(structure_id)
    return None


def _ifc_element_type(entity_name: str, name: str) -> str:
    if entity_name == "IfcDoor":
        return "door"
    if entity_name == "IfcStair":
        return "stair"
    return _classify_element(f"{entity_name} {name}")


def _classify_element(value: str) -> str:
    lowered = value.casefold()
    rules = (
        ("fire door", "fire_door"), ("cửa chống cháy", "fire_door"),
        ("exit sign", "exit_sign"), ("biển thoát", "exit_sign"),
        ("emergency light", "emergency_light"), ("đèn sự cố", "emergency_light"),
        ("extinguisher", "extinguisher"), ("bình chữa cháy", "extinguisher"),
        ("hydrant", "hydrant"), ("họng nước", "hydrant"),
        ("sprinkler", "sprinkler"), ("detector", "detector"),
        ("corridor", "corridor"), ("hallway", "corridor"), ("hành lang", "corridor"),
        ("stair", "stair"), ("cầu thang", "stair"),
        ("exit", "exit"), ("egress", "exit"), ("lối thoát", "exit"),
    )
    return next((element_type for keyword, element_type in rules if keyword in lowered), "other")


def _primitive_properties(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any) -> float | None:
    return float(value) if value is not None else None
