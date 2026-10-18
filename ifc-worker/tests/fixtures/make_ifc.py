"""Builds a small synthetic IFC4 model (millimetres) for worker tests."""
from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.api


def _local(f, parent, x, y, z):
    return f.createIfcLocalPlacement(
        parent, f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(x), float(y), float(z))))
    )


def _box(f, body, x, y, z, dx, dy, dz):
    """Simple extruded box representation placed at (x, y, z) mm."""
    prof = f.createIfcRectangleProfileDef(
        "AREA", None, f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((dx / 2, dy / 2))), dx, dy
    )
    solid = f.createIfcExtrudedAreaSolid(
        prof,
        f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((float(x), float(y), float(z)))),
        f.createIfcDirection((0.0, 0.0, 1.0)),
        dz,
    )
    return f.createIfcShapeRepresentation(body, "Body", "SweptSolid", [solid])


def build_sample_ifc(
    path: Path,
    *,
    with_spaces: bool = True,
    with_exit_door: bool = True,
    with_extinguisher: bool = True,
    with_storeys: bool = True,
) -> dict[str, str]:
    run = ifcopenshell.api.run
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject", name="Sample")
    run("unit.assign_unit", f, length={"is_metric": True, "raw": "MILLIMETERS"})
    model_ctx = run("context.add_context", f, context_type="Model")
    body = run(
        "context.add_context", f, context_type="Model", context_identifier="Body",
        target_view="MODEL_VIEW", parent=model_ctx,
    )
    site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", f, ifc_class="IfcBuilding", name="Building")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    run("aggregate.assign_object", f, products=[building], relating_object=site)

    ids: dict[str, str] = {}
    storeys = {}
    if with_storeys:
        for key, name, elev in (("L1", "Level 1", 0.0), ("L2", "Level 2", 3500.0)):
            st = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=name)
            st.Elevation = elev
            st.ObjectPlacement = _local(f, None, 0.0, 0.0, elev)
            run("aggregate.assign_object", f, products=[st], relating_object=building)
            storeys[key] = st
            ids[key] = st.GlobalId

    def _at(prod, key, x, y):
        parent = storeys[key].ObjectPlacement if storeys else None
        prod.ObjectPlacement = _local(f, parent, x, y, 0.0)

    def contain(prod, key="L1", x=0.0, y=0.0):
        _at(prod, key, x, y)
        if storeys:
            run("spatial.assign_container", f, products=[prod], relating_structure=storeys[key])
        else:
            run("spatial.assign_container", f, products=[prod], relating_structure=building)

    def place(prod, rep):
        run("geometry.assign_representation", f, product=prod, representation=rep)

    wall = run("root.create_entity", f, ifc_class="IfcWall", name="Wall 1")
    place(wall, run("geometry.add_wall_representation", f, context=body, length=5000.0, height=3000.0, thickness=200.0))
    contain(wall, "L1", 0.0, 0.0)
    ids["wall_1"] = wall.GlobalId

    door_ext = run("root.create_entity", f, ifc_class="IfcDoor", name="Main Entrance")
    place(door_ext, _box(f, body, 0, 0, 0, 1000.0, 100.0, 2100.0))
    contain(door_ext, "L1", 5000.0, 0.0)
    run("pset.edit_pset", f, pset=run("pset.add_pset", f, product=door_ext, name="Pset_DoorCommon"), properties={"IsExternal": True})
    ids["door_ext"] = door_ext.GlobalId

    door_int = run("root.create_entity", f, ifc_class="IfcDoor", name="Office Door")
    place(door_int, _box(f, body, 0, 0, 0, 900.0, 100.0, 2100.0))
    contain(door_int, "L1", 2000.0, 2500.0)
    run("pset.edit_pset", f, pset=run("pset.add_pset", f, product=door_int, name="Pset_DoorCommon"), properties={"IsExternal": False})
    ids["door_int"] = door_int.GlobalId

    if with_exit_door:
        d = run("root.create_entity", f, ifc_class="IfcDoor", name="Emergency Exit")
        place(d, _box(f, body, 0, 0, 0, 1000.0, 100.0, 2100.0))
        contain(d, "L1", 4000.0, 2500.0)
        run("pset.edit_pset", f, pset=run("pset.add_pset", f, product=d, name="Pset_DoorCommon"), properties={"FireExit": True})
        ids["door_exit"] = d.GlobalId

    if with_spaces:
        for key, nm, ln, sk in (("space_101", "101", "Corridor", "L1"), ("space_201", "201", "Office", "L2")):
            sp = run("root.create_entity", f, ifc_class="IfcSpace", name=nm)
            sp.LongName = ln
            if storeys:
                run("aggregate.assign_object", f, products=[sp], relating_object=storeys[sk])
                _at(sp, sk, 0.0, 0.0)
            ids[key] = sp.GlobalId

    if with_extinguisher:
        ext = run("root.create_entity", f, ifc_class="IfcBuildingElementProxy", name="Fire Extinguisher")
        place(ext, _box(f, body, 0, 0, 0, 200.0, 200.0, 600.0))
        contain(ext, "L1", 1000.0, 1500.0)
        ids["ext_1"] = ext.GlobalId

    sink = run("root.create_entity", f, ifc_class="IfcSanitaryTerminal", name="Sink")
    place(sink, _box(f, body, 0, 0, 0, 500.0, 400.0, 300.0))
    contain(sink, "L1", 3000.0, 1500.0)
    ids["sink_1"] = sink.GlobalId

    stair = run("root.create_entity", f, ifc_class="IfcStair", name="Stair")
    place(stair, _box(f, body, 0, 0, 0, 1200.0, 3000.0, 3000.0))
    contain(stair, "L1", 6000.0, 1000.0)
    ids["stair_1"] = stair.GlobalId

    f.write(str(path))
    return ids
