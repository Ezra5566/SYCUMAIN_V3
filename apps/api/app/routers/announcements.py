"""Announcement API.

Audience visibility is resolved server-side for every request; the locale
used to resolve a translation comes from the `Accept-Language` header so the
client never has to pass (or be trusted with) content selection.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.dependencies import CurrentUser
from app.database.session import get_db
from app.models.platform import (
    Announcement,
    AnnouncementAudienceType,
    AnnouncementStatus,
    NotificationType,
)
from app.permissions.checks import has_permission
from app.schemas.platform import (
    AnnouncementCreate,
    AnnouncementListResponse,
    AnnouncementResponse,
    AnnouncementUpdate,
)
from app.services.announcement import (
    activate_due_scheduled,
    archive_announcement,
    can_manage_announcements,
    create_announcement,
    is_announcement_visible,
    list_announcements,
    publish_announcement,
    to_list_item,
    to_response,
    update_announcement,
)
from app.services.notification import notify_users_with_role

router = APIRouter(prefix="/announcements", tags=["announcements"])

PAGE_SIZE_MAX = 100


def _preferred_locale(accept_language: str | None) -> str | None:
    """Extract the first usable locale tag from Accept-Language."""
    if not accept_language:
        return None
    for part in accept_language.split(","):
        tag = part.split(";")[0].strip()
        if tag and tag != "*":
            return tag
    return None


def _require(user, permission: str) -> None:
    if not has_permission(user, permission):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to perform this action.",
                }
            },
        )


def _get_announcement_or_404(db: DBSession, announcement_id: uuid.UUID) -> Announcement:
    announcement = (
        db.query(Announcement).filter(Announcement.id == announcement_id).first()
    )
    if announcement is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Announcement not found."}},
        )
    return announcement


@router.get("", response_model=AnnouncementListResponse)
def list_announcement_feed(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    accept_language: Annotated[str | None, Header()] = None,
    status_filter: AnnouncementStatus | None = Query(None, alias="status"),
    audience: AnnouncementAudienceType | None = Query(None),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=PAGE_SIZE_MAX),
):
    """List announcements visible to the caller, localized server-side."""
    _require(current_user, "announcement.view")
    activate_due_scheduled(db)
    locale = _preferred_locale(accept_language)

    items, total = list_announcements(
        db,
        user=current_user,
        locale=locale,
        status_filter=status_filter,
        audience_filter=audience,
        search=search,
        page=page,
        page_size=page_size,
    )
    return AnnouncementListResponse(
        items=[to_list_item(a, locale) for a in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{announcement_id}", response_model=AnnouncementResponse)
def get_announcement(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    announcement_id: uuid.UUID,
    accept_language: Annotated[str | None, Header()] = None,
):
    """Retrieve one announcement, honoring audience rules."""
    _require(current_user, "announcement.view")
    announcement = _get_announcement_or_404(db, announcement_id)

    managing = can_manage_announcements(current_user)
    if not managing:
        if announcement.status != AnnouncementStatus.PUBLISHED:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail={
                    "error": {"code": "NOT_FOUND", "message": "Announcement not found."}
                },
            )
        if not is_announcement_visible(db, current_user, announcement):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "This announcement is not addressed to you.",
                    }
                },
            )

    return to_response(db, announcement, _preferred_locale(accept_language))


@router.post("", response_model=AnnouncementResponse, status_code=http_status.HTTP_201_CREATED)
def create_new_announcement(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    payload: AnnouncementCreate,
    request: Request,
):
    """Create a draft announcement with one or more translations."""
    _require(current_user, "announcement.create")
    announcement = create_announcement(db, payload=payload, actor=current_user)

    record_audit(
        db,
        action="announcement.created",
        actor=current_user,
        entity_type="announcement",
        entity_id=announcement.id,
        context={
            "audience_type": str(announcement.audience_type),
            "locales": [t.locale for t in announcement.translations],
        },
        request=request,
    )
    db.commit()
    return to_response(db, announcement, payload.default_locale)


@router.patch("/{announcement_id}", response_model=AnnouncementResponse)
def edit_announcement(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    announcement_id: uuid.UUID,
    payload: AnnouncementUpdate,
    request: Request,
):
    """Partially update an announcement."""
    _require(current_user, "announcement.edit")
    announcement = _get_announcement_or_404(db, announcement_id)

    if announcement.status == AnnouncementStatus.ARCHIVED:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "INVALID_STATE",
                    "message": "Archived announcements cannot be edited.",
                }
            },
        )

    announcement = update_announcement(
        db, announcement=announcement, payload=payload, actor=current_user
    )

    record_audit(
        db,
        action="announcement.updated",
        actor=current_user,
        entity_type="announcement",
        entity_id=announcement.id,
        context={"fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    db.commit()
    return to_response(db, announcement)


@router.post("/{announcement_id}/publish", response_model=AnnouncementResponse)
def publish(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    announcement_id: uuid.UUID,
    request: Request,
):
    """Publish (or schedule) an announcement and notify its audience."""
    _require(current_user, "announcement.publish")
    announcement = _get_announcement_or_404(db, announcement_id)

    if announcement.status == AnnouncementStatus.ARCHIVED:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "INVALID_STATE",
                    "message": "Archived announcements cannot be published.",
                }
            },
        )

    announcement = publish_announcement(db, announcement=announcement, actor=current_user)

    if announcement.status == AnnouncementStatus.PUBLISHED:
        if announcement.audience_type == AnnouncementAudienceType.STUDENTS:
            roles = ["ADMIN", "MANAGEMENT", "STUDENT"]
        elif announcement.audience_type in {
            AnnouncementAudienceType.TEACHERS,
            AnnouncementAudienceType.STAFF,
        }:
            roles = ["ADMIN", "MANAGEMENT", "TEACHER"]
        else:
            roles = ["ADMIN", "MANAGEMENT", "TEACHER", "STUDENT"]

        notify_users_with_role(
            db,
            role_names=roles,
            notification_type=NotificationType.ANNOUNCEMENT_PUBLISHED,
            params={"announcement_id": str(announcement.id)},
            link_url=f"/app/announcements/{announcement.id}",
            entity_type="announcement",
            entity_id=announcement.id,
            exclude_user_ids={current_user.id},
        )

    record_audit(
        db,
        action="announcement.published",
        actor=current_user,
        entity_type="announcement",
        entity_id=announcement.id,
        context={
            "status": str(announcement.status),
            "audience_type": str(announcement.audience_type),
        },
        request=request,
    )
    db.commit()
    return to_response(db, announcement)


@router.post("/{announcement_id}/archive", response_model=AnnouncementResponse)
def archive(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    announcement_id: uuid.UUID,
    request: Request,
):
    """Archive an announcement without deleting its history."""
    _require(current_user, "announcement.publish")
    announcement = _get_announcement_or_404(db, announcement_id)
    announcement = archive_announcement(
        db, announcement=announcement, actor=current_user
    )

    record_audit(
        db,
        action="announcement.archived",
        actor=current_user,
        entity_type="announcement",
        entity_id=announcement.id,
        request=request,
    )
    db.commit()
    return to_response(db, announcement)
