from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.evidence import EvidenceSourceType
from app.models.incident import IncidentSeverity, IncidentStatus
from app.schemas.common import PaginatedResponse


class IncidentCreate(BaseModel):
    """Payload to create an incident."""

    title: str = Field(..., min_length=1, max_length=255, description="Incident title")
    description: str | None = Field(default=None, description="Detailed incident summary")
    severity: IncidentSeverity = Field(
        default=IncidentSeverity.MEDIUM, description="Incident severity level"
    )
    status: IncidentStatus = Field(
        default=IncidentStatus.OPEN, description="Incident lifecycle status"
    )
    service_name: str | None = Field(
        default=None, max_length=100, description="Affected service name"
    )
    environment: str = Field(
        default="production", max_length=50, description="Target environment"
    )
    organization_id: str | None = Field(
        default=None,
        description="Target tenant organization ID (defaults to caller's primary organization)",
    )
    incident_metadata: dict[str, Any] | None = Field(
        default=None, description="Arbitrary structured metadata"
    )


class IncidentUpdate(BaseModel):
    """Payload to update an incident."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    severity: IncidentSeverity | None = None
    status: IncidentStatus | None = None
    service_name: str | None = Field(default=None, max_length=100)
    environment: str | None = Field(default=None, max_length=50)
    incident_metadata: dict[str, Any] | None = None


class IncidentResponse(BaseModel):
    """Incident detail response model."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    title: str
    description: str | None = None
    severity: IncidentSeverity
    status: IncidentStatus
    service_name: str | None = None
    environment: str
    created_by_user_id: str | None = None
    resolved_at: datetime | None = None
    incident_metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
    evidence_count: int = 0


class EvidenceEventCreate(BaseModel):
    """Payload to ingest an evidence event."""

    source_type: EvidenceSourceType = Field(..., description="Origin source category")
    event_type: str = Field(
        ..., min_length=1, max_length=100, description="Discriminator event type"
    )
    event_timestamp: datetime = Field(
        ..., description="UTC or timezone-aware ISO8601 event timestamp"
    )
    summary: str = Field(..., min_length=1, description="Concise human-readable event summary")
    normalized_payload: dict[str, Any] = Field(
        default_factory=dict, description="Structured normalized attributes"
    )
    source_reference: str | None = Field(
        default=None, max_length=500, description="External reference (URL, commit SHA, alert ID)"
    )
    deduplication_key: str | None = Field(
        default=None, max_length=255, description="Stable deduplication identifier"
    )

    @field_validator("event_timestamp")
    @classmethod
    def ensure_timezone_aware(cls, dt: datetime) -> datetime:
        """Normalize naive datetimes to UTC timezone-aware datetimes."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)


class EvidenceEventResponse(BaseModel):
    """Evidence event detail response model."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    organization_id: str
    source_type: EvidenceSourceType
    event_type: str
    event_timestamp: datetime
    ingestion_timestamp: datetime
    summary: str
    normalized_payload: dict[str, Any]
    source_reference: str | None = None
    deduplication_key: str | None = None
    created_at: datetime
    updated_at: datetime


class TimelineEventResponse(BaseModel):
    """Timeline entry representing an event in the incident chronology."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    source_type: EvidenceSourceType
    event_type: str
    event_timestamp: datetime
    summary: str
    source_reference: str | None = None
    normalized_payload: dict[str, Any]
    deduplication_key: str | None = None


class TimelineResponse(BaseModel):
    """Chronologically sorted timeline representation."""

    incident_id: str
    total_events: int
    events: list[TimelineEventResponse]
    limit: int
    offset: int


# Type aliases for paginated responses
IncidentListResponse = PaginatedResponse[IncidentResponse]
EvidenceListResponse = PaginatedResponse[EvidenceEventResponse]


