from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_incident_or_404,
    get_remediation_proposal_or_404,
)
from app.core.exceptions import ForbiddenException, NotFoundException
from app.core.logging import get_request_id
from app.db.session import get_db
from app.models.incident import Incident
from app.models.investigation import HypothesisStatus, RootCauseHypothesis
from app.models.membership import OrganizationMembership
from app.models.remediation import RemediationProposal
from app.models.user import User
from app.schemas.remediations import (
    RemediationApprovalCreate,
    RemediationApprovalListResponse,
    RemediationApprovalResponse,
    RemediationAuditEventListResponse,
    RemediationAuditEventResponse,
    RemediationAuditExportResponse,
    RemediationDryRunResponse,
    RemediationProposalCreate,
    RemediationProposalGenerateRequest,
    RemediationProposalListResponse,
    RemediationProposalResponse,
    RemediationRejectionCreate,
    RemediationStatusTransitionRequest,
    RiskAssessmentDetails,
)
from app.schemas.sandbox import (
    SandboxScenarioMetadata,
    SandboxSimulationRequest,
    SandboxSimulationResponse,
)
from app.services.organizations.service import OrganizationService
from app.services.remediation.sandbox import TracePilotSandboxSimulator
from app.services.remediation.service import RemediationService

router = APIRouter(tags=["Remediation & Risk Assessment"])


