import pytest


def pytest_collection_modifyitems(items):
    """Name adapter boundaries explicitly; these are not pure unit tests."""
    adapter_files = {
        "test_blender.py", "test_default_app.py", "test_extract.py", "test_gate_client.py",
        "test_geometry.py", "test_process.py", "test_runner.py", "test_server.py", "test_storage.py",
    }
    for item in items:
        item.add_marker(pytest.mark.adapter if item.path.name in adapter_files else pytest.mark.unit)
