"""Operational reporting service.

Every number is derived from authoritative tables with aggregate queries at
request time. Nothing is cached into a separate reporting store, so reports
cannot drift from the records they describe.
"""

from datetime import date, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session as DBSession

from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    ClassSection,
    Course,
    Enrollment,
    EnrollmentStatus,
    Major,
    Program,
    TeacherAssignment,
)
from app.models.admission import AcademicAdmission
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Student, StudentStatus
from app.models.immigration import (
    ImmigrationChangeRequest,
    ImmigrationChangeRequestStatus,
    ImmigrationProfile,
)
from app.models.platform import (
    Announcement,
    AnnouncementStatus,
    Document,
    DocumentStatus,
    SupportTicket,
    SupportTicketStatus,
)
from app.schemas.reports import (
    AcademicReport,
    CountItem,
    HousingReport,
    ImmigrationReport,
    OperationsReport,
    StudentReport,
)
from app.services.housing import calculate_room_occupancy
from app.services.immigration import get_immigration_cohort_rollup
from app.services.student_academic import latest_effective_admission_subquery


def _rows_to_counts(rows, *, sublabel: bool = False) -> list[CountItem]:
    """Convert `(label, sublabel, count)` or `(label, count)` rows."""
    items: list[CountItem] = []
    for row in rows:
        if sublabel:
            label, sub, count = row
            items.append(CountItem(label=label or "—", sublabel=sub, count=count))
        else:
            label, count = row
            items.append(CountItem(label=label or "—", count=count))
    return items


# --- Students --------------------------------------------------------------


def student_report(db: DBSession) -> StudentReport:
    rows = (
        db.query(Student.status, func.count(Student.id))
        .group_by(Student.status)
        .all()
    )
    by_status = dict(rows)

    def status_count(*statuses: StudentStatus) -> int:
        return sum(by_status.get(s.value, 0) for s in statuses)

    by_nationality = _rows_to_counts(
        db.query(Student.nationality, func.count(Student.id))
        .group_by(Student.nationality)
        .order_by(func.count(Student.id).desc())
        .limit(15)
        .all()
    )

    effective = latest_effective_admission_subquery(db)

    by_major = _rows_to_counts(
        db.query(Major.name, func.count(Student.id))
        .join(effective, effective.c.student_id == Student.id)
        .join(Program, Program.id == effective.c.program_id)
        .join(Major, Major.id == Program.major_id)
        .group_by(Major.name)
        .order_by(func.count(Student.id).desc())
        .all()
    )

    by_program = _rows_to_counts(
        db.query(Program.name, func.count(Student.id))
        .join(effective, effective.c.student_id == Student.id)
        .join(Program, Program.id == effective.c.program_id)
        .group_by(Program.name)
        .order_by(func.count(Student.id).desc())
        .all()
    )

    return StudentReport(
        total=sum(by_status.values()),
        active=status_count(StudentStatus.ACTIVE),
        inactive=status_count(StudentStatus.INACTIVE),
        graduated=status_count(StudentStatus.GRADUATED),
        withdrawn=status_count(StudentStatus.WITHDRAWN),
        suspended=status_count(StudentStatus.SUSPENDED),
        by_nationality=by_nationality,
        by_major=by_major,
        by_program=by_program,
    )


# --- Immigration -----------------------------------------------------------


