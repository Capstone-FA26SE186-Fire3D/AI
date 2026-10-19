from pathlib import Path

import ifcopenshell
import ifcopenshell.api
import numpy as np
import pytest
import trimesh

from tests._helpers import glb_json
from tests.fixtures.make_ifc import build_sample_ifc
from worker.pipeline.classify import load_keywords
from worker.pipeline.extract import read_model
from worker.pipeline.geometry import COORDINATE_TRANSFORM, extract_meshes, ifc_to_glb_point
from worker.pipeline.glb import build_glb

CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture(scope="module")
def materials():
    return load_keywords(CONFIG / "materials.v1.json")


def test_axis_conversion():
    assert tuple(ifc_to_glb_point((1, 2, 3))) == (1, 3, -2)
    m = np.array(COORDINATE_TRANSFORM(0.001), dtype=float).reshape(4, 4, order="F")
    out = m @ np.array([1000.0, 2000.0, 3000.0, 1.0])
    assert np.allclose(out[:3], (1, 3, -2))
    assert np.allclose(m[3], (0, 0, 0, 1))


def test_extract_meshes_sample(tmp_path: Path, materials):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    model, info = read_model(tmp_path / "s.ifc")
    meshes, report = extract_meshes(model, info, materials)
    by_id = {m.global_id: m for m in meshes}
    for key in ("wall_1", "door_ext", "door_int", "door_exit", "stair_1", "ext_1", "sink_1", "slab_l2"):
        assert ids[key] in by_id, key
    assert ids["space_101"] not in by_id and ids["space_201"] not in by_id
    # vertices are already metres (no second unit scaling): wall is 5 m long
    wall = by_id[ids["wall_1"]]
    assert wall.vertices[:, 0].max() == pytest.approx(5.0, abs=1e-3)
    # Y-up: wall height 3 m on Y, IFC +y (thickness) becomes GLB -z
    assert wall.vertices[:, 1].max() == pytest.approx(3.0, abs=1e-3)
    assert wall.vertices[:, 2].min() == pytest.approx(-0.2, abs=1e-3)
    slab = by_id[ids["slab_l2"]]
    assert slab.storey_id == "L2"
    assert slab.vertices[:, 1].min() >= 3.4
    assert slab.material_key == "floor.tile"
    assert wall.material_key == "wall.plaster"
    assert wall.faces.shape[1] == 3 and wall.faces.max() < len(wall.vertices)
    assert report.missing_body == []
    assert report.triangles_per_storey["L1"] > 0 and report.triangles_per_storey["L2"] > 0


def test_runtime_filter_and_missing_body(tmp_path: Path, materials):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    f = ifcopenshell.open(str(tmp_path / "s.ifc"))
    run = ifcopenshell.api.run
    body = [c for c in f.by_type("IfcGeometricRepresentationSubContext") if c.ContextIdentifier == "Body"][0]
    storey = f.by_guid(ids["L1"])
    pipe = run("root.create_entity", f, ifc_class="IfcPipeSegment", name="Pipe")
    run("geometry.assign_representation", f, product=pipe,
        representation=run("geometry.add_wall_representation", f, context=body, length=1.0, height=0.1, thickness=0.1))
    run("spatial.assign_container", f, products=[pipe], relating_structure=storey)
    plan = run("context.add_context", f, context_type="Plan")
    axis = run("context.add_context", f, context_type="Plan", context_identifier="Axis", target_view="GRAPH_VIEW", parent=plan)
    bare = run("root.create_entity", f, ifc_class="IfcWall", name="Axis only")
    curve = f.createIfcPolyline([f.createIfcCartesianPoint((0.0, 0.0)), f.createIfcCartesianPoint((1000.0, 0.0))])
    run("geometry.assign_representation", f, product=bare,
        representation=f.createIfcShapeRepresentation(axis, "Axis", "Curve2D", [curve]))
    run("spatial.assign_container", f, products=[bare], relating_structure=storey)
    f.write(str(tmp_path / "s2.ifc"))

    model, info = read_model(tmp_path / "s2.ifc")
    meshes, report = extract_meshes(model, info, materials)
    got = {m.global_id for m in meshes}
    assert pipe.GlobalId not in got
    assert bare.GlobalId not in got
    assert (bare.GlobalId, "IfcWall") in report.missing_body
    assert all(g != pipe.GlobalId for g, _ in report.missing_body)


