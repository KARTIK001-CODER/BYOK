from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.embedding_job import EmbeddingJobStatus


class EmbeddingJobResponse(BaseModel):
    """Sanitized response schema for an EmbeddingJob."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    document_version_id: str
    organization_id: str
    status: EmbeddingJobStatus
    attempt_count: int
    total_chunks: int
    processed_chunks: int
    failed_chunks: int
    embedding_model: str
    embedding_dimension: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class EmbeddingTriggerResponse(BaseModel):
    """Response returned when document embedding generation is initiated."""

    job_id: str
    document_id: str
    status: EmbeddingJobStatus
    total_chunks: int
    processed_chunks: int
    embedding_model: str
    message: str = "Embedding generation initiated."