def immigration_report(db: DBSession, *, today: date | None = None) -> ImmigrationReport:
    today = today or date.today()
    in_30 = today + timedelta(days=30)
    in_90 = today + timedelta(days=90)

    source, cohorts, untrusted, total_students = get_immigration_cohort_rollup(db)

    profile_query = (
        db.query(ImmigrationProfile)
        .join(Student, Student.id == ImmigrationProfile.student_id)
        .filter(Student.status == StudentStatus.ACTIVE)
    )
    if source == "POINTER":
        # A residence-permit/expiry roll-up is an immigration cohort operation:
        # use the original admission, never placement, and exclude untrusted
        # students from named-cohort figures.
        profile_query = profile_query.join(
            AcademicAdmission,
            Student.original_admission_id == AcademicAdmission.id,
        ).filter(AcademicAdmission.verification_status == "VERIFIED")
    profiles = profile_query.all()
    profile_count = len(profiles)

    missing = 0
    expired = 0
    expiring_30 = 0
    expiring_90 = 0
    valid = 0

    for profile in profiles:
        dates = [
            d
            for d in (
                profile.passport_expiry_date,
                profile.visa_expiry_date,
                profile.residence_permit_expiry_date,
            )
            if d is not None
        ]
        if not dates:
            missing += 1
            continue

        if any(d < today for d in dates):
            expired += 1
        elif any(d <= in_30 for d in dates):
            expiring_30 += 1
        elif any(d <= in_90 for d in dates):
            expiring_90 += 1
        else:
            valid += 1

    pending = (
        db.query(func.count(ImmigrationChangeRequest.id))
        .filter(
            ImmigrationChangeRequest.status == ImmigrationChangeRequestStatus.PENDING
        )
        .scalar()
        or 0
    )

    scoped_profile_ids = [profile.id for profile in profiles]

    def expiring_label(field) -> int:  # noqa: ANN001 - column expression
        query = db.query(func.count(ImmigrationProfile.id)).filter(
            field.is_not(None), field <= in_90
        )
        if source == "POINTER":
            query = query.filter(ImmigrationProfile.id.in_(scoped_profile_ids))
        return query.scalar() or 0

    by_document_type = [
        CountItem(
            label="passport",
            sublabel="expiring_90",
            count=expiring_label(ImmigrationProfile.passport_expiry_date),
        ),
        CountItem(
            label="visa",
            sublabel="expiring_90",
            count=expiring_label(ImmigrationProfile.visa_expiry_date),
        ),
        CountItem(
            label="residence_permit",
            sublabel="expiring_90",
            count=expiring_label(ImmigrationProfile.residence_permit_expiry_date),
        ),
    ]

    return ImmigrationReport(
        total_students=total_students,
        with_profile=profile_count,
        missing_information=missing,
        valid=valid,
        expiring_30_days=expiring_30,
        expiring_90_days=expiring_90,
        expired=expired,
        pending_change_requests=pending,
        by_document_type=by_document_type,
        in_named_cohorts=sum(cohort.count for cohort in cohorts),
        untrusted_students=untrusted.total,
        untrusted_by_reason=[
            CountItem(label="UNVERIFIED", count=untrusted.unverified),
            CountItem(label="REVOKED", count=untrusted.revoked),
            CountItem(label="DISPUTED", count=untrusted.disputed),
            CountItem(label="NO_ADMISSION", count=untrusted.no_admission),
        ]
        if source == "POINTER"
        else [],
        by_original_intake=[
            CountItem(label=cohort.intake_name, count=cohort.count)
            for cohort in cohorts
        ],
    )


# --- Housing ---------------------------------------------------------------


def housing_report(db: DBSession) -> HousingReport:
    """Housing totals.

    Occupancy is taken from the housing service's canonical
    `calculate_room_occupancy` so the report and the housing UI can never
    disagree about what "full" means.
    """
    # Reports and the Housing module must agree on what inventory exists. A
    # deactivated building, floor, room or bed is historical inventory: it is
    # still visible in its own history views, but it cannot contribute to
    # capacity, occupancy or availability anywhere.
    active_buildings = (
        db.query(Building).filter(Building.is_active.is_(True)).all()
    )
    active_rooms = (
        db.query(Room)
        .join(Floor, Floor.id == Room.floor_id)
        .join(Building, Building.id == Floor.building_id)
        .filter(
            Building.is_active.is_(True),
            Floor.is_active.is_(True),
            Room.is_active.is_(True),
        )
        .all()
    )
    total_buildings = len(active_buildings)
    total_rooms = len(active_rooms)
    total_beds = sum(
        sum(1 for bed in room.beds if bed.is_active) for room in active_rooms
    )

    active_assignments = (
        db.query(HousingAssignment)
        .join(Bed, Bed.id == HousingAssignment.bed_id)
        .join(Room, Room.id == Bed.room_id)
        .join(Floor, Floor.id == Room.floor_id)
        .join(Building, Building.id == Floor.building_id)
        .filter(
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
            Bed.is_active.is_(True),
            Room.is_active.is_(True),
            Floor.is_active.is_(True),
            Building.is_active.is_(True),
        )
        .all()
    )
    occupied_beds = len({a.bed_id for a in active_assignments})

    rooms_full = 0
    rooms_partial = 0
    rooms_available = 0
    rooms_out_of_service = 0
    out_of_service_beds = 0

    for room in active_rooms:
        occ = calculate_room_occupancy(room)
        status = occ["occupancy_status"]
        if status == "OUT_OF_SERVICE":
            rooms_out_of_service += 1
            out_of_service_beds += occ["total_beds"]
        elif status == "FULL":
            rooms_full += 1
        elif status == "PARTIAL":
            rooms_partial += 1
        else:
            rooms_available += 1

    usable_beds = total_beds - out_of_service_beds
    occupancy_rate = round(occupied_beds / usable_beds * 100, 1) if usable_beds else 0.0

    students_housed = len({a.student_id for a in active_assignments})
    total_active_students = (
        db.query(func.count(Student.id))
        .filter(Student.status == StudentStatus.ACTIVE)
        .scalar()
        or 0
    )

    return HousingReport(
        total_buildings=total_buildings,
        total_rooms=total_rooms,
        total_beds=total_beds,
        occupied_beds=occupied_beds,
        available_beds=max(usable_beds - occupied_beds, 0),
        out_of_service_beds=out_of_service_beds,
        rooms_full=rooms_full,
        rooms_partial=rooms_partial,
        rooms_available=rooms_available,
        rooms_out_of_service=rooms_out_of_service,
        occupancy_rate=occupancy_rate,
        students_housed=students_housed,
        students_not_housed=max(total_active_students - students_housed, 0),
    )


