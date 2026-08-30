from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class DocumentVersion(Base, UUIDPrimaryKeyMixin):
    """Immutable version revision history for a logical document."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_doc_version"),
    )

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    checksum: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    content_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    uploaded_by: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="versions",
    )
    uploader: Mapped["User | None"] = relationship(
        "User",
        foreign_keys=[uploaded_by],
    )