@router.post(
    "/incidents/{incident_id}/remediations",
    response_model=RemediationProposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Remediation Proposal",
    description="Manually create a structured, non-executable remediation proposal for an incident.",
)
async def create_remediation_proposal(
    incident_id: str,
    payload: RemediationProposalCreate,
    incident_data: Annotated[tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RemediationProposalResponse:
    _ = incident_id
    incident, membership = incident_data
    proposal = await RemediationService.create_proposal(
        session=session,
        incident=incident,
        organization_id=membership.organization_id,
        payload=payload,
        user_id=current_user.id,
        request_id=get_request_id(),
    )
    return RemediationProposalResponse.model_validate(proposal)


@router.post(
    "/incidents/{incident_id}/remediations/generate",
    response_model=RemediationProposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate Remediation Proposal from Investigation",
    description="Synthesizes a structured remediation proposal from root-cause hypotheses.",
)
async def generate_remediation_proposal(
    incident_id: str,
    payload: RemediationProposalGenerateRequest,
    incident_data: Annotated[tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RemediationProposalResponse:
    _ = incident_id
    incident, membership = incident_data

    target_hyp_id = payload.hypothesis_id
    if not target_hyp_id:
        # Find top supported hypothesis for this incident
        h_stmt = (
            select(RootCauseHypothesis)
            .where(
                RootCauseHypothesis.incident_id == incident.id,
                RootCauseHypothesis.organization_id == membership.organization_id,
                RootCauseHypothesis.status == HypothesisStatus.SUPPORTED.value,
            )
            .order_by(RootCauseHypothesis.groundedness_score.desc().nullslast())
            .limit(1)
        )
        top_hyp = (await session.execute(h_stmt)).scalar_one_or_none()
        if top_hyp is None:
            # Fall back to any hypothesis
            h_stmt_any = (
                select(RootCauseHypothesis)
                .where(
                    RootCauseHypothesis.incident_id == incident.id,
                    RootCauseHypothesis.organization_id == membership.organization_id,
                )
                .limit(1)
            )
            top_hyp = (await session.execute(h_stmt_any)).scalar_one_or_none()

        if top_hyp is None:
            raise NotFoundException("No investigation hypotheses available to synthesize remediation.")
        target_hyp_id = top_hyp.id

    proposal = await RemediationService.generate_proposal_from_hypothesis(
        session=session,
        incident=incident,
        organization_id=membership.organization_id,
        hypothesis_id=target_hyp_id,
        user_id=current_user.id,
        focus=payload.focus,
        request_id=get_request_id(),
    )
    return RemediationProposalResponse.model_validate(proposal)


@router.get(
    "/incidents/{incident_id}/remediations",
    response_model=RemediationProposalListResponse,
    summary="List Incident Remediation Proposals",
    description="List all remediation proposals for an incident, optionally filtered by status.",
)
async def list_remediation_proposals(
    incident_id: str,
    incident_data: Annotated[tuple[Incident, OrganizationMembership], Depends(get_incident_or_404)],
    session: Annotated[AsyncSession, Depends(get_db)],
    status: str | None = Query(default=None, description="Optional status filter"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RemediationProposalListResponse:
    _ = incident_id
    _incident, membership = incident_data
    items, total = await RemediationService.list_proposals(
        session=session,
        incident_id=incident_id,
        organization_id=membership.organization_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return RemediationProposalListResponse(
        items=[RemediationProposalResponse.model_validate(p) for p in items],
        total=total,
    )


@router.get(
    "/remediations",
    response_model=RemediationProposalListResponse,
    summary="List Organization Remediation Proposals",
    description="List remediation proposals for the caller's organization with optional status and incident filters.",
)
async def list_organization_remediations(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
    organization_id: str | None = Query(default=None, description="Optional target organization ID"),
    incident_id: str | None = Query(default=None, description="Optional incident ID filter"),
    status: str | None = Query(default=None, description="Optional status filter"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RemediationProposalListResponse:
    org_id = organization_id
    if not org_id:
        memberships = await OrganizationService.get_user_memberships(session, current_user.id)
        if not memberships:
            raise NotFoundException("User does not belong to any organization.")
        org_id = memberships[0].organization_id

    membership = await OrganizationService.get_membership(session, org_id, current_user.id)
    if membership is None:
        raise ForbiddenException("Access denied: You do not belong to this organization.")

    items, total = await RemediationService.list_proposals(
        session=session,
        organization_id=org_id,
        incident_id=incident_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return RemediationProposalListResponse(
        items=[RemediationProposalResponse.model_validate(p) for p in items],
        total=total,
    )


@router.get(
    "/remediations/sandbox/scenarios",
    response_model=list[SandboxScenarioMetadata],
    summary="List Deterministic Sandbox Scenarios",
    description="Returns metadata for all available local sandbox simulation scenarios.",
)
async def list_sandbox_scenarios(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[SandboxScenarioMetadata]:
    _ = current_user
    return TracePilotSandboxSimulator.list_scenarios()


@router.post(
    "/remediations/sandbox/simulate",
    response_model=SandboxSimulationResponse,
    summary="Run Deterministic Sandbox Simulation",
    description=(
        "Executes synthetic remediation scenarios locally and deterministically. "
        "Strictly non-executing: no infrastructure APIs or shell commands are executed."
    ),
)
async def run_sandbox_simulation(
    current_user: Annotated[User, Depends(get_current_user)],
    payload: SandboxSimulationRequest | None = None,
) -> SandboxSimulationResponse:
    _ = current_user
    scenario_id = payload.scenario_id if payload else None
    if scenario_id and scenario_id.upper() != "ALL":
        result = TracePilotSandboxSimulator.simulate_scenario(scenario_id)
        return SandboxSimulationResponse(
            results=[result],
            total_scenarios=1,
            passed_scenarios=1 if result.passed else 0,
            all_passed=result.passed,
            is_simulation=True,
        )
    return TracePilotSandboxSimulator.simulate_all()


@router.get(
    "/remediations/{remediation_id}",
    response_model=RemediationProposalResponse,
    summary="Get Remediation Proposal",
    description="Retrieve detailed remediation proposal by ID.",
)
async def get_remediation_proposal(
    remediation_id: str,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
) -> RemediationProposalResponse:
    _ = remediation_id
    proposal, _membership = proposal_data
    return RemediationProposalResponse.model_validate(proposal)


@router.patch(
    "/remediations/{remediation_id}/status",
    response_model=RemediationProposalResponse,
    summary="Transition Remediation Status",
    description="Transition remediation proposal lifecycle state.",
)
async def transition_remediation_status(
    remediation_id: str,
    payload: RemediationStatusTransitionRequest,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RemediationProposalResponse:
    _ = remediation_id
    proposal, membership = proposal_data
    updated = await RemediationService.transition_status(
        session=session,
        proposal=proposal,
        target_status=payload.target_status,
        user_id=current_user.id,
        actor_role=membership.role.value,
        review_notes=payload.review_notes,
        rejection_reason=payload.rejection_reason,
        superseded_by_id=payload.superseded_by_id,
        request_id=get_request_id(),
    )
    return RemediationProposalResponse.model_validate(updated)


@router.post(
    "/remediations/{remediation_id}/risk-assessment",
    response_model=RiskAssessmentDetails,
    summary="Re-evaluate Proposal Risk Assessment",
    description="Recalculate deterministic risk assessment breakdown for this proposal.",
)
async def reevaluate_risk_assessment(
    remediation_id: str,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RiskAssessmentDetails:
    _ = remediation_id
    proposal, membership = proposal_data
    details = await RemediationService.recalculate_risk(
        session=session,
        proposal=proposal,
        user_id=current_user.id,
        actor_role=membership.role.value,
        request_id=get_request_id(),
    )
    return details


@router.post(
    "/remediations/{remediation_id}/approve",
    response_model=RemediationApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve Remediation Proposal",
    description="Record an authorized human approval decision under organizational policy.",
)
async def approve_remediation_proposal(
    remediation_id: str,
    payload: RemediationApprovalCreate,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RemediationApprovalResponse:
    _ = remediation_id
    proposal, membership = proposal_data
    approval_record = await RemediationService.approve_proposal(
        session=session,
        proposal_id=proposal.id,
        organization_id=membership.organization_id,
        reviewer_user=current_user,
        reviewer_membership=membership,
        rationale=payload.rationale,
        request_id=get_request_id(),
    )
    return RemediationApprovalResponse.model_validate(approval_record)


@router.post(
    "/remediations/{remediation_id}/reject",
    response_model=RemediationApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject Remediation Proposal",
    description="Record a human rejection decision and transition proposal to rejected.",
)
async def reject_remediation_proposal(
    remediation_id: str,
    payload: RemediationRejectionCreate,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RemediationApprovalResponse:
    _ = remediation_id
    proposal, membership = proposal_data
    rejection_record = await RemediationService.reject_proposal(
        session=session,
        proposal_id=proposal.id,
        organization_id=membership.organization_id,
        reviewer_user=current_user,
        reviewer_membership=membership,
        rationale=payload.rationale,
        request_id=get_request_id(),
    )
    return RemediationApprovalResponse.model_validate(rejection_record)


@router.get(
    "/remediations/{remediation_id}/approvals",
    response_model=RemediationApprovalListResponse,
    summary="List Approval Decisions",
    description="Retrieve append-only history of approval and rejection decisions for this proposal.",
)
async def list_remediation_approvals(
    remediation_id: str,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RemediationApprovalListResponse:
    _ = remediation_id
    proposal, membership = proposal_data
    items, total = await RemediationService.list_approvals(
        session=session,
        proposal_id=proposal.id,
        organization_id=membership.organization_id,
        limit=limit,
        offset=offset,
    )
    return RemediationApprovalListResponse(
        items=[RemediationApprovalResponse.model_validate(r) for r in items],
        total=total,
    )


@router.get(
    "/remediations/{remediation_id}/audit",
    response_model=RemediationAuditEventListResponse,
    summary="List Remediation Audit Events",
    description="Retrieve immutable lifecycle and governance audit events for this proposal.",
)
async def list_remediation_audit_events(
    remediation_id: str,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> RemediationAuditEventListResponse:
    _ = remediation_id
    proposal, membership = proposal_data
    items, total = await RemediationService.list_audit_events(
        session=session,
        proposal_id=proposal.id,
        organization_id=membership.organization_id,
        limit=limit,
        offset=offset,
    )
    return RemediationAuditEventListResponse(
        items=[RemediationAuditEventResponse.model_validate(e) for e in items],
        total=total,
    )


@router.post(
    "/remediations/{remediation_id}/dry-run",
    response_model=RemediationDryRunResponse,
    summary="Dry-Run Policy Validation",
    description=(
        "Local, deterministic policy evaluation. Validates lifecycle, schema, risk, and role requirements "
        "without contacting external infrastructure or executing commands."
    ),
)
async def dry_run_remediation_policy(
    remediation_id: str,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RemediationDryRunResponse:
    _ = remediation_id
    proposal, membership = proposal_data
    return RemediationService.dry_run_policy(
        proposal=proposal,
        reviewer_user=current_user,
        reviewer_membership=membership,
    )


@router.get(
    "/remediations/{remediation_id}/export",
    response_model=RemediationAuditExportResponse,
    summary="Export Remediation Audit Report",
    description=(
        "Exports a stable JSON audit package for a remediation proposal, including decision history, "
        "policy dry-run validation, evidence references, and groundedness metadata. Enforces tenant isolation."
    ),
)
async def export_remediation_audit(
    remediation_id: str,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RemediationAuditExportResponse:
    _ = remediation_id
    proposal, membership = proposal_data
    return await RemediationService.export_audit_report(
        session=session,
        proposal=proposal,
        reviewer_user=current_user,
        reviewer_membership=membership,
    )


@router.post(
    "/remediations/{remediation_id}/execute",
    summary="Execute Remediation (Forbidden)",
    description="Execution of remediation actions is strictly forbidden (Milestone 5A & 5B).",
)
async def execute_remediation(
    remediation_id: str,
    proposal_data: Annotated[
        tuple[RemediationProposal, OrganizationMembership],
        Depends(get_remediation_proposal_or_404),
    ],
) -> None:
    _ = remediation_id
    _ = proposal_data
    raise ForbiddenException(
        message=(
            "Automated execution of remediation actions is strictly forbidden. "
            "TracePilot proposals are non-executable advisory specifications. "
            "Approval only confirms organizational policy compliance (Milestone 5B)."
        ),
        details={"is_executable": False, "requires_human_approval": True},
    )
