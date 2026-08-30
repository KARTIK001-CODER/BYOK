from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ROLE_HIERARCHY, get_embedding_job_or_404
from app.core.exceptions import ForbiddenException
from app.db.session import get_db
from app.models.embedding_job import EmbeddingJob
from app.models.membership import OrganizationMembership, OrganizationRole
from app.schemas.embeddings import EmbeddingJobResponse
from app.services.embeddings.service import EmbeddingService

router = APIRouter(prefix="/embedding-jobs", tags=["Vector Embeddings"])


@router.get(
    "/{job_id}",
    response_model=EmbeddingJobResponse,
    summary="Get Embedding Job Status",
    description="Retrieves the progress, processed chunk count, and status for an embedding job.",
)
async def get_embedding_job(
    job_and_membership: tuple[EmbeddingJob, OrganizationMembership] = Depends(
        get_embedding_job_or_404
    ),
) -> EmbeddingJobResponse:
    job, _ = job_and_membership
    return EmbeddingJobResponse.model_validate(job)


@router.post(
    "/{job_id}/retry",
    response_model=EmbeddingJobResponse,
    summary="Retry Embedding Job",
    description="Retries a failed embedding job for missing chunks (requires ADMIN or OWNER).",
)
async def retry_embedding_job(
    job_and_membership: tuple[EmbeddingJob, OrganizationMembership] = Depends(
        get_embedding_job_or_404
    ),
    session: AsyncSession = Depends(get_db),
) -> EmbeddingJobResponse:
    job, membership = job_and_membership

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.ADMIN]:
        raise ForbiddenException(
            message="Insufficient permissions: Retrying embedding requires ADMIN or OWNER role."
        )

    retried_job = await EmbeddingService.retry_job(
        session=session,
        job_id=job.id,
        organization_id=membership.organization_id,
    )
    return EmbeddingJobResponse.model_validate(retried_job)
