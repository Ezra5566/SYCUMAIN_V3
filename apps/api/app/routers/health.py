"""Health check endpoints."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session  # noqa: TC002 - FastAPI resolves this annotation at runtime

from app.config.settings import get_settings
from app.database.session import get_db
from app.schemas.health import HealthResponse, ReadyResponse
from app.storage import StorageError, get_storage

logger = logging.getLogger("app.health")
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Confirm the application process is alive.

    Deliberately dependency-free: this answers "is the process serving HTTP?",
    which is what a restart policy needs to know. Dependency state belongs to
    ``/ready``.
    """
    settings = get_settings()
    started_at = getattr(request.app.state, "started_at", None)
    uptime = round(time.monotonic() - started_at, 1) if started_at else None

    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        uptime_seconds=uptime,
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
def readiness_check(
    request: Request, db: Session = Depends(get_db)
) -> JSONResponse:
    """Verify the dependencies needed to serve traffic are available.

    Returns 503 when a dependency is unavailable, so a load balancer or
    container orchestrator can take this instance out of rotation instead of
    routing student records at a process that cannot read them.
    """
    settings = get_settings()

    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        # Logged, not returned: the response stays safe for public exposure
        # while the operator gets the actual driver error.
        logger.warning("readiness_database_unavailable", exc_info=True)
        database = "unavailable"

    storage = "ok"
    try:
        if not get_storage().healthcheck():
            storage = "unavailable"
    except StorageError:
        logger.warning("readiness_storage_unavailable", exc_info=True)
        storage = "unavailable"

    healthy = database == "ok" and storage == "ok"
    payload = ReadyResponse(
        status="ok" if healthy else "degraded",
        database=database,
        storage=storage,
        version=settings.APP_VERSION,
        checks={"database": database, "storage": storage},
    )
    return JSONResponse(
        status_code=200 if healthy else 503,
        content=payload.model_dump(),
    )
