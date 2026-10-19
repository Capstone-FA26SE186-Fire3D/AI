import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.v2.errors import AdapterRefusal, refuse
from app.v2.schemas import AdapterRequest, Citation, ROUTES

FIX = Path(__file__).parent.parent / "fixtures" / "v2"
NAMES = ["organization-answer", "organization-scenario-draft", "trainee-answer"]


def load(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_request_examples_parse(name):
    req = AdapterRequest.model_validate(load(name))
    if name == "organization-scenario-draft":
        assert req.bim is not None
        assert req.bim.floors[0].elevation_meters == 0
        assert req.bim.anchors[0].ifc_global_id == "3cUkl32yn9qRSPvBJVyWYp"
        assert req.bim.geometry.sha256_hash


@pytest.mark.parametrize("name", NAMES)
def test_unknown_fields_ignored(name):
    body = load(name)
    body["extra_field"] = 1
    for s in body["sources"]:
        s["extra_field"] = 1
        if isinstance(s["content"], dict):
            s["content"]["extra_field"] = 1
    if body.get("bim"):
        body["bim"]["extra_field"] = 1
        body["bim"]["runtime"]["extra_field"] = 1
    AdapterRequest.model_validate(body)


def test_response_rejects_bad_relevance():
    with pytest.raises(ValidationError):
        Citation(document_id="d", document_version="v", chunk_id="c", excerpt_locator="l", relevance=1.5)


def test_request_rejects_bad_hash():
    body = copy.deepcopy(load("organization-answer"))
    body["input_hash"] = "XYZ"
    with pytest.raises(ValidationError):
        AdapterRequest.model_validate(body)


def test_routes_and_refuse():
    assert ROUTES["organization/scenario-draft"].requires_bim
    assert ROUTES["trainee/answer"].organization_id_null
    err = refuse("AI_ROUTE_MISMATCH", "bad")
    assert isinstance(err, AdapterRefusal) and err.status_code == 422 and err.code == "AI_ROUTE_MISMATCH"
