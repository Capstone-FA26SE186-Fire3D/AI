import json
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from tests._helpers import glb_json, make_claim
from tests.fixtures.make_ifc import build_sample_ifc
from worker.pipeline.process import UnprocessableIfc, process_ifc

ROOT = Path(__file__).resolve().parents[1]
GEO_SCHEMA = json.loads((ROOT / "contracts" / "geometry-metadata.schema.json").read_text(encoding="utf-8"))
BLD_SCHEMA = json.loads((ROOT / "contracts" / "building-metadata.schema.json").read_text(encoding="utf-8"))


def _run(tmp_path: Path, **kw):
    src = tmp_path / "source.ifc"
    ids = build_sample_ifc(src, **kw)
    out = tmp_path / "out"
    out.mkdir()
    return ids, process_ifc(src, out, make_claim("d" * 64))


def test_process_sample_outputs_pass(tmp_path: Path):
    ids, outputs = _run(tmp_path)
    assert [o.artifact_type for o in outputs] == ["preview_glb", "building_metadata"]
    glb, bld = outputs
    assert (glb.path.name, glb.schema_version, glb.content_type) == ("preview.glb", "fet3d.editor/1", "model/gltf-binary")
    assert (bld.path.name, bld.schema_version, bld.content_type) == \
        ("building_metadata.json", "fet3d.building/1", "application/json")
    assert glb.outcome == bld.outcome == "Passed", glb.issues
    assert glb.issues == bld.issues
    for i in glb.issues:
        assert set(i) <= {"severity", "code", "message", "ifcGlobalIds"}
        assert "ifcGlobalIds" not in i or i["ifcGlobalIds"]
    jsonschema.validate(glb.metadata, GEO_SCHEMA)
    jsonschema.validate(bld.metadata, BLD_SCHEMA)
    assert json.loads(bld.path.read_text(encoding="utf-8")) == bld.metadata
    assert bld.metadata["sources"][0]["sha256"] == "d" * 64
    assert glb_json(glb.path.read_bytes())["asset"]["version"] == "2.0"


def test_geometry_metadata_valid_and_covers_interactables(tmp_path: Path):
    ids, (glb, bld) = _run(tmp_path)
    sem = {s["ifcGlobalId"]: s for s in glb.metadata["semanticMapping"]}
    assert len(sem) == len(glb.metadata["semanticMapping"])
    node_ids = [s["nodeId"] for s in glb.metadata["semanticMapping"]]
    assert len(node_ids) == len(set(node_ids))
    floors = {f["id"] for f in glb.metadata["floors"]}
    assert all(s["floorId"] in floors for s in sem.values())
    assert bld.metadata["interactables"]
    for it in bld.metadata["interactables"]:
        assert it["ifcGlobalId"] in sem
        assert it["floorId"] in floors
    for issue in glb.issues:
        for g in issue.get("ifcGlobalIds", []):
            assert g in sem
    assert sem[ids["space_201"]]["nodeId"] == f"space:{ids['space_201']}"
    assert sem[ids["wall_1"]]["nodeId"] == ids["wall_1"]


def test_door_interactable_has_ifcdoor_class(tmp_path: Path):
    ids, (glb, bld) = _run(tmp_path)
    by = {i["ifcGlobalId"]: i for i in bld.metadata["interactables"]}
    exit_door = by[ids["door_exit"]]
    assert exit_door["catalogKey"] == "door.exit" and exit_door["ifcClass"] == "IfcDoor"
    inferred = by[ids["door_ext"]]
    assert inferred["source"] == "inferred" and inferred["ifcClass"] == "IfcDoor"
    ext = by[ids["ext_1"]]
    ct = glb.metadata["coordinateTransform"]
    shift = np.array([ct[12], ct[13], ct[14]])  # recentring translation (GLB = swap(ifc*s) + shift)
    assert ct[13] == 0
    assert ext["position"] == pytest.approx(list(np.array([1.1, 0.3, -1.6]) + shift), abs=1e-6)
    assert ext["bbox"] == pytest.approx([0.2, 0.2, 0.6], abs=1e-6)
    assert ext["rotationY"] == pytest.approx(0.0)


def test_process_without_spaces_fails(tmp_path: Path):
    _, (glb, bld) = _run(tmp_path, with_spaces=False)
    assert glb.outcome == bld.outcome == "Failed"
    codes = {(i["code"], i["severity"]) for i in glb.issues}
    assert ("IFC_NO_SPACES", "Error") in codes
    assert glb.path.exists()


