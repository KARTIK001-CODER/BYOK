import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.incident import Incident
    from app.models.organization import Organization


class EvidenceSourceType(enum.StrEnum):
    ALERT = "alert"
    LOG = "log"
    METRIC = "metric"
    DEPLOYMENT = "deployment"
    GIT = "git"
    TRACE = "trace"
    MANUAL = "manual"


class EvidenceEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tenant-scoped chronological evidence event attached to an incident."""

    __tablename__ = "evidence_events"
    __table_args__ = (
        Index("ix_evidence_events_incident_time", "incident_id", "event_timestamp"),
        Index("ix_evidence_events_org_incident", "organization_id", "incident_id"),
        Index("ix_evidence_events_source_type", "incident_id", "source_type"),
        Index(
            "ix_evidence_events_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        # Idempotency guard: one row per (incident, deduplication_key).
        # NULL keys never conflict (PostgreSQL and SQLite both treat NULLs
        # as distinct in unique constraints), so key-less events are unaffected.
        UniqueConstraint(
            "incident_id",
            "deduplication_key",
            name="uq_evidence_events_incident_dedup",
        ),
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
    source_type: Mapped[str] = mapped_column(
        String(50),
        index=True,
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=False,
    )
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        index=True,
        nullable=False,
    )
    ingestion_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    normalized_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )
    source_reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
    )
    deduplication_key: Mapped[str | None] = mapped_column(
        String(255),
        index=True,
        nullable=True,
        default=None,
    )

    # Vector Embedding Columns (Milestone 3A)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(384),
        nullable=True,
    )
    embedding_model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    embedded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    incident: Mapped["Incident"] = relationship(
        "Incident",
        back_populates="evidence_events",
    )
    organization: Mapped["Organization"] = relationship("Organization")
