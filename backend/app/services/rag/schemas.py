from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CitationItem(BaseModel):
    """Structured provenance metadata for a citation reference in the generated answer."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="1-indexed citation ID corresponding to [1], [2], etc.")
    chunk_id: str
    document_id: str
    document_version_id: str
    document_name: str
    page_number: int | None = None
    section_title: str | None = None
    content_preview: str | None = None


class RetrievalSummary(BaseModel):
    """Concise metadata regarding the retrieval step in a RAG response."""

    search_mode: str = "hybrid"
    result_count: int = 0
    latency_ms: float = 0.0


class RAGChatRequest(BaseModel):
    """Input payload for user RAG chat queries."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The user's query or conversational prompt.",
    )
    conversation_id: str | None = Field(
        default=None,
        description="Optional existing conversation ID to continue a thread.",
    )
    knowledge_base_ids: list[str] | None = Field(
        default=None,
        description="Optional list of Knowledge Base IDs to restrict context retrieval.",
    )
    provider: str | None = Field(
        default=None,
        description="LLM provider override ('groq', 'openai', 'gemini', 'mock').",
    )
    model: str | None = Field(
        default=None,
        description="Model identifier override.",
    )
    top_k: int = Field(
        default=8,
        gt=0,
        le=50,
        description="Maximum number of context chunks to retrieve.",
    )
    search_mode: Literal["vector", "keyword", "hybrid"] = Field(
        default="hybrid",
        description="Retrieval search strategy.",
    )
    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for answer generation.",
    )

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Chat message cannot be empty or whitespace only.")
        return trimmed


class RAGChatResponse(BaseModel):
    """Complete grounded answer and citation envelope returned from non-streaming generation."""

    conversation_id: str
    message_id: str
    user_message_id: str
    answer: str
    citations: list[CitationItem]
    retrieval: RetrievalSummary
    model: str
    provider: str
    usage: dict[str, int | None] | None = None
    latency_ms: float = 0.0


class MessageRead(BaseModel):
    """Read representation of an individual conversation message."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    message_metadata: dict[str, Any] | None = None
    created_at: datetime


class ConversationRead(BaseModel):
    """Summary representation of a conversation thread."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    organization_id: str
    user_id: str
    title: str
    knowledge_base_ids: list[str] | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int | None = None


class ConversationWithMessagesRead(ConversationRead):
    """Complete conversation thread including message history."""

    messages: list[MessageRead] = []


class ConversationCreate(BaseModel):
    """Payload to explicitly create a conversation thread."""

    title: str | None = Field(default=None, max_length=255)
    knowledge_base_ids: list[str] | None = None


class ConversationUpdate(BaseModel):
    """Payload to update conversation metadata or title."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    knowledge_base_ids: list[str] | None = None