def test_process_without_storeys_still_valid(tmp_path: Path):
    _, (glb, bld) = _run(tmp_path, with_storeys=False)
    assert glb.outcome == "Failed"
    assert "IFC_NO_STOREYS" in {i["code"] for i in glb.issues}
    jsonschema.validate(glb.metadata, GEO_SCHEMA)
    jsonschema.validate(bld.metadata, BLD_SCHEMA)
    assert [f["id"] for f in glb.metadata["floors"]] == ["L1"]


def test_bad_header_raises_unprocessable(tmp_path: Path):
    src = tmp_path / "x.ifc"
    src.write_text("<html>nope</html>")
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(UnprocessableIfc) as ei:
        process_ifc(src, out, make_claim())
    assert ei.value.issue["code"] == "IFC_UNSUPPORTED_FORMAT"
    assert ei.value.issue["severity"] == "Error"
    assert not (out / "preview.glb").exists()


def test_process_without_any_body_geometry_reports_qa(tmp_path: Path):
    import ifcopenshell

    src = tmp_path / "source.ifc"
    build_sample_ifc(src)
    f = ifcopenshell.open(str(src))
    for prod in f.by_type("IfcProduct"):
        rep = prod.Representation
        if rep is None:
            continue
        for r in rep.Representations:
            r.RepresentationIdentifier = "Axis"
            r.Items = [f.createIfcPolyline([f.createIfcCartesianPoint((0.0, 0.0, 0.0)),
                                            f.createIfcCartesianPoint((1.0, 0.0, 0.0))])]
            r.ContextOfItems = f.createIfcGeometricRepresentationContext(None, "Plan", 2, 1e-5,
                                                                         r.ContextOfItems.WorldCoordinateSystem, None)
    f.write(str(src))
    out = tmp_path / "out"
    out.mkdir()
    glb, bld = process_ifc(src, out, make_claim())
    assert glb.outcome == "Failed"
    no_body = [i for i in glb.issues if i["code"] == "IFC_NO_BODY_GEOMETRY" and i["severity"] == "Error"]
    assert no_body and no_body[0]["ifcGlobalIds"]
    sem = {s["ifcGlobalId"]: s["nodeId"] for s in glb.metadata["semanticMapping"]}
    assert all(sem[g].startswith("meta:") for g in no_body[0]["ifcGlobalIds"])
    assert glb_json(glb.path.read_bytes())["nodes"][0]["name"] == "world"
    jsonschema.validate(bld.metadata, BLD_SCHEMA)


def _shift_storeys(src: Path, dx_mm: float, dy_mm: float) -> None:
    import ifcopenshell

    f = ifcopenshell.open(str(src))
    for st in f.by_type("IfcBuildingStorey"):
        loc = st.ObjectPlacement.RelativePlacement.Location
        x, y, z = loc.Coordinates
        loc.Coordinates = (x + dx_mm, y + dy_mm, z)
    f.write(str(src))


def test_far_away_model_is_recentred(tmp_path: Path):
    import ifcopenshell
    import ifcopenshell.util.placement as pl

    src = tmp_path / "source.ifc"
    ids = build_sample_ifc(src)
    _shift_storeys(src, 5e8, 5e8)  # 500 km east and north (survey coordinates)
    out = tmp_path / "out"
    out.mkdir()
    glb, bld = process_ifc(src, out, make_claim())
    jsonschema.validate(glb.metadata, GEO_SCHEMA)
    jsonschema.validate(bld.metadata, BLD_SCHEMA)
    assert "IFC_COORDINATES_OUT_OF_RANGE" not in {i["code"] for i in glb.issues}
    assert bld.metadata["interactables"]
    for it in bld.metadata["interactables"]:
        assert all(abs(n) < 1e5 for n in it["position"])
        assert all(abs(n) < 1e5 for n in it.get("bbox", []))
        assert all(abs(n) < 100 for n in it["position"])  # the sample is a few metres wide
    # IFC model point -> coordinateTransform == shifted GLB point
    ct = np.array(glb.metadata["coordinateTransform"], dtype=float).reshape(4, 4, order="F")
    f = ifcopenshell.open(str(src))
    world = pl.get_local_placement(f.by_guid(ids["ext_1"]).ObjectPlacement)
    centre_ifc = world @ np.array([100.0, 100.0, 300.0, 1.0])  # local centre of the 200x200x600 mm box
    glb_pt = ct @ centre_ifc
    ext = [i for i in bld.metadata["interactables"] if i["ifcGlobalId"] == ids["ext_1"]][0]
    assert glb_pt[:3] == pytest.approx(ext["position"], abs=1e-3)  # L1 elevation 0
    import trimesh
    scene = trimesh.load(str(glb.path), file_type="glb")
    assert np.abs(scene.bounds).max() < 100


