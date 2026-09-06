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
    set_trace_id,
    setup_logging,
)
from app.core.tracing import RequestTrace, set_current_trace
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

    # 1. Request ID + Trace ID and Access Logging Middleware (Phase 1.5)
    @app.middleware("http")
    async def request_id_and_logging_middleware(request: Request, call_next) -> Response:
        # Extract or generate X-Request-ID / X-Trace-ID
        req_id = request.headers.get("X-Request-ID")
        if not req_id or not req_id.strip():
            req_id = str(uuid.uuid4())
        trace_id = request.headers.get("X-Trace-ID")
        if not trace_id or not trace_id.strip():
            trace_id = str(uuid.uuid4())

        # Set context variables for structured logging & tracing
        set_request_id(req_id)
        set_trace_id(trace_id)
        request.state.request_id = req_id
        request.state.trace_id = trace_id

        # Create a RequestTrace for this request
        trace = RequestTrace(trace_id=trace_id, request_id=req_id)
        trace.mark("request_start")
        tok_trace = set_current_trace(trace)

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            trace.record("http_total_ms", duration_ms)

            # Attach IDs to response headers
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Trace-ID"] = trace_id

            # Log trace summary for chat endpoints (verbose tracing)
            if request.url.path.startswith("/api/v1/chat"):
                trace.log_summary()

            logger.info(
                "%s %s -> %d (%.2f ms) trace=%s",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
                trace_id,
            )
            return response
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            trace.record("http_total_ms", duration_ms)
            trace.add_error(str(exc))
            logger.error(
                "%s %s failed with exception: %s (%.2f ms) trace=%s",
                request.method,
                request.url.path,
                str(exc),
                duration_ms,
                trace_id,
            )
            raise
        finally:
            set_request_id(None)
            set_trace_id(None)
            set_current_trace(None)

    # 2. Configure CORS Middleware
    allowed_origins = [
        "https://byok-livid.vercel.app",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ]
    if settings.CORS_ORIGINS:
        allowed_origins.extend(settings.CORS_ORIGINS)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(set(allowed_origins)),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Trace-ID"],
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
