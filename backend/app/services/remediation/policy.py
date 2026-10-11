from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import ConflictException, ForbiddenException, ValidationException
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.remediation import (
    RemediationProposal,
    RemediationRiskLevel,
    RemediationStatus,
)
from app.models.user import User


@dataclass
class PolicyEvaluationResult:
    """Deterministic result of approval policy validation."""

    allowed: bool
    risk_level: RemediationRiskLevel
    required_roles: list[OrganizationRole]
    separation_of_duties_passed: bool
    risk_assessment_valid: bool
    lifecycle_eligible: bool
    violations: list[str] = field(default_factory=list)
    policy_version: str = "v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk_level": self.risk_level.value,
            "required_roles": [r.value for r in self.required_roles],
            "separation_of_duties_passed": self.separation_of_duties_passed,
            "risk_assessment_valid": self.risk_assessment_valid,
            "lifecycle_eligible": self.lifecycle_eligible,
            "violations": self.violations,
            "policy_version": self.policy_version,
        }


class ApprovalPolicyService:
    """Centralized, deterministic approval policy engine for TracePilot remediation proposals.

    RULES:
    1. Tenant Isolation: Reviewer must belong to the proposal's organization.
    2. Separation of Duties: The creator of a proposal cannot approve their own proposal.
    3. Lifecycle Constraints: Only proposals in 'proposed' or 'reviewed' status may be approved.
       Terminal ('rejected', 'superseded', 'cancelled', 'expired') or already 'approved' proposals cannot be approved.
    4. Risk Assessment Freshness & Validity: Must possess a valid, non-stale risk assessment with valid scores.
    5. Role-Tiered Governance:
       - LOW: Any active MEMBER, ADMIN, or OWNER (except creator).
       - MEDIUM: Any active MEMBER, ADMIN, or OWNER (except creator).
       - HIGH / CRITICAL: Strictly requires ADMIN or OWNER (except creator).
    """

    POLICY_VERSION: str = "v1"

    @classmethod
    def evaluate(
        cls,
        proposal: RemediationProposal,
        reviewer_user: User,
        reviewer_membership: OrganizationMembership,
    ) -> PolicyEvaluationResult:
        violations: list[str] = []

        # 1. Organization boundary check
        if reviewer_membership.organization_id != proposal.organization_id:
            violations.append(
                f"Reviewer organization ({reviewer_membership.organization_id}) does not match "
                f"proposal organization ({proposal.organization_id})."
            )

        # 2. Lifecycle state eligibility
        lifecycle_eligible = proposal.status in (
            RemediationStatus.PROPOSED.value,
            RemediationStatus.REVIEWED.value,
        )
        if not lifecycle_eligible:
            if proposal.status == RemediationStatus.APPROVED.value:
                violations.append(
                    f"Proposal is already approved for version {proposal.version}. "
                    "Mutations are required to re-request approval."
                )
            else:
                violations.append(
                    f"Proposal in terminal or non-approvable status '{proposal.status}' cannot be approved."
                )

        # 3. Separation of duties: Creator cannot approve their own proposal
        separation_passed = True
        if proposal.created_by_user_id and proposal.created_by_user_id == reviewer_user.id:
            separation_passed = False
            violations.append(
                "Separation of duties violation: The proposal creator cannot approve their own proposal."
            )

        # 4. Risk assessment validation & freshness
        risk_assessment_valid = True
        if not proposal.risk_assessment or not isinstance(proposal.risk_assessment, dict):
            risk_assessment_valid = False
            violations.append("Proposal is missing required risk assessment.")
        else:
            ra = proposal.risk_assessment
            risk_score = ra.get("risk_score")
            overall_level = ra.get("overall_risk_level")
            if risk_score is None or not (0.0 <= float(risk_score) <= 1.0):
                risk_assessment_valid = False
                violations.append(f"Invalid risk_score in proposal risk assessment: {risk_score}.")
            if not overall_level:
                risk_assessment_valid = False
                violations.append("Missing overall_risk_level in proposal risk assessment.")

            # Check action consistency
            if len(proposal.actions) == 0 and float(risk_score or 0) > 0.5:
                risk_assessment_valid = False
                violations.append("Stale risk assessment: proposal has zero actions but high risk score.")

            # Check for non-executable invariant
            if any(a.get("is_executable") for a in proposal.actions if isinstance(a, dict)):
                risk_assessment_valid = False
                violations.append(
                    "Safety violation: One or more proposed actions is marked executable."
                )

        # 5. Role requirement determination
        risk_level_str = (proposal.risk_level or "medium").lower()
        if risk_level_str == RemediationRiskLevel.LOW.value:
            risk_level = RemediationRiskLevel.LOW
            required_roles = [
                OrganizationRole.MEMBER,
                OrganizationRole.ADMIN,
                OrganizationRole.OWNER,
            ]
        elif risk_level_str == RemediationRiskLevel.MEDIUM.value:
            risk_level = RemediationRiskLevel.MEDIUM
            required_roles = [
                OrganizationRole.MEMBER,
                OrganizationRole.ADMIN,
                OrganizationRole.OWNER,
            ]
        elif risk_level_str == RemediationRiskLevel.HIGH.value:
            risk_level = RemediationRiskLevel.HIGH
            required_roles = [OrganizationRole.ADMIN, OrganizationRole.OWNER]
        else:
            risk_level = RemediationRiskLevel.CRITICAL
            required_roles = [OrganizationRole.ADMIN, OrganizationRole.OWNER]

        # 6. Check reviewer role
        if reviewer_membership.role not in required_roles:
            role_names = ", ".join(r.value for r in required_roles)
            violations.append(
                f"Insufficient authorization: {risk_level.value.upper()} risk proposals require one of [{role_names}], "
                f"but reviewer has role '{reviewer_membership.role.value}'."
            )

        allowed = len(violations) == 0

        return PolicyEvaluationResult(
            allowed=allowed,
            risk_level=risk_level,
            required_roles=required_roles,
            separation_of_duties_passed=separation_passed,
            risk_assessment_valid=risk_assessment_valid,
            lifecycle_eligible=lifecycle_eligible,
            violations=violations,
            policy_version=cls.POLICY_VERSION,
        )

    @classmethod
    def assert_can_approve(
        cls,
        proposal: RemediationProposal,
        reviewer_user: User,
        reviewer_membership: OrganizationMembership,
    ) -> PolicyEvaluationResult:
        result = cls.evaluate(proposal, reviewer_user, reviewer_membership)
        if not result.allowed:
            # Map violations to appropriate error types
            if not result.lifecycle_eligible:
                raise ConflictException(
                    message=f"Proposal cannot be approved in its current status: '{proposal.status}'.",
                    details={"violations": result.violations},
                )
            if not result.separation_of_duties_passed:
                raise ForbiddenException(
                    message="Separation of duties violation: The creator cannot approve their own proposal.",
                    details={"violations": result.violations},
                )
            if not result.risk_assessment_valid:
                raise ValidationException(
                    message="Proposal risk assessment is missing, stale, or invalid.",
                    details={"violations": result.violations},
                )
            # Role or org mismatch
            raise ForbiddenException(
                message=f"Reviewer lacks required authorization for {result.risk_level.value.upper()} risk approval.",
                details={"violations": result.violations},
            )
        return result
