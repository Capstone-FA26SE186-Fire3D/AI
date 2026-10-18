import os
import shutil

import pytest
from pgsupport import apply_sql, prepare_or_fail, start_container, stop_container, wait_ready  # noqa: F401


@pytest.fixture(scope="session")
def pg_dsn():
    override = os.environ.get("FIRE3D_AI_TEST_PG_DSN")
    container = None
    if override:
        dsn = override
    else:
        if shutil.which("docker") is None:
            pytest.skip("docker is not available")
        container, dsn = start_container()
    try:
        prepare_or_fail(dsn)
        yield dsn
    finally:
        if container:
            stop_container(container)
