"""Health check response schemas."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response for /health endpoint."""

    status: str = "ok"
    # Build identity: answering "which version is running?" from the process
    # itself removes the guessing that follows every deployment.
    version: str | None = None
    environment: str | None = None
    uptime_seconds: float | None = None


class ReadyResponse(BaseModel):
    """Response for /ready endpoint."""

    status: str
    database: str = "ok"
    storage: str = "ok"
    version: str | None = None
    checks: dict[str, str] = Field(default_factory=dict)
