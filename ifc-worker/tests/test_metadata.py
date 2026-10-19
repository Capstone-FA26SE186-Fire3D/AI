import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from tests.fixtures.make_ifc import build_sample_ifc
from worker.pipeline.extract import read_model
from worker.pipeline.metadata import building_metadata, geometry_metadata

ROOT = Path(__file__).resolve().parents[1]
GEO_SCHEMA = json.loads((ROOT / "contracts" / "geometry-metadata.schema.json").read_text(encoding="utf-8"))
BLD_SCHEMA = json.loads((ROOT / "contracts" / "building-metadata.schema.json").read_text(encoding="utf-8"))


def test_vendored_schemas_match_rag_api():
    src = ROOT.parent / "rag-api" / "contracts"
    for name in ("geometry-metadata.schema.json", "building-metadata.schema.json"):
        assert json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8")) == \
            json.loads((src / name).read_text(encoding="utf-8"))


def test_geometry_metadata_floors_and_transform(tmp_path: Path):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    node_map = {ids["wall_1"]: ids["wall_1"], ids["slab_l2"]: ids["slab_l2"]}
    extra = {ids["space_201"]: ("IfcSpace", "L2"), ids["door_ext"]: ("IfcDoor", None)}
    md = geometry_metadata(info, info.storeys, node_map, extra)
    jsonschema.validate(md, GEO_SCHEMA)
    assert md["coordinateTransform"] == [0.001, 0, 0, 0, 0, 0, -0.001, 0, 0, 0.001, 0, 0, 0, 0, 0, 1]
    l2 = [f for f in md["floors"] if f["id"] == "L2"][0]
    assert l2["elevationMeters"] == 3.5 and l2["ifcGlobalId"] == ids["L2"]
    assert l2["transform"][13] == 3.5 and l2["transform"][12] == 0 and l2["transform"][14] == 0
    sem = {s["ifcGlobalId"]: s for s in md["semanticMapping"]}
    assert sem[ids["wall_1"]] == {"ifcGlobalId": ids["wall_1"], "nodeId": ids["wall_1"], "floorId": "L1", "semanticType": "IfcWall"}
    assert sem[ids["slab_l2"]]["floorId"] == "L2"
    assert sem[ids["space_201"]]["nodeId"] == f"space:{ids['space_201']}"
    assert sem[ids["door_ext"]]["nodeId"] == f"meta:{ids['door_ext']}"
    assert sem[ids["door_ext"]]["floorId"] == "L1"  # resolved from the element, else lowest floor


def test_geometry_metadata_skips_invalid_global_ids_and_dedupes(tmp_path: Path):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    node_map = {ids["wall_1"]: ids["wall_1"], "bad id!": "bad id!"}
    extra = {ids["wall_1"]: ("IfcWall", "L1"), "short": ("IfcDoor", "L1")}
    md = geometry_metadata(info, info.storeys, node_map, extra)
    jsonschema.validate(md, GEO_SCHEMA)
    gids = [s["ifcGlobalId"] for s in md["semanticMapping"]]
    assert gids == [ids["wall_1"]]


