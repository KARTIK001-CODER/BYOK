from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus


class DocumentVersionResponse(BaseModel):
    """Schema for document version revisions."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    version_number: int
    storage_key: str
    checksum: str
    file_size: int
    content_type: str
    uploaded_by: str | None = None
    created_at: datetime


class DocumentResponse(BaseModel):
    """Standard sanitized metadata response representation of a Document."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    knowledge_base_id: str
    organization_id: str
    uploaded_by: str | None = None
    name: str
    original_filename: str
    content_type: str
    file_size: int
    storage_key: str
    checksum: str
    status: DocumentStatus
    current_version: int
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DocumentUpdate(BaseModel):
    """Schema for updating document metadata or status."""

    name: str | None = Field(None, min_length=1, max_length=255, description="Updated display name")
    status: DocumentStatus | None = Field(None, description="Updated document status")


class DocumentUploadResponse(BaseModel):
    """Response returned upon successful document upload."""

    document: DocumentResponse
    version: DocumentVersionResponse
    message: str = "Document uploaded successfully."
