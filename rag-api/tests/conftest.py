import os

import pytest
from pgsupport import apply_sql, pg_source, prepare_or_fail, start_container, stop_container, wait_ready  # noqa: F401


def pytest_collection_modifyitems(items):
    """Classify existing suites without changing their assertions or fixture lifetime."""
    for item in items:
        path = item.path.as_posix()
        if item.get_closest_marker("pgvector") or item.name.startswith("test_real_model_"):
            item.add_marker(pytest.mark.integration)
        elif any(part in path for part in (
            "/requests/", "/v2/", "/sources/test_fetch.py", "/sources/test_resolver.py",
            "/sources/test_warmer.py", "/sources/test_inline_cache.py", "/llm/test_providers.py",
            "/llm/test_compat_provider.py", "/index/test_memory_index.py",
        )):
            item.add_marker(pytest.mark.adapter)
        else:
            item.add_marker(pytest.mark.unit)


@pytest.fixture(scope="session")
def pg_dsn():
    source = pg_source(os.environ)
    container = None
    if source == "skip":
        pytest.skip("set FIRE3D_AI_TEST_PG_DSN (or FIRE3D_AI_TEST_PG_DOCKER=1 to opt in to Docker)")
    if source == "dsn":
        dsn = os.environ["FIRE3D_AI_TEST_PG_DSN"]
    else:
        container, dsn = start_container()
    try:
        prepare_or_fail(dsn)
        yield dsn
    finally:
        if container:
            stop_container(container)
