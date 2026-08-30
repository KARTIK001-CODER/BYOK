from fastapi import APIRouter, Depends

from app.api.deps import get_ingestion_job_or_404
from app.models.ingestion_job import IngestionJob
from app.models.membership import OrganizationMembership
from app.schemas.ingestion import IngestionJobResponse

router = APIRouter(prefix="/ingestion-jobs", tags=["Document Ingestion"])


@router.get(
    "/{job_id}",
    response_model=IngestionJobResponse,
    summary="Get Ingestion Job Status",
    description="Retrieves the processing status, attempts, and timestamps for an ingestion job.",
)
async def get_ingestion_job(
    job_and_membership: tuple[IngestionJob, OrganizationMembership] = Depends(
        get_ingestion_job_or_404
    ),
) -> IngestionJobResponse:
    job, _ = job_and_membership
    return IngestionJobResponse.model_validate(job)
