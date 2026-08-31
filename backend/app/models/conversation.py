from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.message import Message
    from app.models.organization import Organization
    from app.models.user import User


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tenant-scoped conversation session containing user and assistant messages."""

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_org_user", "organization_id", "user_id"),
        Index("ix_conversations_org_updated", "organization_id", "updated_at"),
    )

    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="New Conversation",
    )
    knowledge_base_ids: Mapped[list[str] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    conversation_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship("Organization")
    user: Mapped["User"] = relationship("User")
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )
