from __future__ import annotations

import hmac
import re
import threading
import uuid
from typing import Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from worker.config import WorkerSettings, toolchain_version
from worker.gate_client import GateClient, GateError

_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def _bad(message: str) -> JSONResponse:
    return JSONResponse({"code": "VALIDATION_ERROR", "message": message}, status_code=400)


def _valid_uuid(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        uuid.UUID(v)
        return True
    except ValueError:
        return False


def create_worker_app(settings: WorkerSettings, runner_factory: Callable[[], object],
                      gate: GateClient | None = None) -> FastAPI:
    app = FastAPI(title="ifc-worker")
    if gate is None:
        gate = GateClient(settings.be_base_url, settings.worker_key, httpx.Client(timeout=10.0))
    app.state.threads = []

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/deliveries")
    async def deliveries(request: Request):
        key = request.headers.get("X-Worker-Key", "")
        if not hmac.compare_digest(key.encode(), settings.worker_key.encode()):
            return JSONResponse({"code": "UNAUTHORIZED"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            return _bad("Invalid JSON")
        payload = body.get("payload") if isinstance(body, dict) else None
        if (not isinstance(payload, dict) or not isinstance(body.get("eventKey"), str)
                or not body["eventKey"] or not isinstance(body.get("payloadHash"), str)
                or not _HEX64.match(body["payloadHash"]) or not _valid_uuid(payload.get("job_id"))
                or not isinstance(payload.get("input_hash"), str)
                or not _HEX64.match(payload["input_hash"])):
            return _bad("Invalid delivery shape")
        job_id = payload["job_id"]
        try:
            claim = await run_in_threadpool(gate.claim, job_id, body["eventKey"], body["payloadHash"],
                                            payload["input_hash"], toolchain_version(settings))
        except GateError as exc:
            return JSONResponse({"code": exc.code or "GATE_ERROR", "message": str(exc)},
                                status_code=exc.status if exc.status >= 400 else 502)
        if not claim.replayed:
            runner = runner_factory()
            t = threading.Thread(target=runner.run, args=(job_id, claim), daemon=True)
            app.state.threads.append(t)
            t.start()
        return {"eventKey": body["eventKey"], "payloadHash": body["payloadHash"],
                "receiptId": claim.receipt_id}

    return app
