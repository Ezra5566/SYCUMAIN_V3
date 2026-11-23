"""Notification service.

Notifications are created by *domain services* when something meaningful
happens, never by routers directly. Notifications carry a machine-readable
`type` plus structured `params`; the localized sentence is composed on the
client from the `notifications.<type>` translation key. This keeps the API
language-neutral and means a new locale needs no backend change.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.models.identity import Role, User, user_roles
from app.models.platform import Notification, NotificationType


def create_notification(
    db: DBSession,
    *,
    user_id: uuid.UUID,
    notification_type: NotificationType,
    params: dict[str, Any] | None = None,
    link_url: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> Notification:
    """Stage a notification for one recipient.

    Does not commit; the caller commits with its own transaction so a
    notification is never delivered for a change that rolled back.
    """
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        params=params,
        link_url=link_url,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(notification)
    return notification


def notify_users_with_role(
    db: DBSession,
    *,
    role_names: set[str] | list[str],
    notification_type: NotificationType,
    params: dict[str, Any] | None = None,
    link_url: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    exclude_user_ids: set[uuid.UUID] | None = None,
) -> list[Notification]:
    """Notify every active user holding one of the given roles."""
    excluded = exclude_user_ids or set()

    recipients = (
        db.query(User.id)
        .join(user_roles, user_roles.c.user_id == User.id)
        .join(Role, Role.id == user_roles.c.role_id)
        .filter(Role.name.in_(list(role_names)), User.is_active.is_(True))
        .distinct()
        .all()
    )

    created: list[Notification] = []
    for (user_id,) in recipients:
        if user_id in excluded:
            continue
        created.append(
            create_notification(
                db,
                user_id=user_id,
                notification_type=notification_type,
                params=params,
                link_url=link_url,
                entity_type=entity_type,
                entity_id=entity_id,
            )
        )
    return created


def list_notifications(
    db: DBSession,
    *,
    user_id: uuid.UUID,
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Notification], int, int]:
    """Return `(items, total, unread_count)` for a recipient."""
    query = db.query(Notification).filter(Notification.user_id == user_id)
    if unread_only:
        query = query.filter(Notification.read_at.is_(None))

    total = query.count()
    items = (
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    unread_count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .scalar()
        or 0
    )
    return items, total, int(unread_count)


def unread_count(db: DBSession, user_id: uuid.UUID) -> int:
    """Number of unread notifications for a recipient."""
    return (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .scalar()
        or 0
    )


def mark_read(
    db: DBSession, *, notification_id: uuid.UUID, user_id: uuid.UUID
) -> Notification | None:
    """Mark one notification read. Returns None when not owned by the user."""
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user_id)
        .first()
    )
    if notification is None:
        return None
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
    return notification


def mark_all_read(db: DBSession, *, user_id: uuid.UUID) -> int:
    """Mark every unread notification read; returns how many were updated."""
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .update({Notification.read_at: datetime.now(UTC)}, synchronize_session=False)
    )
    db.commit()
    return int(updated)


def student_user_id(db: DBSession, student_id: uuid.UUID) -> uuid.UUID | None:
    """Resolve a student record to its authentication identity."""
    from app.models.identity import Student  # noqa: PLC0415 - avoid import cycle

    student = db.query(Student).filter(Student.id == student_id).first()
    return student.user_id if student else None


__all__ = [
    "create_notification",
    "list_notifications",
    "mark_all_read",
    "mark_read",
    "notify_users_with_role",
    "student_user_id",
    "unread_count",
]
