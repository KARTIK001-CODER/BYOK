import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.evidence import EvidenceEvent
    from app.models.organization import Organization
    from app.models.user import User


class IncidentSeverity(enum.StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IncidentStatus(enum.StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    MITIGATED = "mitigated"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Incident(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tenant-scoped SRE incident record."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_org_status", "organization_id", "status"),
        Index("ix_incidents_org_severity", "organization_id", "severity"),
        Index("ix_incidents_org_service", "organization_id", "service_name"),
        Index("ix_incidents_org_created_at", "organization_id", "created_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        default=IncidentSeverity.MEDIUM.value,
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=IncidentStatus.OPEN.value,
        index=True,
        nullable=False,
    )
    service_name: Mapped[str | None] = mapped_column(
        String(100),
        index=True,
        nullable=True,
        default=None,
    )
    environment: Mapped[str] = mapped_column(
        String(50),
        default="production",
        index=True,
        nullable=False,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    incident_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    created_by_user: Mapped["User | None"] = relationship("User")
    evidence_events: Mapped[list["EvidenceEvent"]] = relationship(
        "EvidenceEvent",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="EvidenceEvent.event_timestamp.asc()",
    )
