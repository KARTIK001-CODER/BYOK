from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String
from sqlalchemy import JSON as GenericJSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WorkerHeartbeat(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tracks durable operational worker heartbeats and liveness state."""

    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
        comment="Stable identifier for the worker process instance.",
    )
    worker_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="investigation_worker",
        index=True,
        comment="Classification of the background worker.",
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="active",
        comment="Reported status: active, idle, shutting_down, stopped.",
    )
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        comment="UTC timestamp of the most recent heartbeat signal.",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="UTC timestamp when worker instance started.",
    )
    completed_jobs_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total successfully processed jobs by this instance.",
    )
    worker_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(GenericJSON(), "sqlite"),
        nullable=False,
        default=dict,
        comment="Operational context (PID, hostname, version).",
    )
