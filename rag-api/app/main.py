from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None, *, service: "object | None" = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.environment.lower() == "production" and not settings.ai_api_key:
        raise RuntimeError("AI_API_KEY must be set when ENVIRONMENT=production")
    configure_logging()
    app = FastAPI(title="Local RAG API")
    app.state.settings = settings
    app.state.service = service

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

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
