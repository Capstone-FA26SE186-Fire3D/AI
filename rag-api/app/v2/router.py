"""HTTP surface BE calls: POST /v2/{organization,trainee}/... and GET /v2/requests/{request_id}."""
from __future__ import annotations

import json
import logging
import time
from typing import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings
from app.requests.service import RequestService, error
from app.v2.auth import require_bearer
from app.v2.schemas import AdapterRequest

log = logging.getLogger("app.v2")


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for item in exc.errors(include_url=False, include_input=False)[:5]:
        loc = ".".join(str(p) for p in item.get("loc", ())) or "body"
        parts.append(f"{loc}: {item.get('msg', 'invalid')}")
    return "; ".join(parts) or "Invalid request body"


def build_v2_router(get_service: Callable[[], RequestService], settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v2", dependencies=[Depends(require_bearer(settings))])

    def respond(status: int, body: dict, request_id: str | None, started: float, route: str) -> JSONResponse:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        log.info("%s -> %d", route, status, extra={"request_id": request_id, "duration_ms": duration_ms})
        return JSONResponse(status_code=status, content=body)

    def service_or_none() -> RequestService | None:
        try:
            return get_service()
        except Exception:
            log.exception("AI service unavailable")
            return None

    async def handle_post(route_key: str, request: Request) -> JSONResponse:
        started = time.perf_counter()
        header_id = request.headers.get("x-request-id")
        route = f"POST /v2/{route_key}"
        raw = await request.body()
        try:
            req = AdapterRequest.model_validate(json.loads(raw))
        except (ValueError, UnicodeDecodeError) as exc:
            message = _validation_message(exc) if isinstance(exc, ValidationError) else "Body is not valid JSON"
            return respond(422, error("AI_REQUEST_INVALID", message), header_id, started, route)
        if header_id is None or header_id != req.request_id:
            return respond(
                422, error("AI_REQUEST_ID_MISMATCH", "X-Request-Id header must equal body request_id"),
                req.request_id, started, route,
            )
        service = service_or_none()
        if service is None:
            return respond(503, error("AI_TEMPORARILY_UNAVAILABLE", "AI service is temporarily unavailable"),
                           req.request_id, started, route)
        status, body = await run_in_threadpool(service.submit, route_key, req)
        return respond(status, body, req.request_id, started, route)

    @router.post("/organization/answer")
    async def organization_answer(request: Request) -> JSONResponse:
        return await handle_post("organization/answer", request)

    @router.post("/organization/scenario-draft")
    async def organization_scenario_draft(request: Request) -> JSONResponse:
        return await handle_post("organization/scenario-draft", request)

    @router.post("/trainee/answer")
    async def trainee_answer(request: Request) -> JSONResponse:
        return await handle_post("trainee/answer", request)

    @router.get("/requests/{request_id}")
    async def lookup(request_id: str) -> JSONResponse:
        started = time.perf_counter()
        route = "GET /v2/requests"
        service = service_or_none()
        if service is None:
            return respond(503, error("AI_TEMPORARILY_UNAVAILABLE", "AI service is temporarily unavailable"),
                           request_id, started, route)
        try:
            status, body = await run_in_threadpool(service.lookup, request_id)
        except Exception:
            log.exception("lookup failed", extra={"request_id": request_id})
            status, body = 503, error("AI_TEMPORARILY_UNAVAILABLE", "AI service is temporarily unavailable")
        return respond(status, body, request_id, started, route)

    return router
