from pathlib import Path

from tests.fixtures.make_ifc import build_sample_ifc
from worker.pipeline.classify import Candidate, classify_element, load_keywords
from worker.pipeline.extract import IfcModelInfo, read_model
from worker.pipeline.qa import outcome, run_qa
from worker.pipeline.report import GeometryReport

KW = load_keywords(Path(__file__).parent.parent / "config" / "keywords.v1.json")


def _run(tmp_path, report=None, **kw):
    build_sample_ifc(tmp_path / "s.ifc", **kw)
    _, info = read_model(tmp_path / "s.ifc")
    cands = {}
    for e in info.elements:
        c = classify_element(e, KW)
        if c:
            cands[e.global_id] = c
    return info, cands, run_qa(info, cands, report)


def codes(issues):
    return {i.code for i in issues}


def test_no_spaces_error_failed(tmp_path):
    _, _, issues = _run(tmp_path, with_spaces=False)
    assert "IFC_NO_SPACES" in codes(issues)
    assert outcome(issues) == "Failed"


def test_missing_exit_is_warning_passed(tmp_path):
    info, cands, _ = _run(tmp_path, with_exit_door=False)
    cands = {k: v for k, v in cands.items() if v.catalog_key != "door.exit"}
    issues = run_qa(info, cands, None)
    assert [i.severity for i in issues if i.code == "IFC_EXIT_UNKNOWN"] == ["Warning"]
    assert outcome(issues) == "Passed"


def test_no_storeys_does_not_crash(tmp_path):
    _, _, issues = _run(tmp_path, with_storeys=False)
    assert "IFC_NO_STOREYS" in codes(issues)
    assert outcome(issues) == "Failed"


def test_low_confidence_grouped(tmp_path):
    _, _, issues = _run(tmp_path)
    low = [i for i in issues if i.code == "IFC_LOW_CONFIDENCE_DEVICE"]
    assert len(low) == 1 and len(low[0].ifc_global_ids) >= 2  # proxy extinguisher + inferred exit
    big = {f"g{i}": Candidate("water.sink", 0.6, "ifc") for i in range(250)}
    info = IfcModelInfo("IFC4", None, 0.001, [], [], [])
    low = [i for i in run_qa(info, big, None) if i.code == "IFC_LOW_CONFIDENCE_DEVICE"]
    assert len(low) == 1 and len(low[0].ifc_global_ids) == 100


def test_geometry_report_issues(tmp_path):
    rep = GeometryReport(
        missing_body=[("a", "IfcWall"), ("b", "IfcFurnishingElement")],
        nonstandard_context=["c"],
        triangles_per_storey={"L1": 200000},
        unmapped_materials=["Foo"],
    )
    _, _, issues = _run(tmp_path, rep)
    errs = [i for i in issues if i.code == "IFC_NO_BODY_GEOMETRY" and i.severity == "Error"]
    warn = [i for i in issues if i.code == "IFC_NO_BODY_GEOMETRY" and i.severity == "Warning"]
    assert errs[0].ifc_global_ids == ["a"] and warn[0].ifc_global_ids == ["b"]
    by = {i.code: i for i in issues}
    assert by["IFC_BODY_NONSTANDARD_CONTEXT"].severity == "Info"
    assert by["IFC_TRIANGLE_BUDGET_EXCEEDED"].severity == "Warning"
    assert by["IFC_UNMAPPED_MATERIAL"].severity == "Info"
