"""Migration report for provisioned student accounts.

Answers the questions an international office actually asks after an import:
who has an account, who can still not sign in, who is waiting on an activation
link, and who needs a person rather than a form.

Deliberately excludes every credential: no passwords, no activation tokens, no
raw addresses. A report gets exported, forwarded and printed; it must not be a
list of working links.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.auth.activation import mask_email
from app.models.academic import ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatus,
    AcademicPlacement,
)
from app.models.identity import Student, StudentStatus, User
from app.models.session import AccountActivationToken

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

LIVE_ADMISSION_STATUSES = (
    AcademicAdmissionStatus.ADMITTED.value,
    AcademicAdmissionStatus.ACTIVE.value,
)

#: Reasons a record needs a human. Each is a category, not a sentence, so the
#: report stays localisable and countable.
REASON_DISABLED = "ACCOUNT_DISABLED"
REASON_LINK_MISSING = "ACTIVATION_LINK_MISSING"
REASON_LINK_EXPIRED = "ACTIVATION_LINK_EXPIRED"
REASON_NO_INTAKE = "NO_INTAKE_ASSIGNMENT"
REASON_NO_PLACEMENT = "NO_PLACEMENT"
REASON_RECORD_INACTIVE = "STUDENT_RECORD_INACTIVE"


def _latest_tokens(db: DBSession, user_ids: list) -> dict:
    if not user_ids:
        return {}
    rows = (
        db.query(AccountActivationToken)
        .filter(AccountActivationToken.user_id.in_(user_ids))
        .order_by(AccountActivationToken.created_at.desc())
        .all()
    )
    latest: dict = {}
    for row in rows:
        latest.setdefault(row.user_id, row)
    return latest


def student_account_migration_report(db: DBSession) -> dict:
    """Point-in-time state of every student account in the portal."""
    students = db.query(Student).order_by(Student.student_id).all()
    user_ids = [student.user_id for student in students]
    users = (
        {user.id: user for user in db.query(User).filter(User.id.in_(user_ids)).all()}
        if user_ids
        else {}
    )
    tokens = _latest_tokens(db, user_ids)

    live_admissions = (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.student_id.in_([s.id for s in students]),
            AcademicAdmission.status.in_(LIVE_ADMISSION_STATUSES),
        )
        .order_by(AcademicAdmission.created_at.desc())
        .all()
        if students
        else []
    )
    admission_by_student: dict = {}
    for admission in live_admissions:
        admission_by_student.setdefault(admission.student_id, admission)

    open_placements = (
        db.query(AcademicPlacement)
        .filter(
            AcademicPlacement.student_id.in_([s.id for s in students]),
            AcademicPlacement.ended_at.is_(None),
        )
        .all()
        if students
        else []
    )
    placement_by_student = {placement.student_id: placement for placement in open_placements}

    offering_ids = {
        placement.program_offering_id for placement in open_placements
    } | {
        admission.admitted_program_offering_id
        for admission in live_admissions
        if admission.admitted_program_offering_id is not None
    }
    offerings = (
        {
            offering.id: offering
            for offering in db.query(ProgramOffering)
            .filter(ProgramOffering.id.in_(offering_ids))
            .all()
        }
        if offering_ids
        else {}
    )

    now = datetime.now(UTC)
    totals = {
        "students": len(students),
        "accounts": len(users),
        "activated": 0,
        "activation_pending": 0,
        "activation_expired": 0,
        "activation_link_missing": 0,
        "disabled_accounts": 0,
        "no_intake_assignment": 0,
        "no_placement": 0,
        "missing_contact": 0,
    }
    by_intake: dict[str, dict] = {}
    interventions: list[dict] = []

    for student in students:
        user = users.get(student.user_id)
        token = tokens.get(student.user_id)
        admission = admission_by_student.get(student.id)
        placement = placement_by_student.get(student.id)

        offering = None
        if placement is not None:
            offering = offerings.get(placement.program_offering_id)
        if offering is None and admission is not None:
            offering = offerings.get(admission.admitted_program_offering_id)
        intake_code = (
            offering.academic_period.code
            if offering is not None and offering.academic_period is not None
            else None
        )

        reasons: list[str] = []
        if user is None:
            reasons.append(REASON_LINK_MISSING)
        else:
            if not user.is_active:
                totals["disabled_accounts"] += 1
                reasons.append(REASON_DISABLED)
            if user.activation_required:
                if token is None:
                    totals["activation_link_missing"] += 1
                    reasons.append(REASON_LINK_MISSING)
                elif token.used_at is None and token.expires_at <= now:
                    totals["activation_expired"] += 1
                    reasons.append(REASON_LINK_EXPIRED)
                else:
                    totals["activation_pending"] += 1
            else:
                totals["activated"] += 1

        if admission is None:
            totals["no_intake_assignment"] += 1
            reasons.append(REASON_NO_INTAKE)
        if placement is None:
            totals["no_placement"] += 1
            reasons.append(REASON_NO_PLACEMENT)
        if student.status != StudentStatus.ACTIVE:
            reasons.append(REASON_RECORD_INACTIVE)

        bucket = by_intake.setdefault(
            intake_code or "UNASSIGNED",
            {
                "intake": intake_code or "UNASSIGNED",
                "students": 0,
                "activated": 0,
                "activation_pending": 0,
                "needs_intervention": 0,
            },
        )
        bucket["students"] += 1
        if user is not None and not user.activation_required:
            bucket["activated"] += 1
        elif user is not None and user.activation_required:
            bucket["activation_pending"] += 1
        if reasons:
            bucket["needs_intervention"] += 1

        if reasons:
            interventions.append(
                {
                    "student_number": student.student_id,
                    "email_masked": mask_email(user.email) if user else None,
                    "intake": intake_code,
                    "account_state": (
                        "ACTIVATION_REQUIRED"
                        if user is not None and user.activation_required
                        else "ACTIVE"
                        if user is not None
                        else "MISSING"
                    ),
                    "reasons": reasons,
                }
            )

    return {
        "generated_at": now.isoformat(),
        "totals": totals,
        "by_intake": sorted(by_intake.values(), key=lambda item: item["intake"]),
        "interventions": interventions[:500],
        "interventions_truncated": len(interventions) > 500,
        "excludes": ["passwords", "activation_tokens", "raw_email_addresses"],
    }


__all__ = ["student_account_migration_report"]
