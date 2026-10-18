import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.core.config import Settings
from app.main import create_app

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"


def test_legacy_routes_hidden_by_default() -> None:
    client = TestClient(create_app(Settings(legacy_routes_enabled=False)))

    assert client.post("/chat", json={"question": "x"}).status_code == 404


def test_legacy_routes_enabled_by_flag() -> None:
    app = create_app(Settings(legacy_routes_enabled=True))

    assert "/chat" in app.openapi()["paths"]


def test_production_requires_api_key() -> None:
    with pytest.raises(RuntimeError):
        create_app(Settings(environment="production", ai_api_key=""))


@pytest.mark.parametrize("environment", ["staging", "test", "Production"])
def test_non_development_requires_api_key(environment: str) -> None:
    with pytest.raises(RuntimeError, match="AI_API_KEY"):
        create_app(Settings(environment=environment, ai_api_key="", knowledge_database_url="postgresql://x/y"))


@pytest.mark.parametrize("name", ["scenario-state", "geometry-metadata", "building-metadata"])
def test_vendored_contract_fixtures_validate(name: str) -> None:
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads((CONTRACTS / "fixtures" / f"{name}.valid.json").read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(fixture)
