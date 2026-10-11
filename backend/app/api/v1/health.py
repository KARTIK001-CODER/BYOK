from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.health import (
    HealthResponse,
    ReadinessResponse,
    SystemInfoResponse,
    WorkerStatus,
)
from app.services.health import HealthService

router = APIRouter(tags=["Health & Readiness"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness Check",
    description="Lightweight liveness probe that verifies web process liveness.",
)
@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Liveness Check (Kubernetes probe standard)",
    description="Lightweight liveness probe that verifies web process liveness.",
)
async def liveness_check() -> HealthResponse:
    """Return ok if FastAPI process is live."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness Check",
    description="Verifies infrastructure dependencies (PostgreSQL and pgvector) with bounded timeouts.",
)
@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness Check (Kubernetes probe standard)",
    description="Verifies infrastructure dependencies (PostgreSQL and pgvector) with bounded timeouts.",
)
async def readiness_check(
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> ReadinessResponse:
    """Return operational readiness status based on bounded dependency checks."""
    readiness = await HealthService.check_full_readiness(session)

    if readiness.status == "unhealthy":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return readiness


@router.get(
    "/health/worker",
    response_model=WorkerStatus,
    summary="Worker Operational Status",
    description="Check the background investigation worker heartbeat and job processing lag.",
)
async def worker_status_check(
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> WorkerStatus:
    """Return worker operational state and heartbeat."""
    readiness = await HealthService.check_full_readiness(session)
    if readiness.worker.status in ("stale", "unknown"):
        # Worker degraded but does not necessarily fail API
        response.status_code = status.HTTP_200_OK
    return readiness.worker


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
        features={
            "remediation_proposals": True,
            "remediation_approval_workflow": True,
            "remediation_audit_trail": True,
            "remediation_local_dry_run": True,
            "remediation_execution_enabled": False,  # Safety boundary
        },
    )
