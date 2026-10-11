from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.remediation import (
    RemediationActionType,
    RemediationRiskLevel,
    RemediationStatus,
)


class RemediationActionItem(BaseModel):
    """An individual proposed remediation action step.

    Strictly non-executable and requires human approval.
    """

    model_config = ConfigDict(from_attributes=True)

    step_number: int = Field(..., ge=1, description="Sequential 1-based order of execution.")
    action_type: RemediationActionType = Field(
        ..., description="Standard classification of the remediation action."
    )
    description: str = Field(..., min_length=1, description="Clear human-readable description.")
    target_system: str = Field(..., min_length=1, description="Subsystem or service targeted.")
    command: str | None = Field(
        default=None,
        description="Suggested command line, configuration snippet, or manual script.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="Parameters or configuration key-values."
    )
    risk_level: RemediationRiskLevel = Field(
        default=RemediationRiskLevel.MEDIUM,
        description="Risk level specific to this individual action.",
    )
    reversible: bool = Field(
        default=True, description="Whether this action can be cleanly undone."
    )
    requires_human_approval: bool = Field(
        default=True,
        description="Forced True for all mutating actions; cannot be run unattended.",
    )
    is_executable: bool = Field(
        default=False,
        description="Always False. TracePilot proposals are advisory and non-executable.",
    )

    @field_validator("is_executable")
    @classmethod
    def validate_non_executable(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "Remediation actions cannot be marked as executable. "
                "Automated execution is strictly disabled (Milestone 5A)."
            )
        return False


class RiskAssessmentDetails(BaseModel):
    """Explainable risk assessment breakdown for a remediation proposal."""

    model_config = ConfigDict(from_attributes=True)

    overall_risk_level: RemediationRiskLevel
    risk_score: float = Field(..., ge=0.0, le=1.0)
    risk_factors: list[str] = Field(default_factory=list)
    blast_radius: str
    reversibility_assessment: str
    groundedness_alignment: str | None = None
    requires_human_approval: bool = True
    execution_restricted: bool = True
    restrictions_note: str = (
        "TracePilot action proposals are strictly advisory and non-executable. "
        "Automated or unattended execution is restricted."
    )


class RemediationProposalCreate(BaseModel):
    """Request payload to manually propose a remediation plan."""

    hypothesis_id: str | None = None
    investigation_job_id: str | None = None
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    actions: list[RemediationActionItem] = Field(default_factory=list)
    rollback_plan: str | None = None
    estimated_impact: str | None = Field(default=None, max_length=255)
    mitigation_rationale: str | None = None
    is_executable: bool = Field(
        default=False,
        description="Must be False. Automated execution is strictly prohibited.",
    )

    @field_validator("is_executable")
    @classmethod
    def validate_proposal_non_executable(cls, v: bool) -> bool:
        if v:
            raise ValueError(
                "Remediation proposals cannot be executable. "
                "Automated execution is strictly restricted in Milestone 5A."
            )
        return False


class RemediationProposalGenerateRequest(BaseModel):
    """Request payload to auto-synthesize a remediation proposal from an investigation."""

    investigation_job_id: str | None = None
    hypothesis_id: str | None = None
    focus: str | None = None


class RemediationStatusTransitionRequest(BaseModel):
    """Request payload to transition proposal lifecycle status."""

    target_status: RemediationStatus
    review_notes: str | None = None
    rejection_reason: str | None = Field(default=None, max_length=500)
    superseded_by_id: str | None = None


