"""Support ticket service.

Access rules (enforced here, not in the UI):

* a student may only see and act on their own tickets;
* internal notes are stripped for anyone who is not staff;
* teaching staff see tickets they raised or are assigned;
* management/admin see everything.

Notifications are emitted from this service so every entry point (API and
future automated flows) produces the same side effects.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from app.models.identity import Staff, Student, User
from app.models.platform import (
    NotificationType,
    SupportTicket,
    SupportTicketCategory,
    SupportTicketMessage,
    SupportTicketPriority,
    SupportTicketStatus,
)
from app.permissions.checks import has_permission
from app.schemas.platform import (
    SupportTicketCreate,
    SupportTicketListItem,
    SupportTicketMessageResponse,
    SupportTicketResponse,
    SupportTicketStatsResponse,
    SupportTicketUpdate,
)
from app.services.notification import create_notification, notify_users_with_role

MANAGEMENT_ROLES = {"ADMIN", "MANAGEMENT"}
STAFF_ROLES = {"ADMIN", "MANAGEMENT", "TEACHER"}


def role_names(user: User) -> set[str]:
    return {r.name for r in user.roles}


def is_staff(user: User) -> bool:
    """Staff = anyone who is not purely a student."""
    return bool(role_names(user) - {"STUDENT"})


def can_manage_tickets(user: User) -> bool:
    return bool(MANAGEMENT_ROLES & role_names(user))


def generate_ticket_number(db: DBSession) -> str:
    """Allocate the next sequential ticket number.

    Retries on collision so that two concurrent creations cannot produce the
    same number; the unique index on `ticket_number` is the final arbiter.
    """
    for _ in range(5):
        highest = (
            db.query(func.max(SupportTicket.ticket_number)).scalar() or "SUP-0000"
        )
        try:
            next_value = int(highest.split("-")[-1]) + 1
        except (ValueError, IndexError):
            next_value = db.query(func.count(SupportTicket.id)).scalar() + 1
        candidate = f"SUP-{next_value:04d}"
        if not db.query(SupportTicket.id).filter(
            SupportTicket.ticket_number == candidate
        ).first():
            return candidate
    # Extremely unlikely fallback: derive from the row count.
    return f"SUP-{db.query(func.count(SupportTicket.id)).scalar() + 1:04d}"


def _visible_message(message: SupportTicketMessage, viewer_is_staff: bool) -> bool:
    return viewer_is_staff or not message.is_internal


def to_response(
    db: DBSession,
    ticket: SupportTicket,
    *,
    viewer_is_staff: bool,
    include_messages: bool = True,
) -> SupportTicketResponse:
    """Build the full ticket representation for an authorized viewer."""
    student = ticket.student
    student_user = (
        db.query(User).filter(User.id == student.user_id).first() if student else None
    )

    visible_messages = (
        [m for m in ticket.messages if _visible_message(m, viewer_is_staff)]
        if include_messages
        else []
    )

    return SupportTicketResponse(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        student_id=ticket.student_id,
        student_name=student_user.full_name if student_user else None,
        student_number=student.student_id if student else None,
        category=ticket.category,
        subject=ticket.subject,
        description=ticket.description,
        status=ticket.status,
        priority=ticket.priority,
        assigned_to=ticket.assigned_to,
        assignee_name=ticket.assignee.full_name if ticket.assignee else None,
        resolution_note=ticket.resolution_note,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        resolved_at=ticket.resolved_at,
        closed_at=ticket.closed_at,
        message_count=len(visible_messages),
        messages=[
            SupportTicketMessageResponse(
                id=m.id,
                author_id=m.author_id,
                author_name=m.author.full_name if m.author else None,
                is_internal=m.is_internal,
                body=m.body,
                created_at=m.created_at,
            )
            for m in visible_messages
        ],
    )


def to_list_item(db: DBSession, ticket: SupportTicket) -> SupportTicketListItem:
    student = ticket.student
    student_user = (
        db.query(User).filter(User.id == student.user_id).first() if student else None
    )
    return SupportTicketListItem(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        student_id=ticket.student_id,
        student_name=student_user.full_name if student_user else None,
        student_number=student.student_id if student else None,
        category=ticket.category,
        subject=ticket.subject,
        status=ticket.status,
        priority=ticket.priority,
        assignee_name=ticket.assignee.full_name if ticket.assignee else None,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


def get_accessible_ticket(
    db: DBSession, *, user: User, ticket_id: uuid.UUID
) -> SupportTicket | None:
    """Fetch a ticket only if `user` is allowed to see it."""
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if ticket is None:
        return None

    roles = role_names(user)

    if MANAGEMENT_ROLES & roles:
        return ticket

    if "TEACHER" in roles:
        if ticket.created_by == user.id or ticket.assigned_to == user.id:
            return ticket
        return None

    if "STUDENT" in roles:
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if student is not None and ticket.student_id == student.id:
            return ticket

    return None


def list_tickets(
    db: DBSession,
    *,
    user: User,
    status_filter: SupportTicketStatus | None = None,
    category_filter: SupportTicketCategory | None = None,
    assigned_to_me: bool = False,
    student_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SupportTicket], int]:
    """List tickets visible to `user`, with server-side filtering."""
    query = db.query(SupportTicket)
    roles = role_names(user)

    if MANAGEMENT_ROLES & roles:
        pass
    elif "TEACHER" in roles:
        query = query.filter(
            or_(
                SupportTicket.created_by == user.id,
                SupportTicket.assigned_to == user.id,
            )
        )
    else:
        student = db.query(Student).filter(Student.user_id == user.id).first()
        if student is None:
            return [], 0
        query = query.filter(SupportTicket.student_id == student.id)

    if status_filter is not None:
        query = query.filter(SupportTicket.status == status_filter)
    if category_filter is not None:
        query = query.filter(SupportTicket.category == category_filter)
    if assigned_to_me:
        query = query.filter(SupportTicket.assigned_to == user.id)
    if student_id is not None:
        query = query.filter(SupportTicket.student_id == student_id)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                SupportTicket.subject.ilike(pattern),
                SupportTicket.ticket_number.ilike(pattern),
            )
        )

    total = query.count()
    items = (
        query.order_by(SupportTicket.updated_at.desc(), SupportTicket.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def ticket_stats(db: DBSession, *, user: User) -> SupportTicketStatsResponse:
    """Counting summary for the viewer's visible ticket set."""
    items, total = list_tickets(db, user=user, page=1, page_size=10_000)

    def count(status: SupportTicketStatus) -> int:
        return sum(1 for t in items if t.status == status)

    return SupportTicketStatsResponse(
        total=total,
        open=count(SupportTicketStatus.OPEN),
        in_progress=count(SupportTicketStatus.IN_PROGRESS),
        waiting_for_student=count(SupportTicketStatus.WAITING_FOR_STUDENT),
        resolved=count(SupportTicketStatus.RESOLVED),
        closed=count(SupportTicketStatus.CLOSED),
        unassigned=sum(1 for t in items if t.assigned_to is None),
    )


def create_ticket(
    db: DBSession,
    *,
    payload: SupportTicketCreate,
    actor: User,
    student_id: uuid.UUID | None = None,
) -> SupportTicket:
    """Create a ticket.

    A student may only open a ticket for themselves; staff may pass an
    explicit `student_id` (enforced by the router's permission check).
    """
    resolved_student_id = student_id
    if resolved_student_id is None:
        student = db.query(Student).filter(Student.user_id == actor.id).first()
        if student is None:
            raise ValueError("No student record is associated with this account.")
        resolved_student_id = student.id

    ticket = SupportTicket(
        ticket_number=generate_ticket_number(db),
        student_id=resolved_student_id,
        created_by=actor.id,
        category=payload.category,
        subject=payload.subject,
        description=payload.description,
        status=SupportTicketStatus.OPEN,
        priority=SupportTicketPriority.NORMAL,
    )

    for attempt in range(3):
        try:
            db.add(ticket)
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise
            ticket.ticket_number = generate_ticket_number(db)

    db.refresh(ticket)

    student = db.query(Student).filter(Student.id == resolved_student_id).first()
    student_name = student.student_id if student else None

    notify_users_with_role(
        db,
        role_names=["ADMIN", "MANAGEMENT"],
        notification_type=NotificationType.SUPPORT_TICKET_CREATED,
        params={"ticket_number": ticket.ticket_number, "student_number": student_name},
        link_url="/app/support",
        entity_type="support_ticket",
        entity_id=ticket.id,
        exclude_user_ids={actor.id},
    )
    db.commit()
    return ticket


def add_message(
    db: DBSession,
    *,
    ticket: SupportTicket,
    actor: User,
    body: str,
    is_internal: bool = False,
) -> SupportTicketMessage:
    """Append a message to a ticket and notify the other party."""
    staff = is_staff(actor)
    # Students can never author an internal note, even if they ask for one.
    effective_internal = bool(is_internal) and staff

    message = SupportTicketMessage(
        ticket_id=ticket.id,
        author_id=actor.id,
        body=body,
        is_internal=effective_internal,
    )
    db.add(message)

    # A student reply moves the ticket back into staff's queue.
    if not staff and ticket.status == SupportTicketStatus.WAITING_FOR_STUDENT:
        ticket.status = SupportTicketStatus.IN_PROGRESS

    db.commit()
    db.refresh(message)

    if staff and not effective_internal:
        student = ticket.student
        if student is not None:
            create_notification(
                db,
                user_id=student.user_id,
                notification_type=NotificationType.SUPPORT_TICKET_REPLIED,
                params={
                    "ticket_number": ticket.ticket_number,
                    "subject": ticket.subject,
                },
                link_url="/app/support",
                entity_type="support_ticket",
                entity_id=ticket.id,
            )
            db.commit()
    elif not staff:
        if ticket.assigned_to:
            # The assignee owns the reply obligation.
            create_notification(
                db,
                user_id=ticket.assigned_to,
                notification_type=NotificationType.SUPPORT_TICKET_REPLIED,
                params={"ticket_number": ticket.ticket_number},
                link_url="/app/support",
                entity_type="support_ticket",
                entity_id=ticket.id,
            )
            db.commit()
        else:
            notify_users_with_role(
                db,
                role_names=["ADMIN", "MANAGEMENT"],
                notification_type=NotificationType.SUPPORT_TICKET_REPLIED,
                params={"ticket_number": ticket.ticket_number},
                link_url="/app/support",
                entity_type="support_ticket",
                entity_id=ticket.id,
                exclude_user_ids={actor.id},
            )
            db.commit()

    return message


def _require_valid_assignee(db: DBSession, assigned_to: uuid.UUID | None) -> None:
    """Assignees must be active staff who can actually see support tickets."""
    if assigned_to is None:
        return
    user = db.query(User).filter(User.id == assigned_to).first()
    if user is None:
        raise ValueError("Assignee not found")
    if not user.is_active:
        raise ValueError("Assignee account is inactive")
    staff = (
        db.query(Staff)
        .filter(Staff.user_id == assigned_to, Staff.is_active.is_(True))
        .first()
    )
    if staff is None:
        raise ValueError("Assignee must be an active staff member")
    if not has_permission(user, "support.view"):
        raise ValueError("Assignee does not have support access")


def update_ticket(
    db: DBSession,
    *,
    ticket: SupportTicket,
    payload: SupportTicketUpdate,
    actor: User,
) -> SupportTicket:
    """Apply a staff update to a ticket and notify the student of changes."""
    data = payload.model_dump(exclude_unset=True)

    if "assigned_to" in data:
        _require_valid_assignee(db, data["assigned_to"])

    previous_status = ticket.status
    previous_assignee = ticket.assigned_to

    for field, value in data.items():
        setattr(ticket, field, value)

    now = datetime.now(UTC)
    if "status" in data and data["status"] is not None:
        if ticket.status == SupportTicketStatus.RESOLVED and ticket.resolved_at is None:
            ticket.resolved_at = now
        if ticket.status == SupportTicketStatus.CLOSED and ticket.closed_at is None:
            ticket.closed_at = now

    db.commit()
    db.refresh(ticket)

    student = ticket.student
    status_changed = "status" in data and ticket.status != previous_status
    if student is not None and status_changed:
        create_notification(
            db,
            user_id=student.user_id,
            notification_type=NotificationType.SUPPORT_TICKET_STATUS_CHANGED,
            params={
                "ticket_number": ticket.ticket_number,
                "status": str(ticket.status),
            },
            link_url="/app/support",
            entity_type="support_ticket",
            entity_id=ticket.id,
        )
        db.commit()

    if (
        "assigned_to" in data
        and ticket.assigned_to is not None
        and ticket.assigned_to != previous_assignee
    ):
        create_notification(
            db,
            user_id=ticket.assigned_to,
            notification_type=NotificationType.SUPPORT_TICKET_ASSIGNED,
            params={"ticket_number": ticket.ticket_number},
            link_url="/app/support",
            entity_type="support_ticket",
            entity_id=ticket.id,
        )
        db.commit()

    return ticket


__all__ = [
    "add_message",
    "can_manage_tickets",
    "create_ticket",
    "generate_ticket_number",
    "get_accessible_ticket",
    "is_staff",
    "list_tickets",
    "ticket_stats",
    "to_list_item",
    "to_response",
    "update_ticket",
]
