import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_active_user,
    get_incident_or_404,
)
from app.core.exceptions import ForbiddenException, ValidationException
from app.db.session import get_db
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.models.membership import OrganizationMembership
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.incidents import (
    EvidenceEventCreate,
    EvidenceEventResponse,
    IncidentCreate,
    IncidentResponse,
    TimelineEventResponse,
    TimelineResponse,
)
from app.services.incidents.service import IncidentService
from app.services.organizations.service import OrganizationService

logger = logging.getLogger("app.api.v1.incidents")

router = APIRouter(prefix="/incidents", tags=["Incidents & SRE Investigation"])


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Incident",
    description="Creates a new incident scoped to the target organization with tenant isolation.",
)
async def create_incident(
    payload: IncidentCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> IncidentResponse:
    # 1. Resolve Target Organization
    org_id = payload.organization_id
    if not org_id:
        memberships = await OrganizationService.get_user_memberships(session, current_user.id)
        if not memberships:
            raise ValidationException(message="User does not belong to any organization.")
        org_id = memberships[0].organization_id

    # 2. Enforce Tenant Membership Authorization
    membership = await OrganizationService.get_membership(session, org_id, current_user.id)
    if membership is None:
        raise ForbiddenException(message="Access denied: You do not belong to this organization.")

    # 3. Create Incident
    incident = await IncidentService.create_incident(
        session=session,
        organization_id=org_id,
        user_id=current_user.id,
        payload=payload,
    )
    return IncidentResponse.model_validate(incident)


@router.get(
    "",
    response_model=PaginatedResponse[IncidentResponse],
    summary="List Incidents",
    description="List incidents belonging to the caller's organization with optional filters and pagination.",
)
async def list_incidents(
    current_user: Annotated[User, Depends(get_current_active_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    organization_id: str | None = Query(
        default=None, description="Target organization ID (defaults to primary)"
    ),
    incident_status: IncidentStatus | None = Query(default=None, alias="status"),
    severity: IncidentSeverity | None = Query(default=None),
    service_name: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[IncidentResponse]:
    # 1. Resolve & verify organization
    org_id = organization_id
    if not org_id:
        memberships = await OrganizationService.get_user_memberships(session, current_user.id)
        if not memberships:
            raise ValidationException(message="User does not belong to any organization.")
        org_id = memberships[0].organization_id

    membership = await OrganizationService.get_membership(session, org_id, current_user.id)
    if membership is None:
        raise ForbiddenException(message="Access denied: You do not belong to this organization.")

    # 2. Query Incidents
    items, total = await IncidentService.list_incidents(
        session=session,
        organization_id=org_id,
        status=incident_status,
        severity=severity,
        service_name=service_name,
        environment=environment,
        limit=limit,
        offset=offset,
    )

    return PaginatedResponse(
        items=[IncidentResponse.model_validate(inc) for inc in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
    summary="Get Incident Detail",
    description="Retrieve an incident by ID. Enforces strict tenant isolation.",
)
async def get_incident(
    incident_data: Annotated[
        tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)
    ],
) -> IncidentResponse:
    incident, _ = incident_data
    resp = IncidentResponse.model_validate(incident)
    if incident.evidence_events:
        resp.evidence_count = len(incident.evidence_events)
    return resp


@router.post(
    "/{incident_id}/evidence",
    response_model=EvidenceEventResponse,
    summary="Ingest Evidence Event",
    description=(
        "Ingests an evidence event (log, alert, metric, deployment, git commit, etc.). "
        "Idempotent: if deduplication_key already exists for this incident, returns existing record."
    ),
)
async def ingest_evidence(
    incident_id: str,
    payload: EvidenceEventCreate,
    response: Response,
    incident_data: Annotated[
        tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> EvidenceEventResponse:
    _incident, membership = incident_data
    evidence, is_new = await IncidentService.create_evidence_event(
        session=session,
        incident_id=incident_id,
        organization_id=membership.organization_id,
        payload=payload,
    )
    if is_new:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK
        response.headers["X-TracePilot-Duplicate"] = "true"

    return EvidenceEventResponse.model_validate(evidence)


@router.get(
    "/{incident_id}/evidence",
    response_model=PaginatedResponse[EvidenceEventResponse],
    summary="List Raw Incident Evidence",
    description="List raw evidence events attached to an incident with optional source filtering.",
)
async def list_evidence(
    incident_id: str,
    incident_data: Annotated[
        tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
    source_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PaginatedResponse[EvidenceEventResponse]:
    _incident, membership = incident_data
    items, total = await IncidentService.list_evidence(
        session=session,
        incident_id=incident_id,
        organization_id=membership.organization_id,
        source_type=source_type,
        limit=limit,
        offset=offset,
    )
    return PaginatedResponse(
        items=[EvidenceEventResponse.model_validate(ev) for ev in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{incident_id}/timeline",
    response_model=TimelineResponse,
    summary="Get Deterministic Incident Timeline",
    description="Retrieve chronologically ordered events (event_timestamp ASC, tie-breaker id ASC).",
)
async def get_timeline(
    incident_id: str,
    incident_data: Annotated[
        tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TimelineResponse:
    _incident, membership = incident_data
    items, total = await IncidentService.get_timeline(
        session=session,
        incident_id=incident_id,
        organization_id=membership.organization_id,
        limit=limit,
        offset=offset,
    )
    return TimelineResponse(
        incident_id=incident_id,
        total_events=total,
        events=[TimelineEventResponse.model_validate(ev) for ev in items],
        limit=limit,
        offset=offset,
    )
