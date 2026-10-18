from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_hypothesis_or_404,
    get_incident_or_404,
    get_investigation_job_or_404,
)
from app.core.config import get_settings
from app.db.session import get_db, get_session_factory
from app.models.incident import Incident
from app.models.investigation import (
    HypothesisConfidence,
    InvestigationJob,
    RootCauseHypothesis,
)
from app.models.membership import OrganizationMembership
from app.schemas.common import PaginatedResponse
from app.schemas.investigations import (
    EvidenceLinkResponse,
    HypothesisResponse,
    InvestigationCreate,
    InvestigationJobResponse,
)
from app.services.investigations.service import InvestigationService
from app.services.investigations.streaming import stream_investigation_events

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
    resp.model_confidence = HypothesisConfidence(hyp.confidence) if hyp.confidence else None
    resp.model_confidence_score = hyp.confidence_score
    resp.groundedness_score = hyp.groundedness_score
    resp.system_confidence = hyp.system_confidence
    resp.system_confidence_score = hyp.system_confidence_score
    resp.groundedness_status = hyp.groundedness_status
    resp.assessment_version = hyp.assessment_version
    resp.assessment_details = hyp.assessment_details
    if hyp.assessment_details and "confidence_note" in hyp.assessment_details:
        resp.confidence_note = hyp.assessment_details["confidence_note"]
    return resp


@router.post(
    "/incidents/{incident_id}/investigations",
    response_model=InvestigationJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request Incident Investigation",
    description=(
        "Creates (or reuses, on duplicate requests) a durable investigation job. "
        "Returns HTTP 202 Accepted with a queued job for asynchronous execution "
        "by the background worker. Poll GET /investigations/{job_id} or connect "
        "to the SSE stream for progress."
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
        provider=payload.provider,
        model=payload.model,
        app_version=settings.VERSION,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["X-TracePilot-Duplicate"] = "true"
        return InvestigationJobResponse.model_validate(job)

    response.status_code = status.HTTP_202_ACCEPTED
    return InvestigationJobResponse.model_validate(job)


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


@router.get(
    "/investigations/{job_id}/stream",
    summary="Stream Investigation Progress (SSE)",
    description=(
        "Streams real-time progress events for a durable investigation job via Server-Sent Events (SSE). "
        "Emits investigation.connected, investigation.snapshot, investigation.progress, and terminal events "
        "(investigation.completed, investigation.failed, investigation.cancelled). "
        "Closes cleanly on terminal state. If client disconnects, the investigation continues undisturbed in PostgreSQL."
    ),
)
async def stream_investigation(
    request: Request,
    job_data: Annotated[
        tuple[InvestigationJob, OrganizationMembership], Depends(get_investigation_job_or_404)
    ],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> StreamingResponse:
    job, membership = job_data
    event_generator = stream_investigation_events(
        request=request,
        job_id=job.id,
        organization_id=membership.organization_id,
        session_factory=session_factory,
    )
    return StreamingResponse(
        event_generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