# --- Academics -------------------------------------------------------------


def academic_report(db: DBSession) -> AcademicReport:
    total_majors = db.query(func.count(Major.id)).scalar() or 0
    total_programs = db.query(func.count(Program.id)).scalar() or 0
    total_courses = db.query(func.count(Course.id)).scalar() or 0
    total_classes = db.query(func.count(ClassSection.id)).scalar() or 0

    active_periods = (
        db.query(func.count(AcademicPeriod.id))
        .filter(AcademicPeriod.status == AcademicPeriodStatus.ACTIVE)
        .scalar()
        or 0
    )

    total_enrollments = (
        db.query(func.count(Enrollment.id))
        .filter(Enrollment.status == EnrollmentStatus.ENROLLED)
        .scalar()
        or 0
    )

    total_teacher_assignments = (
        db.query(func.count(TeacherAssignment.id))
        .filter(TeacherAssignment.is_active.is_(True))
        .scalar()
        or 0
    )

    enrollments_by_period = _rows_to_counts(
        db.query(AcademicPeriod.name, func.count(Enrollment.id))
        .join(ClassSection, ClassSection.academic_period_id == AcademicPeriod.id)
        .join(Enrollment, Enrollment.class_section_id == ClassSection.id)
        .filter(Enrollment.status == EnrollmentStatus.ENROLLED)
        .group_by(AcademicPeriod.name)
        .order_by(AcademicPeriod.name)
        .all()
    )

    classes_by_status = _rows_to_counts(
        db.query(ClassSection.status, func.count(ClassSection.id))
        .group_by(ClassSection.status)
        .all()
    )

    return AcademicReport(
        total_majors=total_majors,
        total_programs=total_programs,
        total_courses=total_courses,
        total_classes=total_classes,
        active_periods=active_periods,
        total_enrollments=total_enrollments,
        total_teacher_assignments=total_teacher_assignments,
        enrollments_by_period=enrollments_by_period,
        classes_by_status=classes_by_status,
    )


# --- Combined --------------------------------------------------------------


def operations_report(db: DBSession) -> OperationsReport:
    """Cross-module snapshot used by the dashboard and the reports page."""
    announcements_published = (
        db.query(func.count(Announcement.id))
        .filter(Announcement.status == AnnouncementStatus.PUBLISHED)
        .scalar()
        or 0
    )

    open_support_tickets = (
        db.query(func.count(SupportTicket.id))
        .filter(
            or_(
                SupportTicket.status == SupportTicketStatus.OPEN,
                SupportTicket.status == SupportTicketStatus.IN_PROGRESS,
                SupportTicket.status == SupportTicketStatus.WAITING_FOR_STUDENT,
            )
        )
        .scalar()
        or 0
    )

    documents_stored = (
        db.query(func.count(Document.id))
        .filter(Document.status == DocumentStatus.ACTIVE)
        .scalar()
        or 0
    )

    return OperationsReport(
        students=student_report(db),
        immigration=immigration_report(db),
        housing=housing_report(db),
        academics=academic_report(db),
        announcements_published=announcements_published,
        open_support_tickets=open_support_tickets,
        documents_stored=documents_stored,
    )


__all__ = [
    "academic_report",
    "housing_report",
    "immigration_report",
    "operations_report",
    "student_report",
]
