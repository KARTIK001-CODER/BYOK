from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe response schema."""

    status: str = Field(default="ok", description="Application liveness status")


class DependencyStatus(BaseModel):
    """Status details for an individual infrastructure dependency."""

    status: str = Field(description="Dependency status: 'ok', 'error', 'disabled', or 'not_applicable'")
    mandatory: bool = Field(default=True, description="Whether this dependency is strictly required to serve traffic")
    latency_ms: float | None = Field(default=None, description="Round-trip check latency in milliseconds")
    message: str | None = Field(default=None, description="Safe status message or diagnostic category")


class WorkerStatus(BaseModel):
    """Status details for background asynchronous processing workers."""

    status: str = Field(
        default="idle",
        description="Worker operational status: 'active', 'idle', 'stale', or 'unmonitored'",
    )
    last_heartbeat_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recent worker heartbeat",
    )
    active_jobs_count: int = Field(default=0, description="Count of currently running investigation jobs")
    stale_jobs_count: int = Field(default=0, description="Count of queued jobs exceeding stale threshold")


class ReadinessResponse(BaseModel):
    """Readiness probe response schema with bounded timeout verifications."""

    status: str = Field(description="Overall system readiness: 'ready', 'degraded', or 'unhealthy'")
    database: str = Field(description="Database connectivity status: 'ok' or 'error'")
    vector_store: str = Field(
        description="pgvector extension status: 'ok', 'error', or 'disabled'"
    )
    dependencies: dict[str, DependencyStatus] = Field(
        default_factory=dict,
        description="Detailed health metrics per dependency",
    )
    worker: WorkerStatus = Field(
        default_factory=WorkerStatus,
        description="Background investigation worker liveness metrics",
    )
    check_duration_ms: float | None = Field(
        default=None,
        description="Total duration of readiness evaluation in milliseconds",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp of the readiness evaluation",
    )


class SystemInfoResponse(BaseModel):
    """Application metadata and environment info schema."""

    app_name: str
    version: str
    environment: str
    debug: bool
    features: dict[str, Any] = Field(default_factory=dict)
