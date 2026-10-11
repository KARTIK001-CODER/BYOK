import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, NotFoundException, ValidationException
from app.models.incident import Incident
from app.models.investigation import InvestigationJob, RootCauseHypothesis
from app.models.membership import OrganizationMembership
from app.models.remediation import (
    ApprovalDecision,
    RemediationActionType,
    RemediationApproval,
    RemediationAuditEvent,
    RemediationAuditEventType,
    RemediationProposal,
    RemediationRiskLevel,
    RemediationStatus,
)
from app.models.user import User
from app.schemas.remediations import (
    RemediationApprovalResponse,
    RemediationAuditEventResponse,
    RemediationAuditExportResponse,
    RemediationDryRunResponse,
    RemediationProposalCreate,
    RiskAssessmentDetails,
)
from app.services.remediation.policy import ApprovalPolicyService
from app.services.remediation.risk import RiskEvaluator

logger = logging.getLogger("app.services.remediation.service")

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    RemediationStatus.DRAFT.value: {
        RemediationStatus.PROPOSED.value,
        RemediationStatus.CANCELLED.value,
    },
    RemediationStatus.PROPOSED.value: {
        RemediationStatus.REVIEWED.value,
        RemediationStatus.APPROVED.value,
        RemediationStatus.REJECTED.value,
        RemediationStatus.SUPERSEDED.value,
        RemediationStatus.CANCELLED.value,
        RemediationStatus.EXPIRED.value,
    },
    RemediationStatus.REVIEWED.value: {
        RemediationStatus.APPROVED.value,
        RemediationStatus.REJECTED.value,
        RemediationStatus.SUPERSEDED.value,
        RemediationStatus.CANCELLED.value,
        RemediationStatus.EXPIRED.value,
    },
    RemediationStatus.APPROVED.value: {
        RemediationStatus.PROPOSED.value,  # On mutation / invalidation
        RemediationStatus.SUPERSEDED.value,
        RemediationStatus.CANCELLED.value,
    },
    RemediationStatus.REJECTED.value: set(),
    RemediationStatus.SUPERSEDED.value: set(),
    RemediationStatus.CANCELLED.value: set(),
    RemediationStatus.EXPIRED.value: set(),
}


