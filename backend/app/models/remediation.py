import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON as GenericJSON
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.incident import Incident
    from app.models.investigation import InvestigationJob, RootCauseHypothesis
    from app.models.organization import Organization
    from app.models.user import User


class RemediationStatus(enum.StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class RemediationRiskLevel(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RemediationActionType(enum.StrEnum):
    CONFIG_CHANGE = "config_change"
    SERVICE_RESTART = "service_restart"
    ROLLBACK = "rollback"
    SCALE = "scale"
    DEPENDENCY_UPDATE = "dependency_update"
    FIREWALL_RULE = "firewall_rule"
    MANUAL = "manual"


class ApprovalDecision(enum.StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class RemediationAuditEventType(enum.StrEnum):
    PROPOSAL_CREATED = "proposal_created"
    PROPOSAL_GENERATED = "proposal_generated"
    RISK_RECALCULATED = "risk_recalculated"
    STATUS_CHANGED = "status_changed"
    PROPOSAL_APPROVED = "proposal_approved"
    PROPOSAL_REJECTED = "proposal_rejected"
    PROPOSAL_CANCELLED = "proposal_cancelled"
    PROPOSAL_SUPERSEDED = "proposal_superseded"
    APPROVAL_INVALIDATED = "approval_invalidated"


class RemediationProposal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Structured, risk-assessed remediation proposal for an incident.

    CRITICAL SAFETY GUARANTEES (Milestone 5A & 5B):
    - All remediation proposals and actions are non-executable (is_executable=False).
    - Human approval policy enforces separation of duties and role-tiered governance.
    - Tenant isolation is strictly enforced via organization_id.
    - Versioned audit trail captures all decisions and proposal lifecycle changes.
    """

    __tablename__ = "remediation_proposals"
    __table_args__ = (
        Index("ix_remediation_proposals_incident", "incident_id"),
        Index("ix_remediation_proposals_org_status", "organization_id", "status"),
        Index("ix_remediation_proposals_hypothesis", "hypothesis_id"),
        Index("ix_remediation_proposals_job", "investigation_job_id"),
    )

    incident_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("root_cause_hypotheses.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    investigation_job_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("investigation_jobs.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(30),
        default=RemediationStatus.PROPOSED.value,
        index=True,
        nullable=False,
    )
    risk_level: Mapped[str] = mapped_column(
        String(20),
        default=RemediationRiskLevel.MEDIUM.value,
        nullable=False,
    )
    risk_assessment: Mapped[dict[str, Any] | None] = mapped_column(
        GenericJSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        default=None,
    )
    actions: Mapped[list[dict[str, Any]]] = mapped_column(
        GenericJSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=list,
    )
    is_executable: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    rollback_plan: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    estimated_impact: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    mitigation_rationale: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    review_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("remediation_proposals.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Relationships
    incident: Mapped["Incident"] = relationship("Incident")
    organization: Mapped["Organization"] = relationship("Organization")
    hypothesis: Mapped["RootCauseHypothesis | None"] = relationship("RootCauseHypothesis")
    investigation_job: Mapped["InvestigationJob | None"] = relationship("InvestigationJob")
    created_by_user: Mapped["User | None"] = relationship(
        "User", foreign_keys=[created_by_user_id]
    )
    approved_by_user: Mapped["User | None"] = relationship(
        "User", foreign_keys=[approved_by_user_id]
    )
    approvals: Mapped[list["RemediationApproval"]] = relationship(
        "RemediationApproval",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="desc(RemediationApproval.created_at)",
    )
    audit_events: Mapped[list["RemediationAuditEvent"]] = relationship(
        "RemediationAuditEvent",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="desc(RemediationAuditEvent.created_at)",
    )


class RemediationApproval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable append-only approval or rejection record for a remediation proposal."""

    __tablename__ = "remediation_approvals"
    __table_args__ = (
        Index("ix_remediation_approvals_proposal", "remediation_proposal_id"),
        Index("ix_remediation_approvals_org", "organization_id"),
        Index(
            "ix_remediation_approvals_prop_ver",
            "remediation_proposal_id",
            "proposal_version",
        ),
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    remediation_proposal_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("remediation_proposals.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    proposal_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    reviewer_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    risk_level_at_decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    policy_version: Mapped[str] = mapped_column(
        String(20),
        default="v1",
        nullable=False,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        default=None,
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(
        GenericJSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
    )

    # Relationships
    proposal: Mapped["RemediationProposal"] = relationship(
        "RemediationProposal",
        back_populates="approvals",
    )
    reviewer_user: Mapped["User"] = relationship("User")
    organization: Mapped["Organization"] = relationship("Organization")


class RemediationAuditEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only audit trail event for remediation proposal lifecycle and policy decisions."""

    __tablename__ = "remediation_audit_events"
    __table_args__ = (
        Index("ix_remediation_audit_proposal_created", "remediation_proposal_id", "created_at"),
        Index("ix_remediation_audit_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    remediation_proposal_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("remediation_proposals.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    actor_role: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default=None,
    )
    proposal_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    from_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        default=None,
    )
    to_status: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        default=None,
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        GenericJSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        default=None,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    proposal: Mapped["RemediationProposal"] = relationship(
        "RemediationProposal",
        back_populates="audit_events",
    )
    actor_user: Mapped["User | None"] = relationship("User")
    organization: Mapped["Organization"] = relationship("Organization")
