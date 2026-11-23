"""Read-only academic placement resolution for a student.

Phase 8b removes the three compatibility columns from ``students``. Student
responses and reports resolve the effective programme with this precedence:
ACTIVE, then ADMITTED, then the latest COMPLETED/WITHDRAWN fallback. PENDING
and CANCELLED never participate. The current offering comes only from the one
open placement owned by the effective live admission; a terminal episode
remains historical and never supplies the current offering. Nothing here
writes academic data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import case, func
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import aliased

from app.models.academic import Major, Program, ProgramOffering
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatus,
    AcademicPlacement,
)

if TYPE_CHECKING:
    import uuid

#: Statuses that made an admission effective for the student-facing academic
#: view. PENDING future admissions and CANCELLED episodes deliberately do not
#: replace the programme shown for the student.
EFFECTIVE_ADMISSION_STATUSES: tuple[str, ...] = (
    AcademicAdmissionStatus.ADMITTED.value,
    AcademicAdmissionStatus.ACTIVE.value,
    AcademicAdmissionStatus.COMPLETED.value,
    AcademicAdmissionStatus.WITHDRAWN.value,
)

#: Statuses that may still own a current placement. COMPLETED and WITHDRAWN
#: are historical fallbacks for the programme, but not for the placement.
LIVE_ADMISSION_STATUSES: tuple[str, ...] = (
    AcademicAdmissionStatus.ADMITTED.value,
    AcademicAdmissionStatus.ACTIVE.value,
)

#: ACTIVE is the programme in force. ADMITTED is the next eligible live state,
#: and COMPLETED/WITHDRAWN are only a historical fallback when neither exists.
EFFECTIVE_ADMISSION_PRIORITY: tuple[tuple[str, int], ...] = (
    (AcademicAdmissionStatus.ACTIVE.value, 0),
    (AcademicAdmissionStatus.ADMITTED.value, 1),
    (AcademicAdmissionStatus.COMPLETED.value, 2),
    (AcademicAdmissionStatus.WITHDRAWN.value, 2),
)


def effective_admission_priority(admission):
    """Ordering expression shared by the Python and SQL selection paths."""
    return case(
        *[
            (admission.status == status, priority)
            for status, priority in EFFECTIVE_ADMISSION_PRIORITY
        ],
        else_=len(EFFECTIVE_ADMISSION_PRIORITY),
    )


@dataclass(frozen=True)
class StudentAcademicSnapshot:
    """The effective admission and current placement for one student."""

    admission: AcademicAdmission | None
    placement: AcademicPlacement | None
    program: Program | None
    major: Major | None
    offering: ProgramOffering | None

    @property
    def program_id(self) -> uuid.UUID | None:
        return self.program.id if self.program is not None else None

    @property
    def major_id(self) -> uuid.UUID | None:
        return self.major.id if self.major is not None else None

    @property
    def offering_id(self) -> uuid.UUID | None:
        return self.offering.id if self.offering is not None else None

    @property
    def period_id(self) -> uuid.UUID | None:
        return self.offering.academic_period_id if self.offering is not None else None


def effective_admission(db: DBSession, student_id: uuid.UUID) -> AcademicAdmission | None:
    """Return the latest admission that governed the student's programme."""
    return (
        db.query(AcademicAdmission)
        .filter(
            AcademicAdmission.student_id == student_id,
            AcademicAdmission.status.in_(EFFECTIVE_ADMISSION_STATUSES),
        )
        .order_by(
            effective_admission_priority(AcademicAdmission),
            AcademicAdmission.created_at.desc(),
            AcademicAdmission.id.desc(),
        )
        .first()
    )


def effective_live_admission(
    db: DBSession, student_id: uuid.UUID
) -> AcademicAdmission | None:
    """Return the effective admission only when it is still live."""
    admission = effective_admission(db, student_id)
    if admission is None or admission.status not in LIVE_ADMISSION_STATUSES:
        return None
    return admission


def current_placement(db: DBSession, student_id: uuid.UUID) -> AcademicPlacement | None:
    """Return the open placement owned by the effective live admission."""
    admission = effective_live_admission(db, student_id)
    if admission is None:
        return None
    return (
        db.query(AcademicPlacement)
        .filter(
            AcademicPlacement.student_id == student_id,
            AcademicPlacement.admission_id == admission.id,
            AcademicPlacement.ended_at.is_(None),
        )
        .first()
    )


def student_academic_snapshot(
    db: DBSession, student_id: uuid.UUID
) -> StudentAcademicSnapshot:
    """Resolve the effective programme and current offering without projections."""
    admission = effective_admission(db, student_id)
    live_admission = effective_live_admission(db, student_id)
    placement = current_placement(db, student_id)

    offering = None
    if placement is not None:
        offering = db.get(ProgramOffering, placement.program_offering_id)
    if offering is None and live_admission is not None:
        offering = db.get(ProgramOffering, live_admission.admitted_program_offering_id)

    program = None
    if admission is not None:
        program_id = admission.current_program_id or admission.admitted_program_id
        if program_id is not None:
            program = db.get(Program, program_id)
    if program is None and offering is not None and offering.program_id is not None:
        program = db.get(Program, offering.program_id)

    major = db.get(Major, program.major_id) if program is not None else None
    return StudentAcademicSnapshot(
        admission=admission,
        placement=placement,
        program=program,
        major=major,
        offering=offering,
    )


def latest_effective_admission_subquery(db: DBSession):
    """Latest effective admission per student, for SQL reports and filters."""
    admission = aliased(AcademicAdmission)
    ranked = (
        db.query(
            admission.student_id.label("student_id"),
            admission.id.label("admission_id"),
            func.coalesce(
                admission.current_program_id, admission.admitted_program_id
            ).label("program_id"),
            func.row_number()
            .over(
                partition_by=admission.student_id,
                order_by=(
                    effective_admission_priority(admission),
                    admission.created_at.desc(),
                    admission.id.desc(),
                ),
            )
            .label("row_number"),
        )
        .filter(admission.status.in_(EFFECTIVE_ADMISSION_STATUSES))
        .subquery()
    )
    return (
        db.query(
            ranked.c.student_id,
            ranked.c.admission_id,
            ranked.c.program_id,
        )
        .filter(ranked.c.row_number == 1)
        .subquery()
    )


__all__ = [
    "EFFECTIVE_ADMISSION_STATUSES",
    "LIVE_ADMISSION_STATUSES",
    "StudentAcademicSnapshot",
    "current_placement",
    "effective_admission",
    "effective_admission_priority",
    "effective_live_admission",
    "latest_effective_admission_subquery",
    "student_academic_snapshot",
]
