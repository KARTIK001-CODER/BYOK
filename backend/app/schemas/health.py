from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness probe response schema."""

    status: str = Field(default="ok", description="Application liveness status")


class ReadinessResponse(BaseModel):
    """Readiness probe response schema."""

    status: str = Field(description="Overall system readiness ('ready' or 'unhealthy')")
    database: str = Field(description="Database connectivity status ('ok' or 'error')")
    vector_store: str = Field(
        description="pgvector extension status ('ok', 'error', or 'disabled')"
    )


class SystemInfoResponse(BaseModel):
    """Application metadata and environment info schema."""

    app_name: str
    version: str
    environment: str
    debug: bool
