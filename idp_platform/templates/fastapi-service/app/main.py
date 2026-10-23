import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import get_settings
from app.logging_config import configure_logging
from app.metrics import APP_INFO, MetricsMiddleware
from app.routers import health, items
from app.telemetry import configure_telemetry

settings = get_settings()
configure_logging(settings.log_level, settings.log_format)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "starting %s",
        settings.name,
        extra={"version": settings.version, "commit": settings.commit},
    )
    yield
    logger.info("shutting down %s", settings.name)


def create_app() -> FastAPI:
    app = FastAPI(title=settings.name, version=settings.version, lifespan=lifespan)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(MetricsMiddleware)

    app.include_router(health.router)
    app.include_router(items.router)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"message": f"{settings.name} is running", "docs": "/docs"}

    APP_INFO.labels(settings.version, settings.commit, settings.environment).set(1)
    configure_telemetry(app)
    return app


app = create_app()
