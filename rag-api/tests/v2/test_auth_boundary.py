"""The adapter bearer gate is tested without a provider or live backend."""

import asyncio

import pytest
from starlette.requests import Request

from app.core.config import Settings
from app.v2.auth import Unauthorized, require_bearer, unauthorized_handler


def request(value=None):
    headers = [] if value is None else [(b"authorization", value.encode())]
    return Request({"type": "http", "method": "POST", "path": "/v2/organization/answer", "headers": headers})


def test_configured_bearer_rejects_missing_wrong_scheme_and_wrong_token():
    gate = require_bearer(Settings(ai_api_key="private-test-key", _env_file=None))
    for header in (None, "Basic private-test-key", "Bearer other", "Bearer "):
        with pytest.raises(Unauthorized):
            gate(request(header))
    gate(request("Bearer private-test-key"))
    gate(request("bearer private-test-key"))


def test_unconfigured_development_gate_and_unauthorized_response():
    require_bearer(Settings(ai_api_key="", _env_file=None))(request())
    result = asyncio.run(unauthorized_handler(request(), Unauthorized()))
    assert result.status_code == 401
    assert result.headers["www-authenticate"] == "Bearer"
    assert b'"AI_UNAUTHORIZED"' in result.body
