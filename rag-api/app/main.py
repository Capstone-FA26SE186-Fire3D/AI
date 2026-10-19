from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.v2.auth import Unauthorized, unauthorized_handler

if TYPE_CHECKING:
    from app.requests.service import RequestService

log = logging.getLogger(__name__)


def _is_development(settings: Settings) -> bool:
    return settings.environment.lower() == "development"


def build_default_service(settings: Settings) -> "RequestService":
    """Request store + knowledge index + provider from settings (raises if not buildable)."""
    from app.answering.pipeline import PipelineDeps
    from app.llm.factory import get_provider
    from app.requests.service import RequestService
    from app.requests.store import make_store
    from app.sources.resolver import SourceResolver

    if settings.knowledge_database_url:
        from app.index.pgvector import PgVectorIndex

        index = PgVectorIndex(settings.knowledge_database_url)
    elif _is_development(settings):
        from app.index.memory import MemoryIndex

        index = MemoryIndex()
    else:
        raise RuntimeError("KNOWLEDGE_DATABASE_URL must be set outside development")
    provider = get_provider(settings)
    store = make_store(settings.database_url)
    return RequestService(store, SourceResolver(index, provider, settings), PipelineDeps(provider, index, settings))


class ServiceHolder:
    """Returns the injected service, or builds the default one lazily (retrying after failures)."""

    def __init__(self, settings: Settings, service: "RequestService | None") -> None:
        self._settings = settings
        self._service = service
        self._lock = threading.Lock()

    def get(self) -> "RequestService":
        if self._service is not None:
            return self._service
        with self._lock:
            if self._service is None:
                self._service = build_default_service(self._settings)
        return self._service


def create_app(settings: Settings | None = None, *, service: "RequestService | None" = None) -> FastAPI:
    settings = settings or get_settings()
    if not _is_development(settings) and not settings.ai_api_key:
        raise RuntimeError("AI_API_KEY must be set outside development")
    if service is None and not _is_development(settings) and not settings.knowledge_database_url:
        raise RuntimeError("KNOWLEDGE_DATABASE_URL must be set outside development")
    if not _is_development(settings) and settings.database_url.lower().startswith("sqlite"):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL outside development (SQLite is local-only)")
    configure_logging()
    holder = ServiceHolder(settings, service)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = None
        if settings.recovery_interval_seconds > 0:
            from app.requests.recovery import RecoveryLoop

            # Callable source: a default service that cannot be built yet is retried each tick.
            loop = RecoveryLoop(holder.get, settings.recovery_interval_seconds)
            loop.start()
        try:
            yield
        finally:
            if loop is not None:
                loop.stop()

    app = FastAPI(title="Local RAG API", lifespan=lifespan)
    app.state.settings = settings
    app.state.service_holder = holder
    app.state.service = service
    app.add_exception_handler(Unauthorized, unauthorized_handler)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def _probe() -> None:
        holder.get().store.get("__ready_probe__")

    @app.get("/ready")
    async def ready() -> JSONResponse:
        try:
            await run_in_threadpool(_probe)
        except Exception as exc:
            log.warning("not ready: %s", type(exc).__name__)
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(status_code=200, content={"status": "ready"})

    from app.v2.router import build_v2_router

    app.include_router(build_v2_router(holder.get, settings))

    if settings.legacy_routes_enabled:
        from app.legacy.routes import router as legacy_router

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            allow_credentials=False,
        )
        app.include_router(legacy_router)
    return app


app = create_app()
