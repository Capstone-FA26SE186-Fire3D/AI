import json
from pathlib import Path

import jsonschema
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
    ids, (_, bld) = _run(tmp_path)
    by = {i["ifcGlobalId"]: i for i in bld.metadata["interactables"]}
    exit_door = by[ids["door_exit"]]
    assert exit_door["catalogKey"] == "door.exit" and exit_door["ifcClass"] == "IfcDoor"
    inferred = by[ids["door_ext"]]
    assert inferred["source"] == "inferred" and inferred["ifcClass"] == "IfcDoor"
    ext = by[ids["ext_1"]]
    assert ext["position"] == pytest.approx([1.1, 0.3, -1.6], abs=1e-6)
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
