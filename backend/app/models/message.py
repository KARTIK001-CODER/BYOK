import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.conversation import Conversation


class MessageRole(enum.StrEnum):
    """Supported roles in a RAG conversation thread."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(Base, UUIDPrimaryKeyMixin):
    """An individual message in a conversation thread with associated grounding metadata."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conv_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(
            MessageRole,
            name="message_role_enum",
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=False,
        ),
        nullable=False,
        default=MessageRole.USER,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    conversation: Mapped["Conversation"] = relationship(
        "Conversation",
        back_populates="messages",
    )