def test_geometry_metadata_no_storeys_synthetic_floor(tmp_path: Path):
    ids = build_sample_ifc(tmp_path / "s.ifc", with_storeys=False)
    _, info = read_model(tmp_path / "s.ifc")
    md = geometry_metadata(info, info.storeys, {ids["wall_1"]: ids["wall_1"]}, {})
    jsonschema.validate(md, GEO_SCHEMA)
    assert md["floors"] == [{"id": "L1", "name": "Unassigned", "elevationMeters": 0,
                             "transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}]
    assert md["semanticMapping"][0]["floorId"] == "L1"


def test_building_metadata_shape(tmp_path: Path):
    from worker.pipeline.classify import Candidate
    from worker.pipeline.qa import QaIssue

    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    cands = {ids["ext_1"]: Candidate("extinguisher.portable", 0.7),
             ids["door_ext"]: Candidate("door.exit", 0.7, "inferred")}
    # extinguisher GLB bbox: x 1.0..1.2, y 0..0.6, z -1.7..-1.5 ; door on L1
    positions = {ids["ext_1"]: (np.array([1.0, 0.0, -1.7]), np.array([1.2, 0.6, -1.5])),
                 ids["door_ext"]: (np.array([5.0, 0.0, -0.1]), np.array([6.0, 2.1, 0.0]))}
    issues = [QaIssue("IFC_LOW_CONFIDENCE_DEVICE", "Warning", "x", [ids["ext_1"]])]
    md = building_metadata(info, cands, positions, {"wall.plaster": {"Plaster"}}, issues, "c" * 64)
    jsonschema.validate(md, BLD_SCHEMA)
    assert md["sources"][0]["sha256"] == "c" * 64 and md["sources"][0]["role"] == "architecture"
    assert md["units"] == "m"
    assert [s["id"] for s in md["storeys"]] == ["L1", "L2"]
    assert {s["ifcGlobalId"] for s in md["spaces"]} == {ids["space_101"], ids["space_201"]}
    ext = [i for i in md["interactables"] if i["ifcGlobalId"] == ids["ext_1"]][0]
    assert ext["id"] == "ifc:" + ids["ext_1"].replace("$", "-")
    assert ext["position"] == pytest.approx([1.1, 0.3, -1.6])
    assert ext["bbox"] == pytest.approx([0.2, 0.2, 0.6])
    assert ext["floorId"] == "L1" and ext["source"] == "ifc"
    door = [p for p in md["portals"] if p["ifcGlobalId"] == ids["door_ext"]][0]
    assert door["type"] == "door" and door["isExternal"] is True and door["exitInferred"] is True
    assert md["materials"]["wall.plaster"] == {"libraryKey": "wall.plaster", "ifcNames": ["Plaster"]}
    assert md["qaIssues"] == [{"code": "IFC_LOW_CONFIDENCE_DEVICE", "severity": "Warning", "elements": [ids["ext_1"]]}]
    assert "revisionId" not in md


def test_building_metadata_position_is_floor_local(tmp_path: Path):
    from worker.pipeline.classify import Candidate

    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    cands = {ids["slab_l2"]: Candidate("item.towel", 0.95)}
    positions = {ids["slab_l2"]: (np.array([0.0, 3.5, -3.0]), np.array([5.0, 3.5, 0.0]))}
    md = building_metadata(info, cands, positions, {}, [], "c" * 64)
    jsonschema.validate(md, BLD_SCHEMA)
    it = md["interactables"][0]
    assert it["floorId"] == "L2"
    assert it["position"] == pytest.approx([2.5, 0.0, -1.5])
    assert it["bbox"] == pytest.approx([5.0, 3.0, 0.01])  # flat height clamped to 0.01


def test_building_metadata_skips_candidates_without_position(tmp_path: Path):
    from worker.pipeline.classify import Candidate

    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    md = building_metadata(info, {ids["sink_1"]: Candidate("water.sink", 0.95)}, {}, {}, [], "c" * 64)
    assert md["interactables"] == []


def test_interactable_id_escapes_dollar(tmp_path: Path):
    from worker.pipeline.classify import Candidate

    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    el = [e for e in info.elements if e.global_id == ids["sink_1"]][0]
    el.global_id = "0eCIdyC_bCfvLYSQc$3LVp"
    md = building_metadata(info, {el.global_id: Candidate("water.sink", 0.95)},
                           {el.global_id: (np.zeros(3), np.ones(3))}, {}, [], "c" * 64)
    jsonschema.validate(md, BLD_SCHEMA)
    it = md["interactables"][0]
    assert it["ifcGlobalId"] == "0eCIdyC_bCfvLYSQc$3LVp"
    assert it["id"] == "ifc:0eCIdyC_bCfvLYSQc-3LVp"


def test_building_metadata_space_bbox_and_stair_portals(tmp_path: Path):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    boxes = {ids["space_201"]: (np.array([1.0, 3.5, -2.5]), np.array([5.0, 6.2, -0.5]))}
    md = building_metadata(info, {}, {}, {}, [], "c" * 64, space_boxes=boxes,
                           node_map={ids["stair_1"]: ids["stair_1"]})
    jsonschema.validate(md, BLD_SCHEMA)
    spaces = {s["ifcGlobalId"]: s for s in md["spaces"]}
    assert spaces[ids["space_201"]]["bbox"] == [[1.0, 3.5, -2.5], [5.0, 6.2, -0.5]]
    assert "bbox" not in spaces[ids["space_101"]]
    stairs = [p for p in md["portals"] if p["type"] == "stair"]
    assert stairs == [{"ifcGlobalId": ids["stair_1"], "type": "stair", "ifcClass": "IfcStair", "floor": "L1"}]


def test_stair_without_glb_node_is_not_a_portal(tmp_path: Path):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    md = building_metadata(info, {}, {}, {}, [], "c" * 64, node_map={ids["wall_1"]: ids["wall_1"]})
    assert [p for p in md["portals"] if p["type"] == "stair"] == []
