from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.health import HealthResponse, ReadinessResponse, SystemInfoResponse
from app.services.health import HealthService

router = APIRouter(tags=["Health & Readiness"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness Check",
    description="Lightweight liveness probe that verifies web process liveness.",
)
async def liveness_check() -> HealthResponse:
    """Return ok if FastAPI process is live."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness Check",
    description="Verifies infrastructure dependencies (PostgreSQL and pgvector).",
)
async def readiness_check(
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> ReadinessResponse:
    """Return readiness status based on database and vector store health."""
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


@router.get(
    "/info",
    response_model=SystemInfoResponse,
    summary="System Information",
    description="Returns public application metadata, active environment, and version.",
)
async def system_info(
    settings: Settings = Depends(get_settings),
) -> SystemInfoResponse:
    """Return application name, version, and environment."""
    return SystemInfoResponse(
        app_name=settings.APP_NAME,
        version=settings.VERSION,
        environment=settings.APP_ENV,
        debug=settings.DEBUG,
    )
