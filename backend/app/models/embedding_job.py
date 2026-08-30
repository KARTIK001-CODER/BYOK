import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.document_version import DocumentVersion
    from app.models.organization import Organization


class EmbeddingJobStatus(enum.StrEnum):
    """Lifecycle status for document chunk embedding generation jobs."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EmbeddingJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Auditable document embedding generation job record."""

    __tablename__ = "embedding_jobs"

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    document_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    organization_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[EmbeddingJobStatus] = mapped_column(
        Enum(
            EmbeddingJobStatus,
            name="embedding_job_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
            native_enum=False,
        ),
        default=EmbeddingJobStatus.PENDING,
        index=True,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    processed_chunks: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    failed_chunks: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    embedding_model: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    embedding_dimension: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Relationships
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="embedding_jobs",
    )
    document_version: Mapped["DocumentVersion"] = relationship(
        "DocumentVersion",
    )
    organization: Mapped["Organization"] = relationship(
        "Organization",
    )