class RemediationService:
    """Manages TracePilot remediation proposals, risk evaluation, and lifecycle transitions."""

    @classmethod
    async def record_audit_event(
        cls,
        session: AsyncSession,
        organization_id: str,
        proposal_id: str,
        event_type: str,
        proposal_version: int,
        actor_user_id: str | None = None,
        actor_role: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> RemediationAuditEvent:
        """Append an immutable audit record for proposal events."""
        event = RemediationAuditEvent(
            organization_id=organization_id,
            remediation_proposal_id=proposal_id,
            event_type=event_type,
            proposal_version=proposal_version,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            from_status=from_status,
            to_status=to_status,
            details=details,
            request_id=request_id,
        )
        session.add(event)
        return event

    @classmethod
    async def create_proposal(
        cls,
        session: AsyncSession,
        incident: Incident,
        organization_id: str,
        payload: RemediationProposalCreate,
        user_id: str | None = None,
        request_id: str | None = None,
    ) -> RemediationProposal:
        if incident.organization_id != organization_id:
            raise NotFoundException("Incident not found.")

        # Hard safety validation: reject any execution attempt
        if payload.is_executable:
            raise ValidationException("Remediation proposals cannot be marked as executable.")

        hypothesis: RootCauseHypothesis | None = None
        if payload.hypothesis_id:
            h_stmt = select(RootCauseHypothesis).where(
                RootCauseHypothesis.id == payload.hypothesis_id,
                RootCauseHypothesis.organization_id == organization_id,
                RootCauseHypothesis.incident_id == incident.id,
            )
            hypothesis = (await session.execute(h_stmt)).scalar_one_or_none()
            if hypothesis is None:
                raise NotFoundException("Linked root cause hypothesis not found for this incident.")

        job: InvestigationJob | None = None
        if payload.investigation_job_id:
            j_stmt = select(InvestigationJob).where(
                InvestigationJob.id == payload.investigation_job_id,
                InvestigationJob.organization_id == organization_id,
                InvestigationJob.incident_id == incident.id,
            )
            job = (await session.execute(j_stmt)).scalar_one_or_none()
            if job is None:
                raise NotFoundException("Linked investigation job not found for this incident.")

        # Sanitize action items: force non-executable and required human approval
        sanitized_actions: list[dict[str, Any]] = []
        for act in payload.actions:
            act_dict = act.model_dump()
            act_dict["is_executable"] = False
            act_dict["requires_human_approval"] = True
            sanitized_actions.append(act_dict)

        # Evaluate risk deterministically
        risk_details = RiskEvaluator.evaluate(
            actions=sanitized_actions,
            target_incident_severity=incident.severity,
            hypothesis=hypothesis,
        )

        proposal = RemediationProposal(
            incident_id=incident.id,
            organization_id=organization_id,
            hypothesis_id=hypothesis.id if hypothesis else None,
            investigation_job_id=job.id if job else None,
            title=payload.title,
            description=payload.description,
            status=RemediationStatus.PROPOSED.value,
            risk_level=risk_details.overall_risk_level.value,
            risk_assessment=risk_details.model_dump(),
            actions=sanitized_actions,
            is_executable=False,
            rollback_plan=payload.rollback_plan,
            estimated_impact=payload.estimated_impact,
            mitigation_rationale=payload.mitigation_rationale,
            created_by_user_id=user_id,
            version=1,
        )

        session.add(proposal)
        await session.flush()

        await cls.record_audit_event(
            session=session,
            organization_id=organization_id,
            proposal_id=proposal.id,
            event_type=RemediationAuditEventType.PROPOSAL_CREATED.value,
            proposal_version=proposal.version,
            actor_user_id=user_id,
            to_status=proposal.status,
            details={
                "title": proposal.title,
                "risk_level": proposal.risk_level,
                "action_count": len(proposal.actions),
            },
            request_id=request_id,
        )

        await session.commit()
        await session.refresh(proposal)
        return proposal

    @classmethod
    async def generate_proposal_from_hypothesis(
        cls,
        session: AsyncSession,
        incident: Incident,
        organization_id: str,
        hypothesis_id: str,
        user_id: str | None = None,
        focus: str | None = None,
        request_id: str | None = None,
    ) -> RemediationProposal:
        _ = focus
        h_stmt = select(RootCauseHypothesis).where(
            RootCauseHypothesis.id == hypothesis_id,
            RootCauseHypothesis.organization_id == organization_id,
            RootCauseHypothesis.incident_id == incident.id,
        )
        hypothesis = (await session.execute(h_stmt)).scalar_one_or_none()
        if hypothesis is None:
            raise NotFoundException("Root cause hypothesis not found for this incident.")

        claim_lower = f"{hypothesis.claim} {hypothesis.rationale}".lower()

        actions: list[dict[str, Any]] = []
        if "pool" in claim_lower or "connection" in claim_lower:
            title = f"Database Connection Pool Remediation for Incident {incident.title}"
            desc = (
                f"Mitigation plan for pool exhaustion hypothesis: '{hypothesis.claim}'. "
                "Expands connection pool headroom and recycles stale connections."
            )
            actions = [
                {
                    "step_number": 1,
                    "action_type": RemediationActionType.CONFIG_CHANGE.value,
                    "description": "Increase service database pool maximum connections from baseline to 50.",
                    "target_system": "Database Pool Config",
                    "command": "ALTER SYSTEM SET max_connections = 200;",
                    "parameters": {"max_connections": 200, "pool_size": 50},
                    "risk_level": RemediationRiskLevel.MEDIUM.value,
                    "reversible": True,
                    "requires_human_approval": True,
                    "is_executable": False,
                },
                {
                    "step_number": 2,
                    "action_type": RemediationActionType.SERVICE_RESTART.value,
                    "description": "Trigger rolling restart of application API pods to drop leaked idle connections.",
                    "target_system": "API Deployment",
                    "command": "kubectl rollout restart deployment/api-server",
                    "parameters": {"grace_period": 30},
                    "risk_level": RemediationRiskLevel.MEDIUM.value,
                    "reversible": True,
                    "requires_human_approval": True,
                    "is_executable": False,
                },
                {
                    "step_number": 3,
                    "action_type": RemediationActionType.MANUAL.value,
                    "description": "Verify active connection pool telemetry in monitoring dashboard.",
                    "target_system": "Telemetry & Metrics",
                    "command": None,
                    "parameters": {},
                    "risk_level": RemediationRiskLevel.LOW.value,
                    "reversible": True,
                    "requires_human_approval": False,
                    "is_executable": False,
                },
            ]
            rollback_plan = "Revert pool config to previous settings and re-apply rollout restart."
            estimated_impact = "Restores database client connectivity within 2-3 minutes."
        elif "memory" in claim_lower or "oom" in claim_lower:
            title = f"Memory / OOM Mitigation for Incident {incident.title}"
            desc = (
                f"Mitigation plan for memory exhaustion hypothesis: '{hypothesis.claim}'. "
                "Recycles exhausted workers and increases resource limits."
            )
            actions = [
                {
                    "step_number": 1,
                    "action_type": RemediationActionType.SCALE.value,
                    "description": "Increase container memory limits from 2Gi to 4Gi to halt OOM-kills.",
                    "target_system": "Kubernetes Resource Limits",
                    "command": "kubectl set resources deployment/worker --limits=memory=4Gi",
                    "parameters": {"memory_limit": "4Gi"},
                    "risk_level": RemediationRiskLevel.MEDIUM.value,
                    "reversible": True,
                    "requires_human_approval": True,
                    "is_executable": False,
                },
                {
                    "step_number": 2,
                    "action_type": RemediationActionType.SERVICE_RESTART.value,
                    "description": "Gracefully cycle workers to clear fragmented memory heaps.",
                    "target_system": "Worker Deployment",
                    "command": "kubectl rollout restart deployment/worker",
                    "parameters": {},
                    "risk_level": RemediationRiskLevel.MEDIUM.value,
                    "reversible": True,
                    "requires_human_approval": True,
                    "is_executable": False,
                },
            ]
            rollback_plan = "Restore original memory limit specifications."
            estimated_impact = "Eliminates OOMKilled restarts immediately."
        elif "deploy" in claim_lower or "git" in claim_lower or "commit" in claim_lower:
            title = f"Deployment Rollback Remediation for Incident {incident.title}"
            desc = (
                f"Mitigation plan for recent deployment regression: '{hypothesis.claim}'. "
                "Rolls back to the last known stable deployment revision."
            )
            actions = [
                {
                    "step_number": 1,
                    "action_type": RemediationActionType.ROLLBACK.value,
                    "description": "Roll back deployment to previous stable revision.",
                    "target_system": "Deployment Pipeline",
                    "command": "kubectl rollout undo deployment/api-server",
                    "parameters": {"target_revision": "previous"},
                    "risk_level": RemediationRiskLevel.HIGH.value,
                    "reversible": True,
                    "requires_human_approval": True,
                    "is_executable": False,
                },
                {
                    "step_number": 2,
                    "action_type": RemediationActionType.MANUAL.value,
                    "description": "Inspect error rate telemetry to confirm service recovery.",
                    "target_system": "Monitoring Dashboard",
                    "command": None,
                    "parameters": {},
                    "risk_level": RemediationRiskLevel.LOW.value,
                    "reversible": True,
                    "requires_human_approval": False,
                    "is_executable": False,
                },
            ]
            rollback_plan = "Re-deploy the target commit once hotfix is ready."
            estimated_impact = "Restores stable application binary and eliminates regressions."
        else:
            title = f"Standard Incident Remediation Proposal for {incident.title}"
            desc = (
                f"Proposed operational steps to mitigate hypothesis: '{hypothesis.claim}'."
            )
            actions = [
                {
                    "step_number": 1,
                    "action_type": RemediationActionType.SERVICE_RESTART.value,
                    "description": "Gracefully restart affected service pods to clear transient errors.",
                    "target_system": "Service Pods",
                    "command": "kubectl rollout restart deployment/service",
                    "parameters": {},
                    "risk_level": RemediationRiskLevel.MEDIUM.value,
                    "reversible": True,
                    "requires_human_approval": True,
                    "is_executable": False,
                },
                {
                    "step_number": 2,
                    "action_type": RemediationActionType.MANUAL.value,
                    "description": "Audit incoming error logs and verify system stability.",
                    "target_system": "Logging Telemetry",
                    "command": None,
                    "parameters": {},
                    "risk_level": RemediationRiskLevel.LOW.value,
                    "reversible": True,
                    "requires_human_approval": False,
                    "is_executable": False,
                },
            ]
            rollback_plan = "Manual SRE intervention if error rates do not improve."
            estimated_impact = "Recovers service availability."

        # Risk evaluation with groundedness integration
        risk_details = RiskEvaluator.evaluate(
            actions=actions,
            target_incident_severity=incident.severity,
            hypothesis=hypothesis,
        )

        proposal = RemediationProposal(
            incident_id=incident.id,
            organization_id=organization_id,
            hypothesis_id=hypothesis.id,
            investigation_job_id=hypothesis.investigation_job_id,
            title=title,
            description=desc,
            status=RemediationStatus.PROPOSED.value,
            risk_level=risk_details.overall_risk_level.value,
            risk_assessment=risk_details.model_dump(),
            actions=actions,
            is_executable=False,
            rollback_plan=rollback_plan,
            estimated_impact=estimated_impact,
            mitigation_rationale=f"Synthesized from root cause hypothesis: {hypothesis.claim}",
            created_by_user_id=user_id,
            version=1,
        )

        session.add(proposal)
        await session.flush()

        await cls.record_audit_event(
            session=session,
            organization_id=organization_id,
            proposal_id=proposal.id,
            event_type=RemediationAuditEventType.PROPOSAL_GENERATED.value,
            proposal_version=proposal.version,
            actor_user_id=user_id,
            to_status=proposal.status,
            details={
                "title": proposal.title,
                "hypothesis_id": hypothesis.id,
                "risk_level": proposal.risk_level,
            },
            request_id=request_id,
        )

        await session.commit()
        await session.refresh(proposal)
        return proposal

    @classmethod
    async def get_proposal(
        cls,
        session: AsyncSession,
        proposal_id: str,
        organization_id: str,
    ) -> RemediationProposal | None:
        stmt = (
            select(RemediationProposal)
            .where(
                RemediationProposal.id == proposal_id,
                RemediationProposal.organization_id == organization_id,
            )
            .options(
                selectinload(RemediationProposal.incident),
                selectinload(RemediationProposal.hypothesis),
            )
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def list_proposals(
        cls,
        session: AsyncSession,
        organization_id: str,
        incident_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RemediationProposal], int]:
        filters = [
            RemediationProposal.organization_id == organization_id,
        ]
        if incident_id:
            filters.append(RemediationProposal.incident_id == incident_id)
        if status:
            filters.append(RemediationProposal.status == status)

        count_stmt = select(func.count(RemediationProposal.id)).where(*filters)
        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(RemediationProposal)
            .where(*filters)
            .order_by(RemediationProposal.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = (await session.execute(stmt)).scalars().all()
        return list(items), total

    @classmethod
    async def transition_status(
        cls,
        session: AsyncSession,
        proposal: RemediationProposal,
        target_status: RemediationStatus,
        user_id: str | None = None,
        actor_role: str | None = None,
        review_notes: str | None = None,
        rejection_reason: str | None = None,
        superseded_by_id: str | None = None,
        request_id: str | None = None,
    ) -> RemediationProposal:
        curr = proposal.status
        allowed = ALLOWED_TRANSITIONS.get(curr, set())
        if target_status.value not in allowed:
            raise ConflictException(
                f"Invalid lifecycle transition from '{curr}' to '{target_status.value}'."
            )

        # Invalidate existing approval if transitioning away from approved
        was_approved = proposal.status == RemediationStatus.APPROVED.value
        if was_approved and target_status != RemediationStatus.APPROVED:
            proposal.version += 1
            proposal.approved_by_user_id = None
            proposal.approved_at = None
            await cls.record_audit_event(
                session=session,
                organization_id=proposal.organization_id,
                proposal_id=proposal.id,
                event_type=RemediationAuditEventType.APPROVAL_INVALIDATED.value,
                proposal_version=proposal.version,
                actor_user_id=user_id,
                actor_role=actor_role,
                from_status=curr,
                to_status=target_status.value,
                details={"reason": "Status changed away from approved."},
                request_id=request_id,
            )

        proposal.status = target_status.value
        if review_notes:
            proposal.review_notes = review_notes
        if rejection_reason:
            proposal.rejection_reason = rejection_reason
        if superseded_by_id:
            proposal.superseded_by_id = superseded_by_id

        await cls.record_audit_event(
            session=session,
            organization_id=proposal.organization_id,
            proposal_id=proposal.id,
            event_type=RemediationAuditEventType.STATUS_CHANGED.value,
            proposal_version=proposal.version,
            actor_user_id=user_id,
            actor_role=actor_role,
            from_status=curr,
            to_status=target_status.value,
            details={
                "review_notes": review_notes,
                "rejection_reason": rejection_reason,
                "superseded_by_id": superseded_by_id,
            },
            request_id=request_id,
        )

        await session.commit()
        await session.refresh(proposal)
        return proposal

    @classmethod
    async def recalculate_risk(
        cls,
        session: AsyncSession,
        proposal: RemediationProposal,
        user_id: str | None = None,
        actor_role: str | None = None,
        request_id: str | None = None,
    ) -> RiskAssessmentDetails:
        hyp: RootCauseHypothesis | None = None
        if proposal.hypothesis_id:
            h_stmt = select(RootCauseHypothesis).where(
                RootCauseHypothesis.id == proposal.hypothesis_id,
                RootCauseHypothesis.organization_id == proposal.organization_id,
            )
            hyp = (await session.execute(h_stmt)).scalar_one_or_none()

        risk_details = RiskEvaluator.evaluate(
            actions=proposal.actions,
            hypothesis=hyp,
        )

        was_approved = proposal.status == RemediationStatus.APPROVED.value
        if was_approved:
            proposal.version += 1
            proposal.status = RemediationStatus.PROPOSED.value
            proposal.approved_by_user_id = None
            proposal.approved_at = None
            await cls.record_audit_event(
                session=session,
                organization_id=proposal.organization_id,
                proposal_id=proposal.id,
                event_type=RemediationAuditEventType.APPROVAL_INVALIDATED.value,
                proposal_version=proposal.version,
                actor_user_id=user_id,
                actor_role=actor_role,
                from_status=RemediationStatus.APPROVED.value,
                to_status=RemediationStatus.PROPOSED.value,
                details={"reason": "Risk assessment recalculated after approval."},
                request_id=request_id,
            )

        proposal.risk_level = risk_details.overall_risk_level.value
        proposal.risk_assessment = risk_details.model_dump()

        await cls.record_audit_event(
            session=session,
            organization_id=proposal.organization_id,
            proposal_id=proposal.id,
            event_type=RemediationAuditEventType.RISK_RECALCULATED.value,
            proposal_version=proposal.version,
            actor_user_id=user_id,
            actor_role=actor_role,
            details={
                "risk_level": proposal.risk_level,
                "risk_score": risk_details.risk_score,
            },
            request_id=request_id,
        )

        await session.commit()
        await session.refresh(proposal)
        return risk_details

    @classmethod
    async def approve_proposal(
        cls,
        session: AsyncSession,
        proposal_id: str,
        organization_id: str,
        reviewer_user: User,
        reviewer_membership: OrganizationMembership,
        rationale: str,
        request_id: str | None = None,
    ) -> RemediationApproval:
        """Atomically validate approval policy, lock row, and record decision."""
        # Row-level lock to prevent concurrent races
        stmt = (
            select(RemediationProposal)
            .where(
                RemediationProposal.id == proposal_id,
                RemediationProposal.organization_id == organization_id,
            )
            .with_for_update()
        )
        proposal = (await session.execute(stmt)).scalar_one_or_none()
        if proposal is None:
            raise NotFoundException("Remediation proposal not found.")

        # Check existing approval for this proposal version
        existing_stmt = select(RemediationApproval).where(
            RemediationApproval.remediation_proposal_id == proposal.id,
            RemediationApproval.proposal_version == proposal.version,
            RemediationApproval.decision == ApprovalDecision.APPROVED.value,
        )
        existing_appr = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing_appr is not None or proposal.status == RemediationStatus.APPROVED.value:
            raise ConflictException(
                f"Proposal is already approved for version {proposal.version}."
            )

        # Enforce approval policy
        ApprovalPolicyService.assert_can_approve(
            proposal=proposal,
            reviewer_user=reviewer_user,
            reviewer_membership=reviewer_membership,
        )

        # Load linked hypothesis for snapshot provenance
        hyp_details: dict[str, Any] = {}
        if proposal.hypothesis_id:
            h_stmt = select(RootCauseHypothesis).where(
                RootCauseHypothesis.id == proposal.hypothesis_id,
                RootCauseHypothesis.organization_id == organization_id,
            )
            hyp = (await session.execute(h_stmt)).scalar_one_or_none()
            if hyp:
                hyp_details = {
                    "claim": hyp.claim,
                    "groundedness_score": hyp.groundedness_score,
                    "system_confidence": hyp.system_confidence,
                    "groundedness_status": hyp.groundedness_status,
                }

        snapshot: dict[str, Any] = {
            "title": proposal.title,
            "description": proposal.description,
            "actions": proposal.actions,
            "risk_level": proposal.risk_level,
            "risk_assessment": proposal.risk_assessment,
            "version": proposal.version,
            "hypothesis": hyp_details,
            "policy_version": ApprovalPolicyService.POLICY_VERSION,
        }

        approval_record = RemediationApproval(
            organization_id=organization_id,
            remediation_proposal_id=proposal.id,
            proposal_version=proposal.version,
            reviewer_user_id=reviewer_user.id,
            decision=ApprovalDecision.APPROVED.value,
            rationale=rationale,
            risk_level_at_decision=proposal.risk_level,
            policy_version=ApprovalPolicyService.POLICY_VERSION,
            request_id=request_id,
            snapshot=snapshot,
        )
        session.add(approval_record)

        # Update proposal state
        from_status = proposal.status
        proposal.status = RemediationStatus.APPROVED.value
        proposal.approved_by_user_id = reviewer_user.id
        proposal.approved_at = datetime.now(UTC)

        # Append audit event
        await cls.record_audit_event(
            session=session,
            organization_id=organization_id,
            proposal_id=proposal.id,
            event_type=RemediationAuditEventType.PROPOSAL_APPROVED.value,
            proposal_version=proposal.version,
            actor_user_id=reviewer_user.id,
            actor_role=reviewer_membership.role.value,
            from_status=from_status,
            to_status=proposal.status,
            details={
                "approval_id": approval_record.id,
                "rationale": rationale,
                "risk_level": proposal.risk_level,
            },
            request_id=request_id,
        )

        await session.commit()
        await session.refresh(approval_record)
        return approval_record

    @classmethod
    async def reject_proposal(
        cls,
        session: AsyncSession,
        proposal_id: str,
        organization_id: str,
        reviewer_user: User,
        reviewer_membership: OrganizationMembership,
        rationale: str,
        request_id: str | None = None,
    ) -> RemediationApproval:
        """Atomically record rejection decision and transition proposal to rejected."""
        stmt = (
            select(RemediationProposal)
            .where(
                RemediationProposal.id == proposal_id,
                RemediationProposal.organization_id == organization_id,
            )
            .with_for_update()
        )
        proposal = (await session.execute(stmt)).scalar_one_or_none()
        if proposal is None:
            raise NotFoundException("Remediation proposal not found.")

        if proposal.status in (
            RemediationStatus.REJECTED.value,
            RemediationStatus.CANCELLED.value,
            RemediationStatus.SUPERSEDED.value,
            RemediationStatus.EXPIRED.value,
        ):
            raise ConflictException(
                f"Proposal is already in terminal status '{proposal.status}'."
            )

        snapshot: dict[str, Any] = {
            "title": proposal.title,
            "actions": proposal.actions,
            "risk_level": proposal.risk_level,
            "risk_assessment": proposal.risk_assessment,
            "version": proposal.version,
            "policy_version": ApprovalPolicyService.POLICY_VERSION,
        }

        rejection_record = RemediationApproval(
            organization_id=organization_id,
            remediation_proposal_id=proposal.id,
            proposal_version=proposal.version,
            reviewer_user_id=reviewer_user.id,
            decision=ApprovalDecision.REJECTED.value,
            rationale=rationale,
            risk_level_at_decision=proposal.risk_level,
            policy_version=ApprovalPolicyService.POLICY_VERSION,
            request_id=request_id,
            snapshot=snapshot,
        )
        session.add(rejection_record)

        from_status = proposal.status
        proposal.status = RemediationStatus.REJECTED.value
        proposal.rejection_reason = rationale

        await cls.record_audit_event(
            session=session,
            organization_id=organization_id,
            proposal_id=proposal.id,
            event_type=RemediationAuditEventType.PROPOSAL_REJECTED.value,
            proposal_version=proposal.version,
            actor_user_id=reviewer_user.id,
            actor_role=reviewer_membership.role.value,
            from_status=from_status,
            to_status=proposal.status,
            details={
                "rejection_id": rejection_record.id,
                "rationale": rationale,
            },
            request_id=request_id,
        )

        await session.commit()
        await session.refresh(rejection_record)
        return rejection_record

    @classmethod
    async def list_approvals(
        cls,
        session: AsyncSession,
        proposal_id: str,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RemediationApproval], int]:
        filters = [
            RemediationApproval.remediation_proposal_id == proposal_id,
            RemediationApproval.organization_id == organization_id,
        ]
        count_stmt = select(func.count(RemediationApproval.id)).where(*filters)
        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(RemediationApproval)
            .where(*filters)
            .order_by(RemediationApproval.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = (await session.execute(stmt)).scalars().all()
        return list(items), total

    @classmethod
    async def list_audit_events(
        cls,
        session: AsyncSession,
        proposal_id: str,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RemediationAuditEvent], int]:
        filters = [
            RemediationAuditEvent.remediation_proposal_id == proposal_id,
            RemediationAuditEvent.organization_id == organization_id,
        ]
        count_stmt = select(func.count(RemediationAuditEvent.id)).where(*filters)
        total = (await session.execute(count_stmt)).scalar() or 0

        stmt = (
            select(RemediationAuditEvent)
            .where(*filters)
            .order_by(RemediationAuditEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = (await session.execute(stmt)).scalars().all()
        return list(items), total

    @classmethod
    def dry_run_policy(
        cls,
        proposal: RemediationProposal,
        reviewer_user: User,
        reviewer_membership: OrganizationMembership,
    ) -> RemediationDryRunResponse:
        """Run local deterministic policy evaluation without touching infrastructure."""
        res = ApprovalPolicyService.evaluate(
            proposal=proposal,
            reviewer_user=reviewer_user,
            reviewer_membership=reviewer_membership,
        )
        return RemediationDryRunResponse(
            allowed=res.allowed,
            risk_level=res.risk_level.value,
            required_roles=[r.value for r in res.required_roles],
            separation_of_duties_passed=res.separation_of_duties_passed,
            risk_assessment_valid=res.risk_assessment_valid,
            lifecycle_eligible=res.lifecycle_eligible,
            violations=res.violations,
            policy_version=res.policy_version,
        )

    @classmethod
    async def export_audit_report(
        cls,
        session: AsyncSession,
        proposal: RemediationProposal,
        reviewer_user: User,
        reviewer_membership: OrganizationMembership,
    ) -> RemediationAuditExportResponse:
        """Export comprehensive remediation audit trail and provenance.

        Enforces tenant isolation and sanitizes sensitive data.
        """
        # Load approvals (chronological)
        app_stmt = (
            select(RemediationApproval)
            .where(
                RemediationApproval.remediation_proposal_id == proposal.id,
                RemediationApproval.organization_id == proposal.organization_id,
            )
            .order_by(RemediationApproval.created_at.asc())
        )
        approvals = list((await session.execute(app_stmt)).scalars().all())

        # Load audit events (chronological)
        evt_stmt = (
            select(RemediationAuditEvent)
            .where(
                RemediationAuditEvent.remediation_proposal_id == proposal.id,
                RemediationAuditEvent.organization_id == proposal.organization_id,
            )
            .order_by(RemediationAuditEvent.created_at.asc())
        )
        audit_events = list((await session.execute(evt_stmt)).scalars().all())

        # Load hypothesis & groundedness metadata if linked
        evidence_reference_ids: list[str] = []
        groundedness_meta: dict[str, Any] | None = None
        if proposal.hypothesis_id:
            hyp_stmt = (
                select(RootCauseHypothesis)
                .options(selectinload(RootCauseHypothesis.evidence_links))
                .where(
                    RootCauseHypothesis.id == proposal.hypothesis_id,
                    RootCauseHypothesis.organization_id == proposal.organization_id,
                )
            )
            hyp = (await session.execute(hyp_stmt)).scalar_one_or_none()
            if hyp:
                evidence_reference_ids = [
                    link.evidence_event_id for link in (hyp.evidence_links or [])
                ]
                groundedness_meta = {
                    "groundedness_score": hyp.groundedness_score,
                    "confidence_level": hyp.system_confidence or hyp.confidence,
                    "reasoning": hyp.rationale,
                    "status": hyp.status,
                    "citation_count": len(evidence_reference_ids),
                }

        # Policy dry run validation for context
        dry_run_res = cls.dry_run_policy(
            proposal=proposal,
            reviewer_user=reviewer_user,
            reviewer_membership=reviewer_membership,
        )

        # Raw actions converted to dicts / objects, ensuring non-executable
        raw_actions = proposal.actions or []
        sanitized_actions = []
        for act in raw_actions:
            if isinstance(act, dict):
                act_copy = dict(act)
                act_copy["is_executable"] = False
                sanitized_actions.append(act_copy)
            else:
                sanitized_actions.append(act)

        return RemediationAuditExportResponse(
            audit_export_version="1.0.0",
            exported_at=datetime.now(UTC),
            organization_id=proposal.organization_id,
            incident_id=proposal.incident_id,
            proposal_id=proposal.id,
            proposal_version=proposal.version,
            title=proposal.title,
            description=proposal.description,
            status=RemediationStatus(proposal.status),
            risk_level=RemediationRiskLevel(proposal.risk_level),
            risk_assessment=proposal.risk_assessment,
            risk_assessment_version="v1",
            policy_version=ApprovalPolicyService.POLICY_VERSION,
            created_at=proposal.created_at,
            updated_at=proposal.updated_at,
            created_by_user_id=proposal.created_by_user_id,
            approved_by_user_id=proposal.approved_by_user_id,
            approved_at=proposal.approved_at,
            actions=sanitized_actions,
            decisions=[RemediationApprovalResponse.model_validate(a) for a in approvals],
            audit_events=[RemediationAuditEventResponse.model_validate(e) for e in audit_events],
            hypothesis_id=proposal.hypothesis_id,
            investigation_job_id=proposal.investigation_job_id,
            evidence_reference_ids=evidence_reference_ids,
            groundedness_metadata=groundedness_meta,
            dry_run_validation=dry_run_res,
            execution_prohibited=True,
            disclaimer=(
                "TracePilot audit export reflects application-level decision history and local policy validation. "
                "Automated execution is strictly disabled (Milestones 5A-6). Not guaranteed to be hardware tamper-proof."
            ),
        )
