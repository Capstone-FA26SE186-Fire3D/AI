import pytest
from fastapi.testclient import TestClient

from worker import server


def test_default_app_uses_local_storage_in_development(monkeypatch, tmp_path):
    monkeypatch.setenv("BE_BASE_URL", "http://be")
    monkeypatch.setenv("WORKER_KEY", "k" * 32)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("WORKER_LOCAL_STORAGE", str(tmp_path))
    app = server.create_default_app()
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_default_app_requires_s3_in_production(monkeypatch):
    monkeypatch.setenv("BE_BASE_URL", "http://be")
    monkeypatch.setenv("WORKER_KEY", "k" * 32)
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    with pytest.raises(RuntimeError):
        server.create_default_app()


def test_import_does_not_build_app():
    import importlib
    importlib.reload(server)  # must not raise without env


def test_default_app_refuses_short_worker_key(monkeypatch, tmp_path):
    monkeypatch.setenv("BE_BASE_URL", "http://be")
    monkeypatch.setenv("WORKER_KEY", "")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.setenv("WORKER_LOCAL_STORAGE", str(tmp_path))
    with pytest.raises(RuntimeError, match="WORKER_KEY"):
        server.create_default_app()