def test_glb_top_level_nodes_are_storeys(tmp_path: Path, materials):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    model, info = read_model(tmp_path / "s.ifc")
    meshes, _ = extract_meshes(model, info, materials)
    out = tmp_path / "preview.glb"
    node_map = build_glb(meshes, info.storeys, out)
    assert node_map[ids["wall_1"]] == ids["wall_1"]

    scene = trimesh.load(str(out), file_type="glb")
    root = scene.graph.base_frame
    assert sorted(scene.graph.transforms.children[root]) == ["L1", "L2"]
    assert ids["slab_l2"] in scene.graph.transforms.children["L2"]
    assert ids["wall_1"] in scene.graph.transforms.children["L1"]

    j = glb_json(out.read_bytes())
    assert not j.get("images") and not j.get("textures")
    nodes = {n.get("name"): n for n in j["nodes"]}
    wall_node = nodes[ids["wall_1"]]
    assert wall_node["extras"]["ifcGlobalId"] == ids["wall_1"]
    assert wall_node["extras"]["ifcClass"] == "IfcWall"
    assert "libraryKey" in wall_node["extras"]
    mesh = j["meshes"][wall_node["mesh"]]
    assert mesh["extras"]["ifcGlobalId"] == ids["wall_1"]
    assert "TEXCOORD_0" in mesh["primitives"][0]["attributes"]


def test_glb_without_storeys_uses_unassigned(tmp_path: Path, materials):
    build_sample_ifc(tmp_path / "s.ifc", with_storeys=False)
    model, info = read_model(tmp_path / "s.ifc")
    meshes, report = extract_meshes(model, info, materials)
    assert meshes
    out = tmp_path / "preview.glb"
    build_glb(meshes, info.storeys, out)
    scene = trimesh.load(str(out), file_type="glb")
    assert scene.graph.transforms.children[scene.graph.base_frame] == ["unassigned"]
    assert set(report.triangles_per_storey) == {"unassigned"}


def test_glb_omits_null_library_key_and_unknown_storey_is_unassigned(tmp_path: Path, materials):
    from worker.pipeline.geometry import ElementMesh

    ids = build_sample_ifc(tmp_path / "s.ifc")
    model, info = read_model(tmp_path / "s.ifc")
    for e in info.elements:
        if e.global_id == ids["sink_1"]:
            e.storey_id = "ZZ"  # storey not among info.storeys
    meshes, report = extract_meshes(model, info, materials)
    sink = [m for m in meshes if m.global_id == ids["sink_1"]][0]
    assert sink.material_key is None
    assert report.triangles_per_storey["unassigned"] == len(sink.faces)
    out = tmp_path / "p.glb"
    build_glb(meshes, info.storeys, out)
    j = glb_json(out.read_bytes())
    nodes = {n.get("name"): n for n in j["nodes"]}
    assert "libraryKey" not in nodes[ids["sink_1"]]["extras"]
    assert "libraryKey" not in j["meshes"][nodes[ids["sink_1"]]["mesh"]]["extras"]
    root_children = [j["nodes"][i]["name"] for i in nodes["world"]["children"]]
    assert sorted(root_children) == ["L1", "L2", "unassigned"]
    unassigned_children = [j["nodes"][i]["name"] for i in nodes["unassigned"]["children"]]
    assert unassigned_children == [ids["sink_1"]]


def test_coordinate_transform_with_offset():
    m = np.array(COORDINATE_TRANSFORM(0.001, (10.0, 0.0, -5.0)), dtype=float).reshape(4, 4, order="F")
    out = m @ np.array([1000.0, 2000.0, 3000.0, 1.0])
    assert np.allclose(out[:3], (1 - 10, 3, -2 + 5))
