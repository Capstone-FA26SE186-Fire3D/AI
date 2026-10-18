"""Bearer auth for the v2 adapter routes."""
from __future__ import annotations

import hmac
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.config import Settings


class Unauthorized(Exception):
    """Raised by `require_bearer`; rendered as 401 {"code":"AI_UNAUTHORIZED"} by `unauthorized_handler`."""


def require_bearer(settings: Settings) -> Callable[[Request], None]:
    """FastAPI dependency: enforce `Authorization: Bearer <AI_API_KEY>` when a key is configured."""
    expected = settings.ai_api_key

    def dependency(request: Request) -> None:
        if not expected:
            return
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), expected.encode()):
            raise Unauthorized()

    return dependency


async def unauthorized_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"code": "AI_UNAUTHORIZED", "message": "Missing or invalid bearer token"},
        headers={"WWW-Authenticate": "Bearer"},
    )