class RemediationProposalResponse(BaseModel):
    """Full representation of a persisted remediation proposal."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    organization_id: str
    hypothesis_id: str | None = None
    investigation_job_id: str | None = None
    title: str
    description: str
    status: RemediationStatus
    risk_level: RemediationRiskLevel
    risk_assessment: dict[str, Any] | None = None
    actions: list[RemediationActionItem]
    is_executable: bool = False
    rollback_plan: str | None = None
    estimated_impact: str | None = None
    mitigation_rationale: str | None = None
    review_notes: str | None = None
    rejection_reason: str | None = None
    superseded_by_id: str | None = None
    created_by_user_id: str | None = None
    version: int = 1
    approved_by_user_id: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class RemediationProposalListResponse(BaseModel):
    """List response for remediation proposals."""

    model_config = ConfigDict(from_attributes=True)

    items: list[RemediationProposalResponse]
    total: int


class RemediationApprovalCreate(BaseModel):
    """Payload to record an approval decision."""

    rationale: str = Field(..., min_length=1, max_length=1000, description="Justification for approving.")


class RemediationRejectionCreate(BaseModel):
    """Payload to record a rejection decision."""

    rationale: str = Field(..., min_length=1, max_length=1000, description="Justification for rejecting.")


class RemediationApprovalResponse(BaseModel):
    """Full representation of a durable approval/rejection decision record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    remediation_proposal_id: str
    proposal_version: int
    reviewer_user_id: str
    decision: str
    rationale: str
    risk_level_at_decision: str
    policy_version: str
    request_id: str | None = None
    snapshot: dict[str, Any]
    created_at: datetime


class RemediationApprovalListResponse(BaseModel):
    """List of durable approval decision records."""

    model_config = ConfigDict(from_attributes=True)

    items: list[RemediationApprovalResponse]
    total: int


class RemediationAuditEventResponse(BaseModel):
    """Full representation of an append-only audit event."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    remediation_proposal_id: str
    event_type: str
    actor_user_id: str | None = None
    actor_role: str | None = None
    proposal_version: int
    from_status: str | None = None
    to_status: str | None = None
    details: dict[str, Any] | None = None
    request_id: str | None = None
    created_at: datetime


class RemediationAuditEventListResponse(BaseModel):
    """List of audit events."""

    model_config = ConfigDict(from_attributes=True)

    items: list[RemediationAuditEventResponse]
    total: int


class RemediationDryRunResponse(BaseModel):
    """Result of a local deterministic policy-validation dry run."""

    dry_run_type: str = "local_policy_validation"
    allowed: bool
    risk_level: str
    required_roles: list[str]
    separation_of_duties_passed: bool
    risk_assessment_valid: bool
    lifecycle_eligible: bool
    violations: list[str] = Field(default_factory=list)
    policy_version: str = "v1"
    disclaimer: str = (
        "This is a local, deterministic policy validation only. "
        "No infrastructure APIs were contacted and no commands were executed."
    )


class RemediationAuditExportResponse(BaseModel):
    """Stable JSON audit export payload for remediation decisions and provenance."""

    model_config = ConfigDict(from_attributes=True)

    audit_export_version: str = Field(
        default="1.0.0",
        description="Semantic version of this audit export schema.",
    )
    exported_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when export was generated.",
    )
    organization_id: str
    incident_id: str
    proposal_id: str
    proposal_version: int
    title: str
    description: str
    status: RemediationStatus
    risk_level: RemediationRiskLevel
    risk_assessment: dict[str, Any] | None = None
    risk_assessment_version: str = "v1"
    policy_version: str = "v1"
    created_at: datetime
    updated_at: datetime
    created_by_user_id: str | None = None
    approved_by_user_id: str | None = None
    approved_at: datetime | None = None

    actions: list[RemediationActionItem] = Field(default_factory=list)
    decisions: list[RemediationApprovalResponse] = Field(default_factory=list)
    audit_events: list[RemediationAuditEventResponse] = Field(default_factory=list)

    hypothesis_id: str | None = None
    investigation_job_id: str | None = None
    evidence_reference_ids: list[str] = Field(default_factory=list)
    groundedness_metadata: dict[str, Any] | None = None

    dry_run_validation: RemediationDryRunResponse | None = None

    execution_prohibited: bool = True
    disclaimer: str = (
        "TracePilot audit export reflects application-level decision history and local policy validation. "
        "Automated execution is strictly disabled (Milestones 5A-6). Not guaranteed to be hardware tamper-proof."
    )
