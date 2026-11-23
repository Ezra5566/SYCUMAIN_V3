"""Examination service.

The rules this module owns
--------------------------
* **One examination, many sections.** A shared final is created once and linked
  to every teaching section sitting it. It has one date, one room, one set of
  instructions and one publication decision. Duplicating it per section is
  forbidden by the ``examination_sections`` model rather than by convention.
* **Eligibility comes from enrollments.** A student may sit an examination only
  if they are enrolled in one of its participating sections and their student
  record is active. Programme placement is respected through the enrollment
  itself: a section belongs to a course and an intake, and a student enrolled in
  a different programme's section is simply not eligible.
* **Teachers see their own sections only.** The scope is recomputed on every
  request from ``teacher_assignments``; a teacher cannot widen it by passing an
  examination id, and cannot record a result for a paper they do not teach.
* **Unpublished results do not exist for students.** ``published_at`` is the
  gate, and the student payload has no score field to leak while it is NULL.
* **Corrections supersede.** The previous score, its recorder and the reason for
  the change stay readable, and the change is audited in the same transaction.
* **Nothing is computed.** No GPA, no percentage, no pass mark, no letter-grade
  derivation, no credits. ``max_score`` is a ceiling staff supplied and
  ``letter_grade`` is what staff typed.

Scheduling conflicts are detected only where the model supports it reliably:
same room, overlapping time, same date; or two examinations that share an
enrolled student on overlapping times. Room availability outside examinations
(timetable slots) is deliberately not consulted — a class schedule is not a room
booking system, and treating it as one would produce false conflicts.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - SQLAlchemy resolves UUID at runtime
from collections import defaultdict
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.models.academic import (
    AcademicPeriod,
    ClassSection,
    ClassSectionProgramOffering,
    Course,
    Enrollment,
    EnrollmentStatus,
    ProgramOffering,
    TeacherAssignment,
)
from app.models.admission import (
    AcademicAdmission,
    AcademicAdmissionStatus,
    AcademicPlacement,
)
from app.models.examination import (
    Examination,
    ExaminationResult,
    ExaminationSection,
    ExaminationStatus,
)
from app.models.identity import Staff, Student, StudentStatus, User

if TYPE_CHECKING:
    from app.schemas.examination import (
        ExaminationCancel,
        ExaminationCreate,
        ExaminationUpdate,
        ResultCorrect,
        ResultCreate,
    )

#: Roles that administer the whole examination calendar.
EXAM_STAFF_ROLES: frozenset[str] = frozenset({"ADMIN", "MANAGEMENT"})

#: Enrollments that make a student eligible to sit. ``COMPLETED`` is included
#: because a completed enrollment is still a real enrollment in that section —
#: whether it matters is decided by the examination's own date.
ELIGIBLE_ENROLLMENT_STATUSES: tuple[str, ...] = (
    EnrollmentStatus.ENROLLED.value,
    EnrollmentStatus.COMPLETED.value,
)

#: Admission episodes that still permit a student to be assessed. A student
#: whose only admission episode is terminal (completed, withdrawn or cancelled)
#: is not sitting new papers inside that episode.
LIVE_ADMISSION_STATUSES: tuple[str, ...] = (
    AcademicAdmissionStatus.PENDING.value,
    AcademicAdmissionStatus.ADMITTED.value,
    AcademicAdmissionStatus.ACTIVE.value,
)

MIN_REASON_LENGTH = 10
MAX_PAGE_SIZE = 100

#: How many rows a dashboard needs. Enough to be useful, small enough that the
#: response stays a summary rather than a list endpoint.
DASHBOARD_LIMIT = 8


class ExaminationError(ValueError):
    """A refused examination operation carrying a stable, localisable code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


# ── Time helpers ──


def _now() -> datetime:
    return datetime.now(UTC)


def _today() -> date:
    return _now().date()


def _current_time() -> time:
    return _now().timetz().replace(tzinfo=None)


# ── Access ──


def _role_names(user: User) -> set[str]:
    return {role.name for role in user.roles}


def ensure_staff(user: User) -> None:
    """Only Admin and Management administer the examination calendar."""
    if not (_role_names(user) & EXAM_STAFF_ROLES):
        raise ExaminationError(
            "EXAM_FORBIDDEN",
            "You do not have access to examination administration.",
            status_code=403,
        )


def teacher_section_ids(db: DBSession, user: User) -> set[uuid.UUID]:
    """Sections a teacher is actively assigned to, recomputed per request."""
    staff = db.query(Staff).filter(Staff.user_id == user.id).first()
    if staff is None or not staff.is_active:
        return set()
    return {
        row[0]
        for row in db.query(TeacherAssignment.class_section_id)
        .filter(
            TeacherAssignment.staff_id == staff.id,
            TeacherAssignment.is_active.is_(True),
        )
        .all()
    }


def student_record(db: DBSession, user: User) -> Student:
    student = db.query(Student).filter(Student.user_id == user.id).first()
    if student is None:
        raise ExaminationError(
            "EXAM_NO_STUDENT_RECORD",
            "No student record is linked to this account.",
            status_code=404,
        )
    return student


