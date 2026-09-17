import pytest

from app.bim.normalizer import inspect_bim_upload


def test_rejects_rvt_with_export_guidance() -> None:
    with pytest.raises(ValueError, match="Export the model to IFC or GLB/GLTF"):
        inspect_bim_upload("tower.rvt", b"binary", 1024)


def test_gltf_maps_named_exit_and_stair_nodes() -> None:
    result = inspect_bim_upload(
        "floor.gltf",
        b'{"nodes":[{"name":"Exit East"},{"name":"Stair A"}]}',
        1024,
    )

    assert {element.element_type for element in result.building.elements} == {"exit", "stair"}


def test_rejects_uploads_over_configured_size() -> None:
    with pytest.raises(ValueError, match="maximum allowed size"):
        inspect_bim_upload("floor.gltf", b"{}", 1)
