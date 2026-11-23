"""Immigration expiry reminder generation.

What this module owns
---------------------
* **Only verified information drives an official reminder.** A profile that is
  ``UNVERIFIED``, ``REVOKED`` or ``DISPUTED`` produces no alert, even if its
  expiry dates are inside a warning window. An import or a student's
  unconfirmed submission therefore cannot trigger an official warning.
* **The intervals are the institution's.** They are the existing
  ``WARNING_DAYS_90`` / ``WARNING_DAYS_30`` tiers already used by the overview
  and the student directory, so there is exactly one definition of "urgent" in
  the system. Nothing new is invented here.
* **A reminder is created once.** The alert is keyed on
  (profile, document, tier, expiry date), so re-running the job — on startup, by
  hand, or from two workers at once — cannot send the same warning twice.
* **A reminder resolves when the condition is fixed.** Renewing the document,
  correcting the date, or losing verification marks the open alert resolved and
  records why. Resolved alerts stay readable; they are history, not noise.
* **Recipients are scoped.** The student is told about their own document and
  nobody else's; Admin and Management receive the operational alert. Teachers
  get neither, because a teaching assignment grants no access to passports.

The job is idempotent and safe to run at any frequency. It writes only rows it
owns: ``immigration_reminders`` and notifications. It never edits a profile,
a document or an expiry date.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - used in type hints resolved at runtime
from datetime import UTC, date, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.models.identity import Student, StudentStatus
from app.models.immigration import ImmigrationProfile
from app.models.immigration_reminder import (
    REMINDER_DOCUMENT_TYPES,
    REMINDER_TIERS,
    ImmigrationReminder,
)
from app.models.platform import NotificationType
from app.services.immigration import calculate_document_status
from app.services.notification import create_notification, notify_users_with_role

#: Profile column behind each reminder document type. ``OTHER`` documents carry
#: no expiry date in the profile, so they can never raise an alert.
DOCUMENT_FIELDS: dict[str, str] = {
    "PASSPORT": "passport_expiry_date",
    "VISA": "visa_expiry_date",
    "RESIDENCE_PERMIT": "residence_permit_expiry_date",
}

TIER_NOTIFICATION: dict[str, NotificationType] = {
    "EXPIRED": NotificationType.IMMIGRATION_EXPIRY_EXPIRED,
    "URGENT": NotificationType.IMMIGRATION_EXPIRY_URGENT,
    "EXPIRING_SOON": NotificationType.IMMIGRATION_EXPIRY_EXPIRING_SOON,
}

#: Operational recipients. A reminder is an institutional follow-up task, so it
#: goes to the two roles that administer immigration records.
STAFF_ROLES: tuple[str, ...] = ("ADMIN", "MANAGEMENT")

MAX_PAGE_SIZE = 100


def _now() -> datetime:
    return datetime.now(UTC)


def _resolution(
    profile: ImmigrationProfile, student: Student | None, row: ImmigrationReminder
) -> str:
    """Why an open alert no longer applies.

    The distinction matters to an auditor: a renewed passport and a corrected
    typo both clear the warning, but only one of them is a real-world event.
    """
    if profile.verification_status != "VERIFIED":
        return "PROFILE_UNVERIFIED"
    if student is not None and student.status != StudentStatus.ACTIVE.value:
        return "STUDENT_INACTIVE"
    expiry = getattr(profile, DOCUMENT_FIELDS.get(row.document_type, ""), None)
    if expiry is None or expiry != row.expiry_date:
        return "EXPIRY_UPDATED"
    return "CORRECTED"


def _notify(
    db: DBSession,
    *,
    profile: ImmigrationProfile,
    student: Student,
    row: ImmigrationReminder,
    days_remaining: int,
) -> None:
    """Deliver one alert to the student and to the operational roles."""
    notification_type = TIER_NOTIFICATION[row.tier]
    student_params = {
        "document": row.document_type.lower(),
        "days": days_remaining,
        "expiry_date": row.expiry_date.isoformat(),
    }

    create_notification(
        db,
        user_id=student.user_id,
        notification_type=notification_type,
        params=student_params,
        entity_type="immigration_reminder",
        entity_id=row.id,
    )

    notify_users_with_role(
        db,
        role_names=set(STAFF_ROLES),
        notification_type=notification_type,
        params={
            **student_params,
            "student_name": f"{student.first_name} {student.last_name}".strip(),
            "student_number": student.student_id,
        },
        link_url="/app/immigration",
        entity_type="immigration_reminder",
        entity_id=row.id,
    )


def run_expiry_reminders(
    db: DBSession,
    *,
    today: date | None = None,
) -> dict:
    """Reconcile expiry alerts against verified profiles.

    Returns counts of what changed, which is what an operator needs to know:
    ``evaluated`` profiles, ``created`` new alerts and ``resolved`` cleared ones.
    Running it twice in a row returns ``created=0`` the second time.
    """
    today = today or date.today()
    now = _now()

    profiles = (
        db.query(ImmigrationProfile, Student)
        .join(Student, Student.id == ImmigrationProfile.student_id)
        .filter(ImmigrationProfile.verification_status == "VERIFIED")
        .all()
    )

    created = 0
    resolved = 0
    verified_profile_ids: set[uuid.UUID] = set()

    for profile, student in profiles:
        verified_profile_ids.add(profile.id)

        current: dict[tuple[str, str, date], int] = {}
        for document_type in REMINDER_DOCUMENT_TYPES:
            expiry = getattr(profile, DOCUMENT_FIELDS[document_type], None)
            if expiry is None:
                continue
            status, days = calculate_document_status(expiry, today)
            if status in REMINDER_TIERS and days is not None:
                current[(document_type, status, expiry)] = days

        open_rows = (
            db.query(ImmigrationReminder)
            .filter(
                ImmigrationReminder.immigration_profile_id == profile.id,
                ImmigrationReminder.resolved_at.is_(None),
            )
            .all()
        )
        open_keys = {
            (row.document_type, row.tier, row.expiry_date): row for row in open_rows
        }

        for (document_type, tier, expiry), days in current.items():
            existing = open_keys.get((document_type, tier, expiry))
            if existing is not None:
                continue
            # The alert identity is (profile, document type, tier, expiry), and
            # the unique index covers resolved rows too. A correction that is
            # later reversed (the same expiry re-qualifies) must reopen the
            # existing alert rather than insert a duplicate the index refuses.
            reopened = (
                db.query(ImmigrationReminder)
                .filter(
                    ImmigrationReminder.immigration_profile_id == profile.id,
                    ImmigrationReminder.document_type == document_type,
                    ImmigrationReminder.tier == tier,
                    ImmigrationReminder.expiry_date == expiry,
                )
                .first()
            )
            if reopened is not None:
                reopened.resolved_at = None
                reopened.resolution = None
                reopened.notified_at = now
                db.flush()
                _notify(
                    db, profile=profile, student=student, row=reopened, days_remaining=days
                )
                created += 1
                continue
            row = ImmigrationReminder(
                immigration_profile_id=profile.id,
                student_id=student.id,
                document_type=document_type,
                tier=tier,
                expiry_date=expiry,
                notified_at=now,
                created_at=now,
            )
            db.add(row)
            db.flush()
            _notify(
                db, profile=profile, student=student, row=row, days_remaining=days
            )
            created += 1

        for key, row in open_keys.items():
            if key in current:
                continue
            row.resolved_at = now
            row.resolution = _resolution(profile, student, row)
            resolved += 1

    # A profile that lost verification must not keep an open official warning.
    stale = db.query(ImmigrationReminder).filter(
        ImmigrationReminder.resolved_at.is_(None)
    )
    if verified_profile_ids:
        stale = stale.filter(
            ImmigrationReminder.immigration_profile_id.notin_(verified_profile_ids)
        )
    for row in stale.all():
        profile = db.get(ImmigrationProfile, row.immigration_profile_id)
        student = db.get(Student, row.student_id)
        row.resolved_at = now
        row.resolution = (
            _resolution(profile, student, row) if profile is not None else "CORRECTED"
        )
        resolved += 1

    db.commit()

    return {
        "evaluated": len(profiles),
        "created": created,
        "resolved": resolved,
        "today": today,
    }


def list_reminders(
    db: DBSession,
    *,
    status: str = "open",
    document_type: str | None = None,
    tier: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Reminder history, newest first, with the student it concerns."""
    query = (
        db.query(ImmigrationReminder, Student)
        .join(Student, Student.id == ImmigrationReminder.student_id)
        .order_by(
            ImmigrationReminder.resolved_at.is_(None).desc(),
            ImmigrationReminder.expiry_date.asc(),
            ImmigrationReminder.created_at.desc(),
        )
    )
    if status == "open":
        query = query.filter(ImmigrationReminder.resolved_at.is_(None))
    elif status == "resolved":
        query = query.filter(ImmigrationReminder.resolved_at.is_not(None))
    if document_type:
        query = query.filter(ImmigrationReminder.document_type == document_type)
    if tier:
        query = query.filter(ImmigrationReminder.tier == tier)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Student.student_id.ilike(term),
                Student.first_name.ilike(term),
                Student.last_name.ilike(term),
            )
        )

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [
            {
                "id": row.id,
                "student_id": row.student_id,
                "student_number": student.student_id,
                "student_name": f"{student.first_name} {student.last_name}".strip(),
                "document_type": row.document_type,
                "tier": row.tier,
                "expiry_date": row.expiry_date,
                "notified_at": row.notified_at,
                "resolved_at": row.resolved_at,
                "resolution": row.resolution,
            }
            for row, student in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


__all__ = [
    "DOCUMENT_FIELDS",
    "list_reminders",
    "run_expiry_reminders",
]