def _assessable_section_ids(
    db: DBSession, student_id: uuid.UUID
) -> set[uuid.UUID]:
    """Sections this student may currently be assessed in.

    This is the student-facing twin of staff eligibility: a stale enrollment in
    a section their placement has moved away from must not advertise an
    upcoming paper they will not sit.
    """
    return {
        row[0]
        for row in db.query(Enrollment.class_section_id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(
            Enrollment.student_id == student_id,
            Enrollment.status.in_(ELIGIBLE_ENROLLMENT_STATUSES),
            _student_may_sit(),
        )
        .all()
    }


def _student_may_sit():
    """SQL predicate: this enrollment represents a student who may be assessed.

    Two institutional facts beyond the enrollment row decide it, and both are
    read from the records that already own them:

    * **Placement.** A student whose current placement puts them in a
      programme offering the section does not serve belongs to another cohort,
      even when a stale enrollment row still says ``ENROLLED``. A placement is
      authoritative for the current term, so the section must declare that it
      serves that offering. A student with no placement at all — a legacy or
      imported student — is judged by their enrollment alone.
    * **Admission lifecycle.** A student whose admission episodes are all
      terminal (completed, withdrawn or cancelled) cannot be assessed again in
      that episode. A student with no admission record at all is a legacy or
      imported student and is judged by their enrollment alone.

    The inner ``served_by_section`` subquery is explicitly correlated to the
    outer enrollment and placement; without that SQLAlchemy re-introduces
    ``enrollments`` into the subquery's FROM clause and the comparison silently
    becomes a cartesian one.
    """
    served_by_section = (
        select(ClassSectionProgramOffering.class_section_id)
        .where(
            ClassSectionProgramOffering.class_section_id
            == Enrollment.class_section_id,
            ClassSectionProgramOffering.program_offering_id
            == AcademicPlacement.program_offering_id,
        )
        .correlate(Enrollment, AcademicPlacement)
        .exists()
    )
    contradicted_by_placement = (
        select(AcademicPlacement.id)
        .where(
            AcademicPlacement.student_id == Enrollment.student_id,
            AcademicPlacement.ended_at.is_(None),
            ~served_by_section,
        )
        .correlate(Enrollment)
        .exists()
    )
    has_admission = (
        select(AcademicAdmission.id)
        .where(AcademicAdmission.student_id == Student.id)
        .exists()
    )
    has_live_admission = (
        select(AcademicAdmission.id)
        .where(
            AcademicAdmission.student_id == Student.id,
            AcademicAdmission.status.in_(LIVE_ADMISSION_STATUSES),
        )
        .exists()
    )
    return and_(
        Student.status == StudentStatus.ACTIVE.value,
        ~contradicted_by_placement,
        or_(~has_admission, has_live_admission),
    )


# ── Loading ──


def _load_examination(db: DBSession, examination_id: uuid.UUID) -> Examination:
    examination = (
        db.query(Examination).filter(Examination.id == examination_id).first()
    )
    if examination is None:
        raise ExaminationError(
            "EXAM_NOT_FOUND", "Examination not found.", status_code=404
        )
    return examination


def _section_rows(
    db: DBSession, section_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    """Course, intake and code for a set of sections."""
    if not section_ids:
        return {}
    rows = (
        db.query(
            ClassSection.id,
            ClassSection.section_code,
            Course.code,
            Course.name,
            AcademicPeriod.name,
            ClassSection.academic_period_id,
            ClassSection.course_id,
        )
        .join(Course, Course.id == ClassSection.course_id)
        .join(AcademicPeriod, AcademicPeriod.id == ClassSection.academic_period_id)
        .filter(ClassSection.id.in_(section_ids))
        .all()
    )
    offering_rows = (
        db.query(
            ClassSectionProgramOffering.class_section_id,
            ProgramOffering.name,
        )
        .join(
            ProgramOffering,
            ProgramOffering.id == ClassSectionProgramOffering.program_offering_id,
        )
        .filter(ClassSectionProgramOffering.class_section_id.in_(section_ids))
        .order_by(ProgramOffering.name)
        .all()
    )
    offerings: dict[uuid.UUID, list[str]] = defaultdict(list)
    for section_id, offering_name in offering_rows:
        offerings[section_id].append(offering_name)
    return {
        row[0]: {
            "section_code": row[1],
            "course_code": row[2],
            "course_name": row[3],
            "period_name": row[4],
            "academic_period_id": row[5],
            "course_id": row[6],
            "offerings": offerings.get(row[0], []),
        }
        for row in rows
    }


def _section_label(info: dict) -> str:
    """Human label for a section, built from real identifiers only."""
    course = info.get("course_code") or info.get("course_name") or "—"
    section = info.get("section_code")
    return f"{course} · {section}" if section else course


def _eligible_map(
    db: DBSession, examination_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """``examination_id -> {student_id}`` from live enrollments."""
    if not examination_ids:
        return {}
    rows = (
        db.query(
            ExaminationSection.examination_id,
            Enrollment.student_id,
        )
        .join(
            Enrollment,
            Enrollment.class_section_id == ExaminationSection.class_section_id,
        )
        .join(Student, Student.id == Enrollment.student_id)
        .filter(
            ExaminationSection.examination_id.in_(examination_ids),
            Enrollment.status.in_(ELIGIBLE_ENROLLMENT_STATUSES),
            _student_may_sit(),
        )
        .distinct()
        .all()
    )
    result: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for examination_id, student_id in rows:
        result[examination_id].add(student_id)
    return result


def _result_count_map(
    db: DBSession, examination_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not examination_ids:
        return {}
    rows = (
        db.query(
            ExaminationResult.examination_id,
            func.count(ExaminationResult.id),
        )
        .filter(
            ExaminationResult.examination_id.in_(examination_ids),
            ExaminationResult.superseded_at.is_(None),
        )
        .group_by(ExaminationResult.examination_id)
        .all()
    )
    return {row[0]: row[1] for row in rows}


def _publisher_names(
    db: DBSession, examinations: list[Examination]
) -> dict[uuid.UUID, str]:
    ids = {e.published_by_id for e in examinations if e.published_by_id}
    if not ids:
        return {}
    return dict(
        db.query(User.id, User.full_name).filter(User.id.in_(ids)).all()
    )


def _section_eligible_counts(
    db: DBSession, section_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """``class_section_id -> distinct eligible students`` for one examination.

    An examination that serves several sections reports how many students each
    of those sections brings to it, so a dashboard can show the per-section
    intake instead of a single institution-wide total.
    """
    if not section_ids:
        return {}
    rows = (
        db.query(
            Enrollment.class_section_id,
            func.count(func.distinct(Enrollment.student_id)),
        )
        .join(Student, Student.id == Enrollment.student_id)
        .filter(
            Enrollment.class_section_id.in_(section_ids),
            Enrollment.status.in_(ELIGIBLE_ENROLLMENT_STATUSES),
            _student_may_sit(),
        )
        .group_by(Enrollment.class_section_id)
        .all()
    )
    return dict(rows)


def _payload_reference(
    db: DBSession, examinations: list[Examination]
) -> dict:
    """Names and per-section counts for a page of examinations, read in bulk.

    Deliberately reads columns rather than ``Course``/``AcademicPeriod``
    entities. Those models carry ``lazy="selectin"`` collections
    (``Course.classes``, ``AcademicPeriod.classes``, and every collection on
    ``ClassSection``), so loading one entity per examination cascades into
    hundreds of statements and makes a page load take seconds under any
    concurrent use. A page of 25 examinations needs a fixed handful of queries,
    not one per row.
    """
    section_ids = sorted(
        {
            section.class_section_id
            for examination in examinations
            for section in examination.sections
        }
    )
    offering_ids = {
        examination.program_offering_id
        for examination in examinations
        if examination.program_offering_id is not None
    }
    offerings = (
        dict(
            db.query(ProgramOffering.id, ProgramOffering.name)
            .filter(ProgramOffering.id.in_(offering_ids))
            .all()
        )
        if offering_ids
        else {}
    )
    courses = {
        row[0]: (row[1], row[2])
        for row in db.query(Course.id, Course.code, Course.name)
        .filter(Course.id.in_({examination.course_id for examination in examinations}))
        .all()
    }
    periods = dict(
        db.query(AcademicPeriod.id, AcademicPeriod.name)
        .filter(
            AcademicPeriod.id.in_
            ({examination.academic_period_id for examination in examinations})
        )
        .all()
    )
    return {
        "sections": _section_rows(db, section_ids),
        "section_counts": _section_eligible_counts(db, section_ids),
        "offerings": offerings,
        "courses": courses,
        "periods": periods,
    }


def _exam_payload(
    db: DBSession,
    examination: Examination,
    *,
    eligible: set[uuid.UUID] | None = None,
    result_count: int | None = None,
    publisher_name: str | None = None,
    reference: dict | None = None,
) -> dict:
    # A caller rendering a whole page builds this once for every examination;
    # a single-record response builds it for one.
    reference = reference or _payload_reference(db, [examination])
    section_ids = [section.class_section_id for section in examination.sections]
    info = reference["sections"]
    section_counts = reference["section_counts"]
    sections = [
        {
            "class_section_id": section_id,
            "section_code": info.get(section_id, {}).get("section_code"),
            "label": _section_label(info.get(section_id, {})),
            "course_code": info.get(section_id, {}).get("course_code"),
            "course_name": info.get(section_id, {}).get("course_name"),
            "academic_period_name": info.get(section_id, {}).get("period_name"),
            "offerings": info.get(section_id, {}).get("offerings", []),
            "eligible_count": section_counts.get(section_id, 0),
        }
        for section_id in section_ids
    ]
    course_code, course_name = reference["courses"].get(
        examination.course_id, (None, None)
    )
    period_name = reference["periods"].get(examination.academic_period_id)
    offering_name = (
        reference["offerings"].get(examination.program_offering_id)
        if examination.program_offering_id
        else None
    )
    if publisher_name is None and examination.published_by_id:
        publisher_name = (
            db.query(User.full_name)
            .filter(User.id == examination.published_by_id)
            .scalar()
        )

    return {
        "id": examination.id,
        "title": examination.title,
        "examination_type": examination.examination_type,
        "course_id": examination.course_id,
        "course_code": course_code,
        "course_name": course_name,
        "academic_period_id": examination.academic_period_id,
        "academic_period_name": period_name,
        "program_offering_id": examination.program_offering_id,
        "program_offering_name": offering_name,
        "exam_date": examination.exam_date,
        "start_time": examination.start_time,
        "end_time": examination.end_time,
        "location": examination.location,
        "instructions": examination.instructions,
        "max_score": (
            float(examination.max_score) if examination.max_score is not None else None
        ),
        "status": examination.status,
        "cancelled_at": examination.cancelled_at,
        "cancellation_reason": examination.cancellation_reason,
        "published_at": examination.published_at,
        "published_by_name": publisher_name,
        "sections": sections,
        "section_count": len(sections),
        "eligible_count": len(eligible) if eligible is not None else 0,
        "result_count": result_count or 0,
        "created_at": examination.created_at,
    }


# ── Scoping ──


def _visible_query(db: DBSession, user: User):
    """Examinations this user may see, as a query.

    Admin/Management: everything. Teacher: examinations containing a section
    they are assigned to. Student: examinations containing a section they are
    enrolled in.
    """
    query = db.query(Examination)
    roles = _role_names(user)

    if roles & EXAM_STAFF_ROLES:
        return query

    if "TEACHER" in roles:
        section_ids = teacher_section_ids(db, user)
        if not section_ids:
            return query.filter(False)
        return query.join(
            ExaminationSection,
            ExaminationSection.examination_id == Examination.id,
        ).filter(ExaminationSection.class_section_id.in_(section_ids))

    if "STUDENT" in roles:
        student = db.query(Student).filter(Student.user_id == user.id).first()
        # Current enrollment **and** a placement that does not contradict it.
        section_ids = _assessable_section_ids(db, student.id) if student else set()
        if not section_ids:
            return query.filter(False)
        return query.join(
            ExaminationSection,
            ExaminationSection.examination_id == Examination.id,
        ).filter(ExaminationSection.class_section_id.in_(section_ids))

    return query.filter(False)


def can_manage_results(db: DBSession, user: User, examination: Examination) -> bool:
    """Whether this user may record a result for this examination."""
    roles = _role_names(user)
    if roles & EXAM_STAFF_ROLES:
        return True
    section_ids = teacher_section_ids(db, user)
    if not section_ids:
        return False
    return bool(
        section_ids
        & {section.class_section_id for section in examination.sections}
    )


# ── Listing ──


def list_examinations(
    db: DBSession,
    user: User,
    *,
    search: str | None = None,
    period_id: uuid.UUID | None = None,
    status: str | None = None,
    published: str | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict:
    """Examinations visible to the caller, newest schedule first."""
    query = _visible_query(db, user).distinct()

    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Examination.title.ilike(term),
                Examination.location.ilike(term),
            )
        )
    if period_id is not None:
        query = query.filter(Examination.academic_period_id == period_id)
    if status in ("SCHEDULED", "CANCELLED"):
        query = query.filter(Examination.status == status)
    if published == "published":
        query = query.filter(Examination.published_at.is_not(None))
    elif published == "unpublished":
        query = query.filter(Examination.published_at.is_(None))

    total = query.count()
    examinations = (
        query.order_by(Examination.exam_date.desc(), Examination.start_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    ids = [examination.id for examination in examinations]
    eligible = _eligible_map(db, ids)
    results = _result_count_map(db, ids)
    publishers = _publisher_names(db, examinations)
    reference = _payload_reference(db, examinations)

    return {
        "items": [
            _exam_payload(
                db,
                examination,
                eligible=eligible.get(examination.id, set()),
                result_count=results.get(examination.id, 0),
                publisher_name=publishers.get(examination.published_by_id),
                reference=reference,
            )
            for examination in examinations
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def examination_detail(db: DBSession, user: User, examination_id: uuid.UUID) -> dict:
    """Staff view: schedule, eligible students and recorded results."""
    examination = _load_examination(db, examination_id)

    # The detail payload contains every eligible student and every recorded
    # result, so it is a staff surface. A student reads their own schedule and
    # their own published result through ``/me``; exposing this shape to them
    # would leak the whole cohort's marks.
    roles = _role_names(user)
    if not (roles & EXAM_STAFF_ROLES) and "TEACHER" not in roles:
        raise ExaminationError(
            "EXAM_NOT_FOUND", "Examination not found.", status_code=404
        )

    visible = (
        _visible_query(db, user)
        .filter(Examination.id == examination_id)
        .first()
    )
    if visible is None:
        # A teacher outside the section, or a student in another programme,
        # gets the same answer as for an examination that does not exist: the
        # schedule is not theirs to learn about.
        raise ExaminationError(
            "EXAM_NOT_FOUND", "Examination not found.", status_code=404
        )

    eligible_rows = _eligible_students(db, examination)
    results = _results_for(db, examination.id)

    return {
        "examination": _exam_payload(
            db,
            examination,
            eligible={row["student_id"] for row in eligible_rows},
            result_count=len([r for r in results if r["is_current"]]),
        ),
        "eligible_students": eligible_rows,
        "results": results,
    }


def _eligible_students(db: DBSession, examination: Examination) -> list[dict]:
    """Every active student enrolled in any participating section."""
    section_ids = [section.class_section_id for section in examination.sections]
    if not section_ids:
        return []
    info = _section_rows(db, section_ids)
    rows = (
        db.query(
            Student.id,
            Student.student_id,
            User.full_name,
            Enrollment.class_section_id,
        )
        .join(Enrollment, Enrollment.student_id == Student.id)
        .join(User, User.id == Student.user_id)
        .filter(
            Enrollment.class_section_id.in_(section_ids),
            Enrollment.status.in_(ELIGIBLE_ENROLLMENT_STATUSES),
            _student_may_sit(),
        )
        .all()
    )
    recorded = {
        row[0]
        for row in db.query(ExaminationResult.student_id)
        .filter(
            ExaminationResult.examination_id == examination.id,
            ExaminationResult.superseded_at.is_(None),
        )
        .all()
    }
    placement_offerings = _placement_offering_names(
        db, {row[0] for row in rows}
    )

    grouped: dict[uuid.UUID, dict] = {}
    for student_id, student_number, full_name, class_section_id in rows:
        entry = grouped.setdefault(
            student_id,
            {
                "student_id": student_id,
                "student_number": student_number,
                "student_name": full_name,
                "program_offering_name": placement_offerings.get(student_id),
                "section_labels": [],
                "has_result": student_id in recorded,
            },
        )
        label = _section_label(info.get(class_section_id, {}))
        if label not in entry["section_labels"]:
            entry["section_labels"].append(label)

    return sorted(grouped.values(), key=lambda row: row["student_name"])


def _placement_offering_names(
    db: DBSession, student_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Current placement's offering for each student, when one exists."""
    if not student_ids:
        return {}
    rows = (
        db.query(
            AcademicPlacement.student_id,
            ProgramOffering.name,
        )
        .join(
            ProgramOffering,
            ProgramOffering.id == AcademicPlacement.program_offering_id,
        )
        .filter(
            AcademicPlacement.student_id.in_(student_ids),
            AcademicPlacement.ended_at.is_(None),
        )
        .all()
    )
    return dict(rows)


def _results_for(db: DBSession, examination_id: uuid.UUID) -> list[dict]:
    rows = (
        db.query(ExaminationResult)
        .filter(ExaminationResult.examination_id == examination_id)
        .order_by(
            ExaminationResult.superseded_at.is_(None).desc(),
            ExaminationResult.recorded_at.desc(),
        )
        .all()
    )
    if not rows:
        return []
    student_ids = {row.student_id for row in rows}
    recorder_ids = {row.recorded_by_id for row in rows}
    students = {
        row.id: row
        for row in db.query(Student).filter(Student.id.in_(student_ids)).all()
    }
    users = {
        row.id: row.full_name
        for row in db.query(User)
        .filter(
            User.id.in_(
                recorder_ids
                | {student.user_id for student in students.values()}
            )
        )
        .all()
    }
    return [
        {
            "id": row.id,
            "examination_id": row.examination_id,
            "student_id": row.student_id,
            "student_number": (
                students[row.student_id].student_id
                if row.student_id in students
                else None
            ),
            "student_name": (
                users.get(students[row.student_id].user_id)
                if row.student_id in students
                else None
            ),
            "score": float(row.score),
            "letter_grade": row.letter_grade,
            "note": row.note,
            "recorded_by_id": row.recorded_by_id,
            "recorded_by_name": users.get(row.recorded_by_id),
            "recorded_at": row.recorded_at,
            "supersedes_id": row.supersedes_id,
            "superseded_at": row.superseded_at,
            "correction_reason": row.correction_reason,
            "is_current": row.superseded_at is None,
        }
        for row in rows
    ]


# ── Validation ──


def _validate_sections(
    db: DBSession,
    *,
    section_ids: list[uuid.UUID],
    course_id: uuid.UUID,
    academic_period_id: uuid.UUID,
    program_offering_id: uuid.UUID | None = None,
) -> list[ClassSection]:
    """Sections must exist, share the exam's subject and intake, and serve its offering.

    When the examination is scoped to a programme offering, a section that does
    not serve that offering would bring another cohort's students into the
    paper. The link that decides this already exists —
    ``class_section_program_offerings`` — so it is read rather than guessed from
    a name or code.
    """
    unique_ids = list(dict.fromkeys(section_ids))
    sections = (
        db.query(ClassSection).filter(ClassSection.id.in_(unique_ids)).all()
    )
    if len(sections) != len(unique_ids):
        raise ExaminationError(
            "EXAM_SECTION_NOT_FOUND",
            "One or more teaching sections do not exist.",
            status_code=422,
        )
    for section in sections:
        if section.course_id != course_id:
            raise ExaminationError(
                "EXAM_SECTION_WRONG_SUBJECT",
                "Every participating section must teach the examination's "
                "subject. A shared examination covers one subject.",
                status_code=422,
            )
        if section.academic_period_id != academic_period_id:
            raise ExaminationError(
                "EXAM_SECTION_WRONG_INTAKE",
                "Every participating section must belong to the examination's "
                "intake.",
                status_code=422,
            )

    if program_offering_id is not None:
        served = {
            row[0]
            for row in db.query(ClassSectionProgramOffering.class_section_id)
            .filter(
                ClassSectionProgramOffering.class_section_id.in_(unique_ids),
                ClassSectionProgramOffering.program_offering_id
                == program_offering_id,
            )
            .all()
        }
        outside = [
            section for section in sections if section.id not in served
        ]
        if outside:
            codes = ", ".join(
                sorted(
                    (section.section_code or str(section.id)[:8])
                    for section in outside
                )
            )
            raise ExaminationError(
                "EXAM_SECTION_OFFERING_MISMATCH",
                "Every participating section must serve the examination's "
                f"programme offering. These sections do not: {codes}.",
                status_code=422,
            )
    return sections


def _validate_window(start_time: time, end_time: time) -> None:
    if end_time <= start_time:
        raise ExaminationError(
            "EXAM_INVALID_TIME_WINDOW",
            "The end time must be after the start time.",
            status_code=422,
        )


def _detect_conflicts(
    db: DBSession,
    *,
    exam_date: date,
    start_time: time,
    end_time: time,
    location: str | None,
    section_ids: list[uuid.UUID],
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Refuse a schedule that provably clashes with another examination.

    Two checks are reliable with this model, so two are enforced:

    * the same room, on the same date, with overlapping times;
    * the same student (through a shared enrolled section), on the same date,
      with overlapping times.

    Nothing else is guessed. Timetable slots are not room bookings, so they are
    not consulted.
    """
    base = db.query(Examination).filter(
        Examination.exam_date == exam_date,
        Examination.status != ExaminationStatus.CANCELLED.value,
        Examination.start_time < end_time,
        Examination.end_time > start_time,
    )
    if exclude_id is not None:
        base = base.filter(Examination.id != exclude_id)

    if location:
        clash = base.filter(
            func.lower(func.btrim(Examination.location)) == location.strip().lower()
        ).first()
        if clash is not None:
            raise ExaminationError(
                "EXAM_LOCATION_CONFLICT",
                f"The location is already used by '{clash.title}' at an "
                "overlapping time on that date.",
            )

    if not section_ids:
        return
    students = db.query(Enrollment.student_id).filter(
        Enrollment.class_section_id.in_(section_ids),
        Enrollment.status.in_(ELIGIBLE_ENROLLMENT_STATUSES),
    )
    clash = (
        base.join(
            ExaminationSection,
            ExaminationSection.examination_id == Examination.id,
        )
        .join(
            Enrollment,
            Enrollment.class_section_id == ExaminationSection.class_section_id,
        )
        .filter(
            Enrollment.status.in_(ELIGIBLE_ENROLLMENT_STATUSES),
            Enrollment.student_id.in_(students),
        )
        .first()
    )
    if clash is not None:
        raise ExaminationError(
            "EXAM_STUDENT_CONFLICT",
            f"'{clash.title}' is scheduled at an overlapping time and shares "
            "students with this examination.",
        )


# ── Writes ──


def create_examination(
    db: DBSession,
    data: ExaminationCreate,
    actor: User,
    *,
    request: object | None = None,
) -> dict:
    """Schedule one examination for one or more teaching sections."""
    ensure_staff(actor)
    _validate_window(data.start_time, data.end_time)

    course = db.get(Course, data.course_id)
    if course is None:
        raise ExaminationError(
            "EXAM_COURSE_NOT_FOUND", "Course not found.", status_code=404
        )
    period = db.get(AcademicPeriod, data.academic_period_id)
    if period is None:
        raise ExaminationError(
            "EXAM_PERIOD_NOT_FOUND", "Academic period not found.", status_code=404
        )
    if data.program_offering_id is not None:
        offering = db.get(ProgramOffering, data.program_offering_id)
        if offering is None:
            raise ExaminationError(
                "EXAM_OFFERING_NOT_FOUND",
                "Programme offering not found.",
                status_code=404,
            )
        if offering.academic_period_id != data.academic_period_id:
            raise ExaminationError(
                "EXAM_OFFERING_WRONG_INTAKE",
                "The programme offering belongs to a different intake.",
                status_code=422,
            )

    sections = _validate_sections(
        db,
        section_ids=data.section_ids,
        course_id=data.course_id,
        academic_period_id=data.academic_period_id,
        program_offering_id=data.program_offering_id,
    )

    _detect_conflicts(
        db,
        exam_date=data.exam_date,
        start_time=data.start_time,
        end_time=data.end_time,
        location=data.location,
        section_ids=[section.id for section in sections],
    )

    examination = Examination(
        title=data.title.strip(),
        examination_type=data.examination_type.value,
        course_id=data.course_id,
        academic_period_id=data.academic_period_id,
        program_offering_id=data.program_offering_id,
        exam_date=data.exam_date,
        start_time=data.start_time,
        end_time=data.end_time,
        location=(data.location or "").strip() or None,
        instructions=data.instructions,
        max_score=(
            Decimal(str(data.max_score)).quantize(Decimal("0.01"))
            if data.max_score is not None
            else None
        ),
        status=ExaminationStatus.SCHEDULED.value,
        created_by_id=actor.id,
    )
    db.add(examination)
    db.flush()
    for section in sections:
        db.add(
            ExaminationSection(
                examination_id=examination.id, class_section_id=section.id
            )
        )
    db.flush()

    try:
        record_audit(
            db,
            action="examination.created",
            actor=actor,
            entity_type="examination",
            entity_id=examination.id,
            context={
                "course_id": data.course_id,
                "academic_period_id": data.academic_period_id,
                "exam_date": data.exam_date,
                "start_time": data.start_time,
                "end_time": data.end_time,
                "location": examination.location,
                "section_ids": sorted(str(section.id) for section in sections),
            },
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(examination)

    return _exam_payload(
        db,
        examination,
        eligible=_eligible_map(db, [examination.id]).get(examination.id, set()),
    )


def update_examination(
    db: DBSession,
    examination_id: uuid.UUID,
    data: ExaminationUpdate,
    actor: User,
    *,
    request: object | None = None,
) -> dict:
    """Reschedule or correct a scheduled examination."""
    ensure_staff(actor)
    examination = _load_examination(db, examination_id)

    if examination.status == ExaminationStatus.CANCELLED.value:
        raise ExaminationError(
            "EXAM_CANCELLED",
            "A cancelled examination cannot be changed.",
            status_code=422,
        )

    fields = data.model_dump(exclude_unset=True)
    section_ids = fields.pop("section_ids", None)

    course_id = fields.get("course_id", examination.course_id)
    period_id = fields.get("academic_period_id", examination.academic_period_id)
    start_time = fields.get("start_time", examination.start_time)
    end_time = fields.get("end_time", examination.end_time)
    exam_date = fields.get("exam_date", examination.exam_date)
    offering_id = fields.get("program_offering_id", examination.program_offering_id)

    _validate_window(start_time, end_time)

    if "program_offering_id" in fields and fields["program_offering_id"] is not None:
        offering = db.get(ProgramOffering, fields["program_offering_id"])
        if offering is None or offering.academic_period_id != period_id:
            raise ExaminationError(
                "EXAM_OFFERING_WRONG_INTAKE",
                "The programme offering does not belong to this intake.",
                status_code=422,
            )

    previous_sections = [s.class_section_id for s in examination.sections]

    if section_ids is not None:
        # Once results exist, the participant list is part of the record: a
        # section added afterwards would make an already-recorded cohort look
        # incomplete, and one removed would orphan a student who sat the paper.
        if db.query(ExaminationResult.id).filter(
            ExaminationResult.examination_id == examination.id
        ).first():
            raise ExaminationError(
                "EXAM_SECTIONS_LOCKED",
                "Participating sections cannot change once results have been "
                "recorded.",
                status_code=422,
            )
        sections = _validate_sections(
            db,
            section_ids=section_ids,
            course_id=course_id,
            academic_period_id=period_id,
            program_offering_id=offering_id,
        )
        effective_sections = [section.id for section in sections]
    else:
        # Re-validating keeps the invariant even when the subject, intake or
        # offering moves: the participating sections must still be compatible
        # with every scoping field, not only the ones sent in this request.
        _validate_sections(
            db,
            section_ids=previous_sections,
            course_id=course_id,
            academic_period_id=period_id,
            program_offering_id=offering_id,
        )
        effective_sections = previous_sections

    _detect_conflicts(
        db,
        exam_date=exam_date,
        start_time=start_time,
        end_time=end_time,
        location=fields.get("location", examination.location),
        section_ids=effective_sections,
        exclude_id=examination.id,
    )

    if "title" in fields and fields["title"] is not None:
        fields["title"] = fields["title"].strip()
    if "location" in fields:
        fields["location"] = (fields["location"] or "").strip() or None
    if "max_score" in fields and fields["max_score"] is not None:
        fields["max_score"] = Decimal(str(fields["max_score"])).quantize(
            Decimal("0.01")
        )
    if "examination_type" in fields and fields["examination_type"] is not None:
        fields["examination_type"] = fields["examination_type"].value

    for key, value in fields.items():
        setattr(examination, key, value)

    if section_ids is not None:
        db.query(ExaminationSection).filter(
            ExaminationSection.examination_id == examination.id
        ).delete(synchronize_session=False)
        for section_id in effective_sections:
            db.add(
                ExaminationSection(
                    examination_id=examination.id, class_section_id=section_id
                )
            )

    try:
        record_audit(
            db,
            action="examination.updated",
            actor=actor,
            entity_type="examination",
            entity_id=examination.id,
            context={"fields": sorted(fields)},
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(examination)

    return _exam_payload(
        db,
        examination,
        eligible=_eligible_map(db, [examination.id]).get(examination.id, set()),
    )


def cancel_examination(
    db: DBSession,
    examination_id: uuid.UUID,
    data: ExaminationCancel,
    actor: User,
    *,
    request: object | None = None,
) -> dict:
    """Cancel an examination, keeping its schedule and any results."""
    ensure_staff(actor)
    examination = _load_examination(db, examination_id)
    if examination.status == ExaminationStatus.CANCELLED.value:
        raise ExaminationError(
            "EXAM_ALREADY_CANCELLED", "This examination is already cancelled."
        )

    reason = data.reason.strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise ExaminationError(
            "EXAM_CANCELLATION_REASON_REQUIRED",
            f"A cancellation needs a reason of at least {MIN_REASON_LENGTH} "
            "characters.",
            status_code=422,
        )

    examination.status = ExaminationStatus.CANCELLED.value
    examination.cancelled_at = _now()
    examination.cancelled_by_id = actor.id
    examination.cancellation_reason = reason

    try:
        record_audit(
            db,
            action="examination.cancelled",
            actor=actor,
            entity_type="examination",
            entity_id=examination.id,
            context={"reason": reason, "exam_date": examination.exam_date},
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(examination)

    return _exam_payload(
        db,
        examination,
        eligible=_eligible_map(db, [examination.id]).get(examination.id, set()),
    )


def _score_value(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def record_result(
    db: DBSession,
    examination_id: uuid.UUID,
    data: ResultCreate,
    actor: User,
    *,
    request: object | None = None,
) -> dict:
    """Record one student's result, validating eligibility first."""
    examination = _load_examination(db, examination_id)
    if not can_manage_results(db, actor, examination):
        raise ExaminationError(
            "EXAM_FORBIDDEN",
            "You may only record results for examinations of sections you "
            "teach.",
            status_code=403,
        )
    if examination.status == ExaminationStatus.CANCELLED.value:
        raise ExaminationError(
            "EXAM_CANCELLED",
            "A cancelled examination cannot take results.",
            status_code=422,
        )

    student = db.query(Student).filter(Student.id == data.student_id).first()
    if student is None:
        raise ExaminationError(
            "STUDENT_NOT_FOUND", "Student not found.", status_code=404
        )

    section_ids = {section.class_section_id for section in examination.sections}
    enrolled = (
        db.query(Enrollment.id)
        .join(Student, Student.id == Enrollment.student_id)
        .filter(
            Enrollment.student_id == student.id,
            Enrollment.class_section_id.in_(section_ids),
            Enrollment.status.in_(ELIGIBLE_ENROLLMENT_STATUSES),
            _student_may_sit(),
        )
        .first()
    )
    if enrolled is None:
        raise ExaminationError(
            "EXAM_STUDENT_NOT_ELIGIBLE",
            "That student is not enrolled in a section sitting this "
            "examination.",
            status_code=422,
        )

    score = _score_value(data.score)
    if examination.max_score is not None and score > examination.max_score:
        raise ExaminationError(
            "EXAM_SCORE_ABOVE_MAXIMUM",
            f"The score exceeds the examination's stated maximum of "
            f"{float(examination.max_score):g}.",
            status_code=422,
        )

    existing = (
        db.query(ExaminationResult.id)
        .filter(
            ExaminationResult.examination_id == examination.id,
            ExaminationResult.student_id == student.id,
            ExaminationResult.superseded_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        raise ExaminationError(
            "EXAM_RESULT_ALREADY_RECORDED",
            "A result is already recorded for this student. Correct the "
            "existing result instead.",
        )

    result = ExaminationResult(
        examination_id=examination.id,
        student_id=student.id,
        score=score,
        letter_grade=(data.letter_grade or "").strip() or None,
        note=data.note,
        recorded_by_id=actor.id,
    )
    db.add(result)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ExaminationError(
            "EXAM_RESULT_ALREADY_RECORDED",
            "A result is already recorded for this student.",
        ) from None

    try:
        record_audit(
            db,
            action="examination.result.recorded",
            actor=actor,
            entity_type="examination_result",
            entity_id=result.id,
            context={
                "examination_id": examination.id,
                "student_id": student.id,
                "score": float(score),
            },
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(result)

    current = _results_for(db, examination.id)
    return {
        "result": next(row for row in current if row["id"] == result.id),
        "result_count": len([row for row in current if row["is_current"]]),
    }


def correct_result(
    db: DBSession,
    examination_id: uuid.UUID,
    result_id: uuid.UUID,
    data: ResultCorrect,
    actor: User,
    *,
    request: object | None = None,
) -> dict:
    """Supersede a result, keeping the previous score readable."""
    examination = _load_examination(db, examination_id)
    if not can_manage_results(db, actor, examination):
        raise ExaminationError(
            "EXAM_FORBIDDEN",
            "You may only correct results for examinations of sections you "
            "teach.",
            status_code=403,
        )

    original = (
        db.query(ExaminationResult)
        .filter(
            ExaminationResult.id == result_id,
            ExaminationResult.examination_id == examination.id,
            ExaminationResult.superseded_at.is_(None),
        )
        .with_for_update()
        .first()
    )
    if original is None:
        raise ExaminationError(
            "EXAM_RESULT_NOT_FOUND",
            "That result does not exist or has already been replaced.",
            status_code=404,
        )

    reason = data.reason.strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise ExaminationError(
            "EXAM_CORRECTION_REASON_REQUIRED",
            f"A correction needs a reason of at least {MIN_REASON_LENGTH} "
            "characters.",
            status_code=422,
        )

    score = _score_value(data.score)
    if examination.max_score is not None and score > examination.max_score:
        raise ExaminationError(
            "EXAM_SCORE_ABOVE_MAXIMUM",
            f"The score exceeds the examination's stated maximum of "
            f"{float(examination.max_score):g}.",
            status_code=422,
        )

    letter_grade = (data.letter_grade or "").strip() or None
    if (score, letter_grade, data.note) == (
        original.score,
        original.letter_grade,
        original.note,
    ):
        raise ExaminationError(
            "EXAM_RESULT_UNCHANGED",
            "The corrected result is identical to the current one.",
            status_code=422,
        )

    previous = {
        "previous_score": float(original.score),
        "previous_letter_grade": original.letter_grade,
        "previous_note": original.note,
    }

    original.superseded_at = _now()
    replacement = ExaminationResult(
        examination_id=examination.id,
        student_id=original.student_id,
        score=score,
        letter_grade=letter_grade,
        note=data.note,
        recorded_by_id=actor.id,
        supersedes_id=original.id,
        correction_reason=reason,
    )
    db.add(replacement)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ExaminationError(
            "EXAM_RESULT_ALREADY_RECORDED",
            "A result is already recorded for this student.",
        ) from None

    try:
        record_audit(
            db,
            action="examination.result.corrected",
            actor=actor,
            entity_type="examination_result",
            entity_id=replacement.id,
            context={
                **previous,
                "examination_id": examination.id,
                "student_id": original.student_id,
                "score": float(score),
                "reason": reason,
            },
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(replacement)

    current = _results_for(db, examination.id)
    return {
        "result": next(row for row in current if row["id"] == replacement.id),
        "result_count": len([row for row in current if row["is_current"]]),
    }


def publish_results(
    db: DBSession,
    examination_id: uuid.UUID,
    actor: User,
    *,
    request: object | None = None,
) -> dict:
    """Publish an examination's results to its students."""
    ensure_staff(actor)
    examination = _load_examination(db, examination_id)

    if examination.status == ExaminationStatus.CANCELLED.value:
        raise ExaminationError(
            "EXAM_CANCELLED",
            "A cancelled examination has no results to publish.",
            status_code=422,
        )
    if examination.published_at is not None:
        raise ExaminationError(
            "EXAM_ALREADY_PUBLISHED",
            "These results are already published.",
        )

    count = _result_count_map(db, [examination.id]).get(examination.id, 0)
    examination.published_at = _now()
    examination.published_by_id = actor.id

    try:
        record_audit(
            db,
            action="examination.results.published",
            actor=actor,
            entity_type="examination",
            entity_id=examination.id,
            context={"result_count": count},
            request=request,
        )
    except Exception:
        db.rollback()
        raise
    db.commit()
    db.refresh(examination)

    return {
        "examination": _exam_payload(db, examination, result_count=count),
        "published_count": count,
    }


# ── Student views ──


def _student_exam_payload(
    examination: Examination,
    *,
    labels: list[str],
    section_result: ExaminationResult | None,
) -> dict:
    published = examination.published_at is not None
    today = _today()
    now = _current_time()
    is_past = examination.exam_date < today or (
        examination.exam_date == today and examination.end_time < now
    )

    result = None
    if published and section_result is not None:
        result = {
            "score": float(section_result.score),
            "letter_grade": section_result.letter_grade,
            "note": section_result.note,
            "published_at": examination.published_at,
        }

    return {
        "id": examination.id,
        "title": examination.title,
        "examination_type": examination.examination_type,
        "course_code": None,
        "course_name": None,
        "exam_date": examination.exam_date,
        "start_time": examination.start_time,
        "end_time": examination.end_time,
        "location": examination.location,
        "instructions": examination.instructions,
        "status": examination.status,
        "section_labels": labels,
        "is_past": is_past,
        "results_published": published,
        # Deliberately absent — not merely null-shaped — while unpublished.
        "result": result,
    }


def student_examinations(db: DBSession, user: User) -> dict:
    """The signed-in student's examinations and published results."""
    student = student_record(db, user)
    section_ids = _assessable_section_ids(db, student.id)
    # A published result stays in the student's record after they leave the
    # section: the paper was sat, and hiding it would rewrite history. The
    # examination joins either through a live enrollment or through the
    # student's own result row.
    own_results = (
        select(ExaminationResult.examination_id)
        .where(
            ExaminationResult.examination_id == Examination.id,
            ExaminationResult.student_id == student.id,
            ExaminationResult.superseded_at.is_(None),
        )
        .exists()
    )

    examinations = (
        db.query(Examination)
        .outerjoin(
            ExaminationSection,
            ExaminationSection.examination_id == Examination.id,
        )
        .filter(
            or_(
                ExaminationSection.class_section_id.in_(section_ids),
                own_results,
            )
        )
        .distinct()
        .order_by(Examination.exam_date.desc(), Examination.start_time.desc())
        .all()
    )
    if not examinations:
        return {"items": [], "total": 0, "upcoming_count": 0, "past_count": 0}

    exam_ids = [examination.id for examination in examinations]
    info = _section_rows(
        db,
        [
            section.class_section_id
            for examination in examinations
            for section in examination.sections
            if section.class_section_id in section_ids
        ],
    )
    # Columns, not ``Course`` entities: the model's ``classes`` collection is
    # ``selectin``, so one entity load per course would pull every section (and
    # every section's enrollments, timetable and assessments) with it.
    courses = {
        row[0]: (row[1], row[2])
        for row in db.query(Course.id, Course.code, Course.name)
        .filter(Course.id.in_({e.course_id for e in examinations}))
        .all()
    }

    results = {
        row.examination_id: row
        for row in db.query(ExaminationResult)
        .filter(
            ExaminationResult.examination_id.in_(exam_ids),
            ExaminationResult.student_id == student.id,
            ExaminationResult.superseded_at.is_(None),
        )
        .all()
    }

    today = _today()
    now = _current_time()
    items = []
    upcoming = past = 0
    for examination in examinations:
        labels = [
            _section_label(info.get(section.class_section_id, {}))
            for section in examination.sections
            if section.class_section_id in section_ids
        ]
        payload = _student_exam_payload(
            examination,
            labels=labels,
            section_result=results.get(examination.id),
        )
        course_code, course_name = courses.get(examination.course_id, (None, None))
        payload["course_code"] = course_code
        payload["course_name"] = course_name
        is_past = examination.exam_date < today or (
            examination.exam_date == today and examination.end_time < now
        )
        if is_past:
            past += 1
        else:
            upcoming += 1
        items.append(payload)

    return {
        "items": items,
        "total": len(items),
        "upcoming_count": upcoming,
        "past_count": past,
    }


# ── Dashboards ──


def examination_dashboard(db: DBSession, user: User) -> dict:
    """Role-scoped summary built from real rows only.

    Every figure is a SQL count over the caller's visible set. There are no
    sample numbers, no extrapolation and no chart series invented for display.
    """
    roles = _role_names(user)
    today = _today()

    if "STUDENT" in roles and not (roles & EXAM_STAFF_ROLES) and "TEACHER" not in roles:
        listing = student_examinations(db, user)
        published = [item for item in listing["items"] if item["results_published"]]
        return {
            "counts": {
                "total": listing["total"],
                "upcoming": listing["upcoming_count"],
                "completed": listing["past_count"],
                "cancelled": len(
                    [
                        item
                        for item in listing["items"]
                        if item["status"] == ExaminationStatus.CANCELLED.value
                    ]
                ),
                "published": len(published),
                "unpublished_results": 0,
                "eligible_students": 0,
                "results_recorded": len(
                    [item for item in listing["items"] if item["result"]]
                ),
            },
            "upcoming": [],
            "recent": [],
            "results": [item for item in listing["items"] if item["result"]],
        }

    query = _visible_query(db, user).distinct()
    total = query.count()
    cancelled = query.filter(
        Examination.status == ExaminationStatus.CANCELLED.value
    ).count()
    published = query.filter(Examination.published_at.is_not(None)).count()
    unpublished = query.filter(
        Examination.published_at.is_(None),
        Examination.status != ExaminationStatus.CANCELLED.value,
        Examination.exam_date <= today,
    ).count()
    upcoming_q = query.filter(
        Examination.exam_date >= today,
        Examination.status != ExaminationStatus.CANCELLED.value,
    )

    upcoming_rows = (
        upcoming_q.order_by(Examination.exam_date.asc(), Examination.start_time.asc())
        .limit(DASHBOARD_LIMIT)
        .all()
    )
    recent_rows = (
        query.order_by(Examination.exam_date.desc(), Examination.start_time.desc())
        .limit(DASHBOARD_LIMIT)
        .all()
    )

    ids = [row.id for row in {e.id: e for e in upcoming_rows + recent_rows}.values()]
    eligible = _eligible_map(db, ids)
    result_counts = _result_count_map(db, ids)
    publishers = _publisher_names(db, upcoming_rows + recent_rows)
    reference = _payload_reference(db, upcoming_rows + recent_rows)

    def payload(examination: Examination) -> dict:
        return _exam_payload(
            db,
            examination,
            eligible=eligible.get(examination.id, set()),
            result_count=result_counts.get(examination.id, 0),
            publisher_name=publishers.get(examination.published_by_id),
            reference=reference,
        )

    return {
        "counts": {
            "total": total,
            "upcoming": upcoming_q.count(),
            "completed": max(total - cancelled - upcoming_q.count(), 0),
            "cancelled": cancelled,
            "published": published,
            "unpublished_results": unpublished,
            "eligible_students": len(
                {student for students in eligible.values() for student in students}
            ),
            "results_recorded": sum(result_counts.values()),
        },
        "upcoming": [payload(row) for row in upcoming_rows],
        "recent": [payload(row) for row in recent_rows],
        "results": [],
    }
