import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import (
    set_request_id,
    setup_logging,
)
from app.db.session import close_db_engine, get_db
from app.schemas.health import HealthResponse, ReadinessResponse
from app.services.health import HealthService

logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown lifespan management."""
    settings = get_settings()
    # 1. Initialize logging
    setup_logging(log_level=settings.LOG_LEVEL, log_format=settings.LOG_FORMAT)
    logger.info(
        "Starting %s in [%s] mode (v%s, debug=%s)",
        settings.APP_NAME,
        settings.APP_ENV,
        settings.VERSION,
        settings.DEBUG,
    )

    yield

    # 2. Cleanup resources on shutdown
    logger.info("Shutting down %s...", settings.APP_NAME)
    await close_db_engine()
    logger.info("Application shutdown complete.")


def create_application() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()

    app = FastAPI(
        title=f"{settings.APP_NAME} API",
        description="Production-oriented modular RAG platform - Phase 2: Auth & Multi-Tenancy.",
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Request ID and Access Logging Middleware
    @app.middleware("http")
    async def request_id_and_logging_middleware(request: Request, call_next) -> Response:
        # Extract or generate X-Request-ID
        req_id = request.headers.get("X-Request-ID")
        if not req_id or not req_id.strip():
            req_id = str(uuid.uuid4())

        # Set context variable for structured logging
        set_request_id(req_id)
        request.state.request_id = req_id

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # Attach X-Request-ID to response header
            response.headers["X-Request-ID"] = req_id

            logger.info(
                "%s %s -> %d (%.2f ms)",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error(
                "%s %s failed with exception: %s (%.2f ms)",
                request.method,
                request.url.path,
                str(exc),
                duration_ms,
            )
            raise
        finally:
            set_request_id(None)

    # 2. Configure CORS Middleware
    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    # 3. Register Centralized Exception Handlers
    register_exception_handlers(app)

    # 4. Root Liveness & Readiness Endpoints
    @app.get(
        "/health",
        response_model=HealthResponse,
        tags=["Health & Readiness"],
        summary="Root Liveness Probe",
        description="Lightweight liveness probe that verifies if the web process is running.",
    )
    async def root_liveness() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get(
        "/ready",
        response_model=ReadinessResponse,
        tags=["Health & Readiness"],
        summary="Root Readiness Probe",
        description="Verifies infrastructure dependencies (PostgreSQL and pgvector).",
    )
    async def root_readiness(
        response: Response,
        session: AsyncSession = Depends(get_db),
    ) -> ReadinessResponse:
        is_ready, db_status, vector_status = await HealthService.check_infrastructure(session)
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return ReadinessResponse(
                status="unhealthy",
                database=db_status,
                vector_store=vector_status,
            )
        return ReadinessResponse(
            status="ready",
            database=db_status,
            vector_store=vector_status,
        )

    # 5. Register API Versioned Routers
    app.include_router(api_router, prefix=settings.API_V1_STR)

    return app


app = create_application()
