import pgsupport
import pytest


def test_sql_apply_error_fails_instead_of_skipping():
    def bad_apply(dsn):
        raise RuntimeError("applying KnowledgeChunks.sql failed: syntax error")

    with pytest.raises(pytest.fail.Exception) as info:
        pgsupport.prepare_or_fail("postgresql://x", wait=lambda dsn: None, apply=bad_apply)
    assert "syntax error" in str(info.value)


def test_readiness_timeout_fails_instead_of_skipping():
    def never_ready(dsn):
        raise RuntimeError("postgres not ready")

    with pytest.raises(pytest.fail.Exception):
        pgsupport.prepare_or_fail("postgresql://x", wait=never_ready, apply=lambda dsn: None)


def test_pg_source_skips_without_env_and_never_needs_docker(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: (_ for _ in ()).throw(AssertionError("docker probed")))
    assert pgsupport.pg_source({}) == "skip"
    assert pgsupport.pg_source({"FIRE3D_AI_TEST_PG_DOCKER": "0"}) == "skip"
    assert pgsupport.pg_source({"FIRE3D_AI_TEST_PG_DOCKER": "1"}) == "docker"
    assert pgsupport.pg_source({"FIRE3D_AI_TEST_PG_DSN": "postgresql://x", "FIRE3D_AI_TEST_PG_DOCKER": "1"}) == "dsn"
