from __future__ import annotations

import hmac
import logging
import os
from functools import partial
from pathlib import Path
from contextlib import asynccontextmanager
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
# BE ProcessingWorker MachineKey is 32-512 chars; a shorter key is a misconfiguration.
MIN_WORKER_KEY_LENGTH = 32
PACKAGE_JOB_REASON = "Package jobs are handled by the Unity package worker"

log = logging.getLogger("ifc-worker")


def _require_worker_key(settings: WorkerSettings) -> None:
    if len(settings.worker_key or "") < MIN_WORKER_KEY_LENGTH:
        raise RuntimeError(f"WORKER_KEY must be at least {MIN_WORKER_KEY_LENGTH} characters")


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
    _require_worker_key(settings)
    own_http = None
    if gate is None:
        own_http = httpx.Client(timeout=10.0)
        gate = GateClient(settings.be_base_url, settings.worker_key, own_http)
    toolchain = toolchain_version(settings)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        if own_http is not None:
            own_http.close()

    app = FastAPI(title="ifc-worker", lifespan=lifespan)
    app.state.threads = []
    slots = threading.BoundedSemaphore(max(1, settings.max_concurrent_jobs))

    def run_and_release(runner, job_id, claim):
        try:
            runner.run(job_id, claim)
        finally:
            slots.release()

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
        # Take a slot before claiming: a claim we cannot run would hold the lease until it expires.
        if not slots.acquire(blocking=False):
            return JSONResponse({"code": "WORKER_BUSY", "message": "No free job slot"}, status_code=503)
        started = False
        try:
            try:
                claim = await run_in_threadpool(gate.claim, job_id, body["eventKey"], body["payloadHash"],
                                                payload["input_hash"], toolchain)
            except GateError as exc:
                return JSONResponse({"code": exc.code or "GATE_ERROR", "message": str(exc)},
                                    status_code=exc.status if exc.status >= 400 else 502)
            if not _valid_uuid(claim.receipt_id):
                return JSONResponse({"code": "GATE_REPLY_INVALID", "message": "Invalid receiptId"},
                                    status_code=502)
            if not claim.replayed and claim.scenario_version_id:
                # The claim is committed (ACK below); hand the job back as failed instead of running IFC.
                try:
                    await run_in_threadpool(gate.fail, job_id, claim.attempt_id, claim.lease_token,
                                            PACKAGE_JOB_REASON)
                except GateError as exc:
                    log.warning("job %s: failing package job failed: %s", job_id, exc)
            elif not claim.replayed:
                runner = runner_factory()
                t = threading.Thread(target=run_and_release, args=(runner, job_id, claim), daemon=True)
                app.state.threads.append(t)
                t.start()
                started = True
        finally:
            if not started:
                slots.release()
        return {"eventKey": body["eventKey"], "payloadHash": body["payloadHash"],
                "receiptId": claim.receipt_id}

    return app


def create_default_app() -> FastAPI:
    """App for `uvicorn worker.server:app`, configured from environment variables."""
    from worker.pipeline.process import process_ifc
    from worker.runner import JobRunner
    from worker.storage import LocalStorage, S3Storage

    settings = WorkerSettings()
    _require_worker_key(settings)
    if settings.s3_bucket:
        storage = S3Storage(settings)
    elif settings.environment == "development":
        storage = LocalStorage(Path(os.environ.get("WORKER_LOCAL_STORAGE", "./data/storage")))
    else:
        raise RuntimeError("S3_BUCKET is required outside development")
    process = partial(process_ifc, settings=settings)
    http = httpx.Client(timeout=10.0)
    gate = GateClient(settings.be_base_url, settings.worker_key, http)
    app = create_worker_app(settings, lambda: JobRunner(gate, storage, settings, process), gate=gate)
    app.router.on_shutdown.append(http.close)
    return app


def __getattr__(name: str):
    if name == "app":  # lazy: importing this module must not need env vars
        value = create_default_app()
        globals()["app"] = value
        return value
    raise AttributeError(name)
