"""Audit log API.

Read-only, and restricted to holders of `audit.view` (ADMIN and MANAGEMENT).
Contexts are sanitized at write time, so responses cannot leak secrets.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession

from app.auth.dependencies import CurrentUser
from app.database.session import get_db
from app.models.audit import AuditLog
from app.permissions.checks import has_permission
from app.schemas.platform import AuditLogListResponse, AuditLogResponse

router = APIRouter(prefix="/audit", tags=["audit"])

PAGE_SIZE_MAX = 100


def _require(user) -> None:
    if not has_permission(user, "audit.view"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to view audit logs.",
                }
            },
        )


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    action: str | None = Query(None, max_length=100),
    entity_type: str | None = Query(None, max_length=50),
    entity_id: uuid.UUID | None = Query(None),
    actor_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=PAGE_SIZE_MAX),
):
    """List audit entries, newest first."""
    _require(current_user)

    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if actor_id:
        query = query.filter(AuditLog.actor_id == actor_id)
    if since:
        query = query.filter(AuditLog.created_at >= since)

    total = query.count()
    items = (
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(entry) for entry in items],
        total=total,
        page=page,
        page_size=page_size,
    )
