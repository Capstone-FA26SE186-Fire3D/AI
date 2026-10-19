import os

import pytest
from pgsupport import apply_sql, pg_source, prepare_or_fail, start_container, stop_container, wait_ready  # noqa: F401


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
