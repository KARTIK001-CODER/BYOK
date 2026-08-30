from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeBaseCreate(BaseModel):
    """Schema for creating a new Knowledge Base."""

    name: str = Field(..., min_length=1, max_length=255, description="Knowledge base display name")
    description: str | None = Field(
        None, max_length=2000, description="Optional markdown/plain description"
    )
    organization_id: str | None = Field(
        None,
        description="Target organization UUID. Defaults to primary workspace if omitted.",
    )


class KnowledgeBaseUpdate(BaseModel):
    """Schema for updating Knowledge Base metadata."""

    name: str | None = Field(None, min_length=1, max_length=255, description="Updated display name")
    description: str | None = Field(
        None, max_length=2000, description="Updated markdown/plain description"
    )
    is_active: bool | None = Field(None, description="Active status flag")


class KnowledgeBaseResponse(BaseModel):
    """Standard sanitized response representation of a Knowledge Base."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    name: str
    slug: str
    description: str | None = None
    is_active: bool
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime
