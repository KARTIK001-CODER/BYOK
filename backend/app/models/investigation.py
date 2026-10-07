import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON as GenericJSON
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evidence import EvidenceEvent
    from app.models.incident import Incident
    from app.models.organization import Organization


class InvestigationStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InvestigationErrorCategory(enum.StrEnum):
    NONE = "none"
    NO_EVIDENCE = "no_evidence"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"
    CITATION_VALIDATION_FAILED = "citation_validation_failed"
    INTERNAL_ERROR = "internal_error"


class HypothesisStatus(enum.StrEnum):
    SUPPORTED = "supported"
    CONTESTED = "contested"
    REJECTED = "rejected"


class HypothesisConfidence(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceLinkType(enum.StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"


class InvestigationJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Durable, tenant-scoped investigation job. Database row is the source of truth."""

    __tablename__ = "investigation_jobs"
    __table_args__ = (
        Index("ix_investigation_jobs_incident", "incident_id"),
        Index("ix_investigation_jobs_org_status", "organization_id", "status"),
        UniqueConstraint(
            "incident_id",
            "idempotency_key",
            name="uq_investigation_jobs_incident_idempotency",
        ),
        # At most one active (queued/running) job per incident. This is the
        # database-level backstop for the check-then-insert race in
        # InvestigationService.create_job when no idempotency key is supplied
        # (NULL keys never conflict in the UNIQUE constraint above).
        # Completed/failed/cancelled jobs are unconstrained, so explicit
        # re-investigation after a terminal state always works.
        Index(
            "uq_investigation_jobs_single_active",
            "incident_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
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
    status: Mapped[str] = mapped_column(
        String(20),
        default=InvestigationStatus.QUEUED.value,
        index=True,
        nullable=False,
    )
    stage: Mapped[str] = mapped_column(
        String(50),
        default="queued",
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    error_category: Mapped[str] = mapped_column(
        String(50),
        default=InvestigationErrorCategory.NONE.value,
        nullable=False,
    )
    error_summary: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
    )
    provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
    )
    model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        default=None,
    )
    app_version: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
    )
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(
        GenericJSON().with_variant(JSONB, "postgresql"),
        nullable=True,
        default=None,
    )

    # Relationships
    incident: Mapped["Incident"] = relationship("Incident")
    organization: Mapped["Organization"] = relationship("Organization")
    hypotheses: Mapped[list["RootCauseHypothesis"]] = relationship(
        "RootCauseHypothesis",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class RootCauseHypothesis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An inferred root-cause hypothesis. Inferences, never observed facts."""

    __tablename__ = "root_cause_hypotheses"
    __table_args__ = (
        Index("ix_hypotheses_job", "investigation_job_id"),
        Index("ix_hypotheses_incident", "incident_id"),
        Index("ix_hypotheses_org", "organization_id"),
    )

    investigation_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("investigation_jobs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    incident_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    claim: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    rationale: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    confidence: Mapped[str] = mapped_column(
        String(20),
        default=HypothesisConfidence.MEDIUM.value,
        nullable=False,
    )
    confidence_score: Mapped[float | None] = mapped_column(
        nullable=True,
        default=None,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=HypothesisStatus.SUPPORTED.value,
        nullable=False,
    )
    rejection_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
    )
    provider: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
    )
    model: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        default=None,
    )

    # Relationships
    job: Mapped["InvestigationJob"] = relationship(
        "InvestigationJob",
        back_populates="hypotheses",
    )
    incident: Mapped["Incident"] = relationship("Incident")
    evidence_links: Mapped[list["HypothesisEvidenceLink"]] = relationship(
        "HypothesisEvidenceLink",
        back_populates="hypothesis",
        cascade="all, delete-orphan",
    )


class HypothesisEvidenceLink(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Links one hypothesis to one persisted evidence event (supports/contradicts)."""

    __tablename__ = "hypothesis_evidence_links"
    __table_args__ = (
        UniqueConstraint(
            "hypothesis_id",
            "evidence_event_id",
            "link_type",
            name="uq_hypothesis_evidence_link",
        ),
        Index("ix_hyp_evidence_hypothesis", "hypothesis_id"),
        Index("ix_hyp_evidence_event", "evidence_event_id"),
    )

    hypothesis_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("root_cause_hypotheses.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_event_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evidence_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    link_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    excerpt: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )

    # Relationships
    hypothesis: Mapped["RootCauseHypothesis"] = relationship(
        "RootCauseHypothesis",
        back_populates="evidence_links",
    )
    evidence_event: Mapped["EvidenceEvent"] = relationship("EvidenceEvent")
