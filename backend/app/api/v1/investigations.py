from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_hypothesis_or_404,
    get_incident_or_404,
    get_investigation_job_or_404,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.models.incident import Incident
from app.models.investigation import InvestigationJob, RootCauseHypothesis
from app.models.membership import OrganizationMembership
from app.schemas.common import PaginatedResponse
from app.schemas.investigations import (
    EvidenceLinkResponse,
    HypothesisResponse,
    InvestigationCreate,
    InvestigationJobResponse,
)
from app.services.investigations.engine import execute_claimed_job
from app.services.investigations.service import InvestigationService

router = APIRouter(tags=["Investigations & Root-Cause Hypotheses"])


def _hypothesis_to_response(hyp: RootCauseHypothesis) -> HypothesisResponse:
    supporting = [
        EvidenceLinkResponse.model_validate(link)
        for link in hyp.evidence_links
        if link.link_type == "supports"
    ]
    contradicting = [
        EvidenceLinkResponse.model_validate(link)
        for link in hyp.evidence_links
        if link.link_type == "contradicts"
    ]
    resp = HypothesisResponse.model_validate(hyp)
    resp.supporting_evidence = supporting
    resp.contradicting_evidence = contradicting
    return resp


@router.post(
    "/incidents/{incident_id}/investigations",
    response_model=InvestigationJobResponse,
    summary="Request Incident Investigation",
    description=(
        "Creates (or reuses, on duplicate requests) a durable investigation job and "
        "executes it. Poll GET /investigations/{job_id} for progress."
    ),
)
async def request_investigation(
    payload: InvestigationCreate,
    response: Response,
    incident_data: Annotated[tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InvestigationJobResponse:
    _incident, membership = incident_data
    settings = get_settings()

    job, created = await InvestigationService.create_job(
        session=session,
        incident=_incident,
        organization_id=membership.organization_id,
        idempotency_key=payload.idempotency_key,
        app_version=settings.VERSION,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["X-TracePilot-Duplicate"] = "true"
        return InvestigationJobResponse.model_validate(job)

    response.status_code = status.HTTP_201_CREATED
    claimed = await InvestigationService.claim_job(session, job.id, membership.organization_id)
    if claimed is None:  # lost a concurrent claim race — return current state
        current = await InvestigationService.get_job(session, job.id, membership.organization_id)
        assert current is not None
        return InvestigationJobResponse.model_validate(current)
    finished = await execute_claimed_job(session, claimed)
    return InvestigationJobResponse.model_validate(finished)


@router.get(
    "/incidents/{incident_id}/investigations",
    response_model=PaginatedResponse[InvestigationJobResponse],
    summary="List Incident Investigations",
)
async def list_investigations(
    incident_id: str,
    incident_data: Annotated[tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[InvestigationJobResponse]:
    _incident, membership = incident_data
    items, total = await InvestigationService.list_jobs(
        session, incident_id, membership.organization_id, limit=limit, offset=offset
    )
    return PaginatedResponse(
        items=[InvestigationJobResponse.model_validate(j) for j in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/investigations/{job_id}",
    response_model=InvestigationJobResponse,
    summary="Get Investigation Status",
    description="Poll this endpoint for durable job progress (stage, progress, status).",
)
async def get_investigation(
    job_data: Annotated[
        tuple[InvestigationJob, OrganizationMembership], Depends(get_investigation_job_or_404)
    ],
) -> InvestigationJobResponse:
    job, _ = job_data
    return InvestigationJobResponse.model_validate(job)


@router.post(
    "/investigations/{job_id}/cancel",
    response_model=InvestigationJobResponse,
    summary="Cancel Queued Investigation",
    description=(
        "Cancels a queued job. Running or terminal jobs cannot be cancelled (409), "
        "including repeated cancellation of an already-cancelled job. A job claimed "
        "by a worker between read and cancel is refused, never silently cancelled "
        "mid-run. In-flight provider generation cannot be physically interrupted; "
        "results are only persisted if the job is still running when generation ends."
    ),
)
async def cancel_investigation(
    job_data: Annotated[
        tuple[InvestigationJob, OrganizationMembership], Depends(get_investigation_job_or_404)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> InvestigationJobResponse:
    job, _ = job_data
    cancelled = await InvestigationService.cancel_job(session, job)
    return InvestigationJobResponse.model_validate(cancelled)


@router.get(
    "/investigations/{job_id}/hypotheses",
    response_model=PaginatedResponse[HypothesisResponse],
    summary="List Investigation Hypotheses",
)
async def list_hypotheses(
    job_id: str,
    job_data: Annotated[
        tuple[InvestigationJob, OrganizationMembership], Depends(get_investigation_job_or_404)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[HypothesisResponse]:
    _job, membership = job_data
    items, total = await InvestigationService.list_hypotheses(
        session, job_id, membership.organization_id, limit=limit, offset=offset
    )
    return PaginatedResponse(
        items=[_hypothesis_to_response(h) for h in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/hypotheses/{hypothesis_id}",
    response_model=HypothesisResponse,
    summary="Get Hypothesis Detail",
)
async def get_hypothesis(
    hypothesis_data: Annotated[
        tuple[RootCauseHypothesis, OrganizationMembership], Depends(get_hypothesis_or_404)
    ],
) -> HypothesisResponse:
    hyp, _ = hypothesis_data
    return _hypothesis_to_response(hyp)
