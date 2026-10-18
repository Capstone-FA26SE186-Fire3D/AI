import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SQL_FILES = [
    ROOT / "tests" / "fixtures" / "pg_bootstrap.sql",
    ROOT / "contracts" / "KnowledgeChunks.sql",
    ROOT / "db" / "migrations" / "001_ai_service.sql",
]


def _wait_ready(dsn: str, timeout: float = 60.0) -> None:
    import psycopg

    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1)
    raise RuntimeError(f"postgres not ready: {last}")


def _apply_sql(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in SQL_FILES:
            conn.execute(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def pg_dsn():
    override = os.environ.get("FIRE3D_AI_TEST_PG_DSN")
    container = None
    if override:
        dsn = override
    else:
        if shutil.which("docker") is None:
            pytest.skip("docker is not available")
        try:
            run = subprocess.run(
                ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::5432",
                 "-e", "POSTGRES_PASSWORD=test", "pgvector/pgvector:pg17"],
                capture_output=True, text=True, timeout=180,
            )
            if run.returncode != 0:
                pytest.skip(f"docker run failed: {run.stderr.strip()[:200]}")
            container = run.stdout.strip()
            port_out = subprocess.run(
                ["docker", "port", container, "5432/tcp"],
                capture_output=True, text=True, timeout=30,
            ).stdout
            match = re.search(r":(\d+)\s*$", port_out.strip().splitlines()[0])
            if not match:
                pytest.skip(f"cannot read docker port: {port_out!r}")
            dsn = f"postgresql://postgres:test@127.0.0.1:{match.group(1)}/postgres"
        except (OSError, subprocess.SubprocessError, IndexError) as exc:
            if container:
                subprocess.run(["docker", "stop", container], capture_output=True)
            pytest.skip(f"docker unavailable: {exc}")
    try:
        try:
            _wait_ready(dsn)
            _apply_sql(dsn)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"postgres test database unavailable: {exc}")
        yield dsn
    finally:
        if container:
            subprocess.run(["docker", "stop", container], capture_output=True)
