from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.ingestion_job import IngestionJobStatus


class IngestionJobResponse(BaseModel):
    """Sanitized response schema for an IngestionJob."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    document_version_id: str
    organization_id: str
    status: IngestionJobStatus
    attempt_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class IngestionTriggerResponse(BaseModel):
    """Response returned when document ingestion is triggered."""

    job_id: str
    document_id: str
    status: IngestionJobStatus
    message: str = "Ingestion job initiated."
