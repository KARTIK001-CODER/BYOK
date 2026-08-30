from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class DocumentChunkResponse(BaseModel):
    """Sanitized response schema for a DocumentChunk."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    document_version_id: str
    organization_id: str
    knowledge_base_id: str
    chunk_index: int
    content: str
    character_count: int
    word_count: int
    page_number: int | None = None
    section_title: str | None = None
    chunk_metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime
