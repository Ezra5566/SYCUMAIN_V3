"""Support ticket API.

Every access decision is made through the support service, which applies the
same ownership rules the UI assumes: students see only their own tickets and
never internal notes.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession

from app.audit import record_audit
from app.auth.dependencies import CurrentUser
from app.database.session import get_db
from app.models.platform import (
    SupportTicketCategory,
    SupportTicketStatus,
)
from app.permissions.checks import has_permission
from app.schemas.platform import (
    SupportTicketCreate,
    SupportTicketListResponse,
    SupportTicketMessageCreate,
    SupportTicketMessageResponse,
    SupportTicketResponse,
    SupportTicketStatsResponse,
    SupportTicketUpdate,
)
from app.services.support import (
    add_message,
    create_ticket,
    get_accessible_ticket,
    is_staff,
    list_tickets,
    ticket_stats,
    to_list_item,
    to_response,
    update_ticket,
)

router = APIRouter(prefix="/support", tags=["support"])

PAGE_SIZE_MAX = 100


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


def _get_ticket_or_404(db: DBSession, user, ticket_id: uuid.UUID):
    ticket = get_accessible_ticket(db, user=user, ticket_id=ticket_id)
    if ticket is None:
        # A ticket the caller cannot see is indistinguishable from one that
        # does not exist — this avoids leaking ticket IDs.
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": "Ticket not found."}},
        )
    return ticket


@router.get("", response_model=SupportTicketListResponse)
def list_support_tickets(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    status_filter: SupportTicketStatus | None = Query(None, alias="status"),
    category: SupportTicketCategory | None = Query(None),
    assigned_to_me: bool = Query(False),
    student_id: uuid.UUID | None = Query(None),
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=PAGE_SIZE_MAX),
):
    """List tickets visible to the caller."""
    _require(current_user, "support.view")

    items, total = list_tickets(
        db,
        user=current_user,
        status_filter=status_filter,
        category_filter=category,
        assigned_to_me=assigned_to_me,
        student_id=student_id,
        search=search,
        page=page,
        page_size=page_size,
    )
    return SupportTicketListResponse(
        items=[to_list_item(db, t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=SupportTicketStatsResponse)
def support_stats(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Counting summary for the caller's visible tickets."""
    _require(current_user, "support.view")
    return ticket_stats(db, user=current_user)


@router.post("", response_model=SupportTicketResponse, status_code=http_status.HTTP_201_CREATED)
def open_ticket(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    payload: SupportTicketCreate,
    request: Request,
):
    """Open a support ticket.

    A student always opens a ticket for themselves; staff may target a
    student explicitly.
    """
    _require(current_user, "support.create")

    student_id = None
    if payload.student_id is not None:
        if not is_staff(current_user):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You may only open a ticket for yourself.",
                    }
                },
            )
        student_id = payload.student_id

    try:
        ticket = create_ticket(
            db, payload=payload, actor=current_user, student_id=student_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail={"error": {"code": "NO_STUDENT_RECORD", "message": str(exc)}},
        ) from exc

    record_audit(
        db,
        action="support.ticket.created",
        actor=current_user,
        entity_type="support_ticket",
        entity_id=ticket.id,
        context={"category": str(ticket.category)},
        request=request,
    )
    db.commit()
    return to_response(db, ticket, viewer_is_staff=is_staff(current_user))


@router.get("/{ticket_id}", response_model=SupportTicketResponse)
def get_ticket(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    ticket_id: uuid.UUID,
):
    """Retrieve a ticket with its visible message thread."""
    _require(current_user, "support.view")
    ticket = _get_ticket_or_404(db, current_user, ticket_id)
    return to_response(db, ticket, viewer_is_staff=is_staff(current_user))


@router.post(
    "/{ticket_id}/messages",
    response_model=SupportTicketMessageResponse,
    status_code=http_status.HTTP_201_CREATED,
)
def post_message(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    ticket_id: uuid.UUID,
    payload: SupportTicketMessageCreate,
):
    """Add a reply. Internal notes are staff-only and never echoed to students."""
    _require(current_user, "support.view")
    ticket = _get_ticket_or_404(db, current_user, ticket_id)

    staff = is_staff(current_user)
    if not staff:
        # A student may only reply on their own ticket.
        owns_ticket = ticket.created_by == current_user.id or (
            ticket.student is not None and ticket.student.user_id == current_user.id
        )
        if not owns_ticket:
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": "You cannot reply to this ticket.",
                    }
                },
            )

    if staff and not has_permission(current_user, "support.respond"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to respond to tickets.",
                }
            },
        )

    message = add_message(
        db,
        ticket=ticket,
        actor=current_user,
        body=payload.body,
        is_internal=payload.is_internal,
    )
    return SupportTicketMessageResponse(
        id=message.id,
        author_id=message.author_id,
        author_name=current_user.full_name,
        is_internal=message.is_internal,
        body=message.body,
        created_at=message.created_at,
    )


@router.patch("/{ticket_id}", response_model=SupportTicketResponse)
def edit_ticket(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    ticket_id: uuid.UUID,
    payload: SupportTicketUpdate,
    request: Request,
):
    """Staff-only: reassign, reprioritize, or change ticket status."""
    _require(current_user, "support.view")
    ticket = _get_ticket_or_404(db, current_user, ticket_id)

    if not is_staff(current_user):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Only staff can update ticket details.",
                }
            },
        )

    data = payload.model_dump(exclude_unset=True)

    if "assigned_to" in data and not has_permission(current_user, "support.assign"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to assign tickets.",
                }
            },
        )

    status_change = data.get("status")
    closing = status_change in {
        SupportTicketStatus.RESOLVED,
        SupportTicketStatus.CLOSED,
    }
    if closing and not has_permission(current_user, "support.resolve"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to close tickets.",
                }
            },
        )

    try:
        ticket = update_ticket(db, ticket=ticket, payload=payload, actor=current_user)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_ASSIGNEE",
                    "message": str(exc),
                }
            },
        ) from None

    record_audit(
        db,
        action="support.ticket.updated",
        actor=current_user,
        entity_type="support_ticket",
        entity_id=ticket.id,
        context={"fields": sorted(data.keys())},
        request=request,
    )
    db.commit()
    return to_response(db, ticket, viewer_is_staff=True)


__all__ = ["router"]