def test_outlier_beyond_range_is_dropped_with_error(tmp_path: Path):
    import ifcopenshell

    src = tmp_path / "source.ifc"
    ids = build_sample_ifc(src)
    base_out = tmp_path / "base"
    base_out.mkdir()
    _, base_bld = process_ifc(src, base_out, make_claim())  # same model, no outlier
    f = ifcopenshell.open(str(src))
    loc = f.by_guid(ids["ext_1"]).ObjectPlacement.RelativePlacement.Location
    loc.Coordinates = (3e8, 1500.0, 0.0)  # 300 km away from everything else
    f.write(str(src))
    out = tmp_path / "out"
    out.mkdir()
    glb, bld = process_ifc(src, out, make_claim())
    err = [i for i in glb.issues if i["code"] == "IFC_COORDINATES_OUT_OF_RANGE"]
    assert err and err[0]["severity"] == "Error" and ids["ext_1"] in err[0]["ifcGlobalIds"]
    assert glb.outcome == "Failed"
    assert ids["ext_1"] not in {i["ifcGlobalId"] for i in bld.metadata["interactables"]}
    for it in bld.metadata["interactables"]:
        assert all(abs(n) <= 1e5 for n in it["position"] + it.get("bbox", []))
    sem = {s["ifcGlobalId"] for s in glb.metadata["semanticMapping"]}
    assert ids["ext_1"] in sem
    # Median recentring: one far outlier must not push the rest of the model out of range.
    assert err[0]["ifcGlobalIds"] == [ids["ext_1"]]
    expected = {i["ifcGlobalId"] for i in base_bld.metadata["interactables"]} - {ids["ext_1"]}
    assert expected
    assert {i["ifcGlobalId"] for i in bld.metadata["interactables"]} == expected


def test_semantic_mapping_puts_candidates_and_qa_ids_first(tmp_path: Path):
    ids, (glb, bld) = _run(tmp_path)
    order = [s["ifcGlobalId"] for s in glb.metadata["semanticMapping"]]
    wall_idx = order.index(ids["wall_1"])
    slab_idx = order.index(ids["slab_l2"])
    important = [i["ifcGlobalId"] for i in bld.metadata["interactables"]]
    important += [g for i in glb.issues for g in i.get("ifcGlobalIds", [])]
    important += [ids["space_101"], ids["space_201"], ids["stair_1"]]
    assert important
    for g in important:
        assert order.index(g) < min(wall_idx, slab_idx), g


def test_duplicate_global_ids_deduped_with_warning(tmp_path: Path):
    import ifcopenshell

    src = tmp_path / "source.ifc"
    ids = build_sample_ifc(src)
    f = ifcopenshell.open(str(src))
    f.by_id(f.by_guid(ids["space_201"]).id()).GlobalId = ids["space_101"]
    f.by_id(f.by_guid(ids["L2"]).id()).GlobalId = ids["L1"]
    f.write(str(src))
    out = tmp_path / "out"
    out.mkdir()
    glb, bld = process_ifc(src, out, make_claim())
    dup = [i for i in glb.issues if i["code"] == "IFC_DUPLICATE_GLOBALID"]
    assert dup and dup[0]["severity"] == "Warning"
    assert set(dup[0]["ifcGlobalIds"]) == {ids["space_101"], ids["L1"]}
    assert [s["ifcGlobalId"] for s in bld.metadata["spaces"]] == [ids["space_101"]]
    floor_gids = [fl.get("ifcGlobalId") for fl in glb.metadata["floors"]]
    assert floor_gids == [ids["L1"], None]
    sem = [s["ifcGlobalId"] for s in glb.metadata["semanticMapping"]]
    assert len(sem) == len(set(sem)) and ids["L1"] in sem and ids["space_101"] in sem
    jsonschema.validate(glb.metadata, GEO_SCHEMA)
    jsonschema.validate(bld.metadata, BLD_SCHEMA)
