"""Notification API.

A user can only ever read and mutate their own notifications: the recipient
is always taken from the authenticated session, never from the request.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession

from app.auth.dependencies import CurrentUser
from app.database.session import get_db
from app.schemas.platform import NotificationListResponse, NotificationResponse
from app.services.notification import (
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])

PAGE_SIZE_MAX = 100


@router.get("", response_model=NotificationListResponse)
def get_notifications(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    unread_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=PAGE_SIZE_MAX),
):
    """List notifications for the authenticated user."""
    items, total, unread = list_notifications(
        db,
        user_id=current_user.id,
        unread_only=unread_only,
        page=page,
        page_size=page_size,
    )
    return NotificationListResponse(
        items=[NotificationResponse.model_validate(n) for n in items],
        total=total,
        unread_count=unread,
        page=page,
        page_size=page_size,
    )


@router.get("/unread-count")
def get_unread_count(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Unread badge count for the current user."""
    return {"unread_count": unread_count(db, current_user.id)}


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    notification_id: uuid.UUID,
):
    """Mark a single notification as read."""
    notification = mark_read(
        db, notification_id=notification_id, user_id=current_user.id
    )
    if notification is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "Notification not found.",
                }
            },
        )
    return NotificationResponse.model_validate(notification)


@router.post("/read-all")
def mark_everything_read(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Mark every unread notification for the current user as read."""
    return {"updated": mark_all_read(db, user_id=current_user.id)}
