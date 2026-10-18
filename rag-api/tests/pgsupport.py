"""Helpers for the pg_dsn fixture. Skip only when Docker is unavailable; any later failure is a test failure."""
import re
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


def wait_ready(dsn: str, timeout: float = 60.0) -> None:
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
    raise RuntimeError(f"postgres not ready after {timeout}s: {last}")


def apply_sql(dsn: str, files=SQL_FILES) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        for path in files:
            try:
                conn.execute(Path(path).read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError(f"applying {Path(path).name} failed: {exc}") from exc


def prepare_or_fail(dsn: str, wait=wait_ready, apply=apply_sql) -> None:
    """Wait for the database and apply the SQL. Errors FAIL the run (never skip)."""
    try:
        wait(dsn)
        apply(dsn)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"test database setup failed: {exc}", pytrace=False)


def start_container() -> tuple[str, str]:
    """Start pgvector container; returns (container_id, dsn). Skips only if Docker is unavailable."""
    try:
        run = subprocess.run(
            ["docker", "run", "-d", "--rm", "-p", "127.0.0.1::5432",
             "-e", "POSTGRES_PASSWORD=test", "pgvector/pgvector:pg17"],
            capture_output=True, text=True, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"docker unavailable: {exc}")
    if run.returncode != 0:
        pytest.skip(f"docker run failed: {run.stderr.strip()[:200]}")
    container = run.stdout.strip()
    try:
        port_out = subprocess.run(
            ["docker", "port", container, "5432/tcp"],
            capture_output=True, text=True, timeout=30,
        ).stdout
        match = re.search(r":(\d+)\s*$", port_out.strip().splitlines()[0])
        if not match:
            raise RuntimeError(f"cannot parse docker port output: {port_out!r}")
    except Exception:
        stop_container(container)
        raise
    return container, f"postgresql://postgres:test@127.0.0.1:{match.group(1)}/postgres"


def stop_container(container: str) -> None:
    subprocess.run(["docker", "stop", container], capture_output=True)
