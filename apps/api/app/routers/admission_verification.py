"""Read-only migration verification queue for the Phase 2 staff console."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.auth.dependencies import CurrentUser  # noqa: TC001
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.admission import AdmissionVerificationStatus  # noqa: TC001
from app.permissions.checks import has_permission
from app.schemas.admission import MigrationQueueResponse
from app.services.admission_verification_queue import list_migration_queue

router = APIRouter(prefix="/admission-verification", tags=["admission-verification"])


def _forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail={"error": {"code": "FORBIDDEN", "message": message}},
    )


@router.get("/queue", response_model=MigrationQueueResponse)
def get_migration_queue(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    verification_status: AdmissionVerificationStatus | None = Query(
        None,
        description="Filter by UNVERIFIED, VERIFIED, DISPUTED or REVOKED.",
    ),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> MigrationQueueResponse:
    """List MIGRATED candidates; no trust state is inferred or written here."""
    if not has_permission(current_user, "academic.view_admissions"):
        raise _forbidden("You do not have permission to view admission verification.")
    if not get_settings().ADMISSION_MIGRATION_CONSOLE_ENABLED:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "MIGRATION_CONSOLE_DISABLED",
                    "message": "The admission migration verification console is disabled.",
                }
            },
        )
    return list_migration_queue(
        db,
        verification_status=verification_status,
        search=search,
        page=page,
        page_size=page_size,
    )
