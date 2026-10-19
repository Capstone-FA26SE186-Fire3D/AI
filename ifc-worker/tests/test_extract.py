from pathlib import Path

import pytest

from tests.fixtures.make_ifc import build_sample_ifc
from worker.pipeline.extract import read_model


def test_read_sample_storeys_ordered_and_ids(tmp_path: Path):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    assert [(s.id, s.elevation_m) for s in info.storeys] == [("L1", 0.0), ("L2", 3.5)]
    assert info.storeys[0].ifc_global_id == ids["L1"]
    assert info.unit_scale == pytest.approx(0.001)
    assert info.schema.startswith("IFC4")
    assert len(info.spaces) == 2


def test_non_step_file_rejected(tmp_path: Path):
    p = tmp_path / "x.ifc"
    p.write_text("<html>not ifc</html>")
    with pytest.raises(ValueError, match="IFC_UNSUPPORTED_FORMAT"):
        read_model(p)


def test_element_storey_and_psets(tmp_path: Path):
    ids = build_sample_ifc(tmp_path / "s.ifc")
    _, info = read_model(tmp_path / "s.ifc")
    by_id = {e.global_id: e for e in info.elements}
    door = by_id[ids["door_ext"]]
    assert door.ifc_class == "IfcDoor"
    assert door.storey_id == "L1"
    assert door.psets["Pset_DoorCommon"]["IsExternal"] is True
    assert by_id[ids["sink_1"]].ifc_class == "IfcSanitaryTerminal"
    assert ids["space_101"] not in by_id
    sp = {s.global_id: s for s in info.spaces}[ids["space_101"]]
    assert (sp.name, sp.long_name, sp.storey_id) == ("101", "Corridor", "L1")


def test_no_storeys_does_not_crash(tmp_path: Path):
    build_sample_ifc(tmp_path / "s.ifc", with_storeys=False)
    _, info = read_model(tmp_path / "s.ifc")
    assert info.storeys == []
    assert all(e.storey_id is None for e in info.elements)


def test_fixture_placement_separates_and_elevates(tmp_path: Path):
    import ifcopenshell
    import ifcopenshell.util.placement as pl

    ids = build_sample_ifc(tmp_path / "s.ifc")
    f = ifcopenshell.open(str(tmp_path / "s.ifc"))

    def pos(k):
        return pl.get_local_placement(f.by_guid(ids[k]).ObjectPlacement)[:3, 3]

    assert pos("space_201")[2] == 3500.0
    assert pos("sink_1")[2] == 0.0
    assert tuple(pos("sink_1")[:2]) != tuple(pos("ext_1")[:2])
