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
