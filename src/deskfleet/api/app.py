"""The FastAPI app factory. Nothing imports this package."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from deskfleet.api import models_routes, ops, resolve
from deskfleet.config import configure_logging, get_logger, get_settings
from deskfleet.observability import metrics_middleware, setup_tracing
from deskfleet.store import migrate

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    # Tracing must be configured before any LangChain object exists, or it silently does nothing.
    setup_tracing(settings)
    migrate()
    logger.info("service_started", extra={"port": settings.port})
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="DeskFleet",
        version=ops.VERSION,
        lifespan=lifespan,
    )
    metrics_middleware(application)
    application.include_router(ops.router)
    application.include_router(resolve.router)
    application.include_router(models_routes.router)

    @application.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Never return a traceback — it can carry key fragments and account detail."""
        correlation_id = str(uuid.uuid4())
        logger.error(
            "unhandled_error",
            extra={
                "correlation_id": correlation_id,
                "path": request.url.path,
                "cause": type(exc).__name__,
            },
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "the request could not be completed",
                "correlation_id": correlation_id,
            },
        )

    return application


app = create_app()
