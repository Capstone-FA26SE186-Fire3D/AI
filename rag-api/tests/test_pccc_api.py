from fastapi.testclient import TestClient

from app.core.config import Settings
from app.legacy import routes
from app.main import create_app


class EmptyStore:
    def search_approved(self, question: str, top_k: int, jurisdiction: str) -> list:
        return []


def test_unapproved_knowledge_is_rejected() -> None:
    client = TestClient(create_app(Settings(legacy_routes_enabled=True)))

    response = client.post(
        "/pccc/knowledge-documents",
        files={"file": ("guide.md", b"text", "text/markdown")},
        data={"approved": "false", "jurisdiction": "VN", "version": "2023", "source_name": "BXD"},
    )

    assert response.status_code == 400
    assert "approved" in response.json()["detail"]


def test_bim_inspection_does_not_call_ai() -> None:
    client = TestClient(create_app(Settings(legacy_routes_enabled=True)))

    response = client.post(
        "/pccc/bim/inspect",
        files={"file": ("floor.gltf", b'{"nodes":[{"name":"Exit East"}]}', "model/gltf+json")},
    )

    assert response.status_code == 200
    assert response.json()["building"]["elements"][0]["element_type"] == "exit"


def test_analysis_without_approved_sources_returns_400(monkeypatch) -> None:
    monkeypatch.setattr(routes, "get_store", lambda: EmptyStore())
    client = TestClient(create_app(Settings(legacy_routes_enabled=True)))

    response = client.post(
        "/pccc/analyses",
        json={
            "building": {"name": "Tòa A"},
            "floors": [{"id": "L1", "number": 1, "name": "Tầng 1"}],
            "elements": [{"id": "exit-1", "element_type": "exit", "floor_id": "L1"}],
        },
    )

    assert response.status_code == 400
    assert "approved PCCC knowledge" in response.json()["detail"]
