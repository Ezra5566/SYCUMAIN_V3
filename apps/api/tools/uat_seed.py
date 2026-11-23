"""Additive, repeatable UAT fixtures for the SCU portal.

This is an operator tool, never startup code. It preserves every existing
record, uses only ``uat.`` accounts and ``UAT-`` student numbers, and skips a
scenario that already exists. It requires the operator-supplied local password
in ``UAT_PASSWORD``; the password is never printed or written to disk.

Run from ``apps/api`` inside the development stack:

    UAT_PASSWORD='...' python tools/uat_seed.py

The 2026 Autumn timetable must already be applied with
``python -m app.cli academic-import prepare`` / ``apply``. The canonical UAT
programme mappings are created by this tool when they are absent.

Scenario 7 (authorized earlier-intake placement) is intentionally not seeded:
the source materials provide no dated earlier intake, and inventing one would
fabricate institutional calendar data. That gap is documented in the handover.

Repeat the documented command to fill a missing scenario; existing scenarios are
skipped by student number. To rebuild from scratch, do it only in a disposable
stack (for example the isolated E2E composition): remove that stack's volume,
run the migrations and baseline seed, apply the 2026 Autumn import, then run
this tool again. Never reset the persistent development database just to repeat
UAT data; the additive run is already safe there.
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

# Running ``python tools/uat_seed.py`` puts ``tools/`` on sys.path, not the
# application package root. Add the latter explicitly so the documented
# operator invocation works without a shell-specific PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.auth  # noqa: F401 - initialize the auth package before account service
from app.audit.service import record_audit
from app.database.session import SessionLocal
from app.models.academic import (
    Assessment,
    AssessmentType,
    AttendanceRecord,
    AttendanceStatus,
    ClassSection,
    ClassSectionProgramOffering,
    EntityStatus,
    Grade,
    Major,
    Program,
    ProgramOffering,
)
from app.models.admission import (
    AcademicAdmission,
    AdmissionEvidenceType,
    AdmissionVerificationSlot,
)
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Staff, Student, StudentStatus, User
from app.models.immigration import (
    ImmigrationDocument,
    ImmigrationDocumentType,
    ImmigrationProfile,
)
from app.models.platform import (
    Document,
    DocumentReviewStatus,
    DocumentScanStatus,
    DocumentStatus,
    DocumentVisibility,
)
from app.schemas.academic import EnrollmentCreate, TeacherAssignmentCreate
from app.schemas.admission import (
    AdmissionCreate,
    AdmissionTransition,
    MigratedAdmissionCreate,
    MigratedAdmissionUpdate,
    PlacementCreate,
    VerificationConfirm,
)
from app.services.academic import assign_teacher, enroll_student
from app.services.account import create_account
from app.services.admission import create_admission, transition_admission
from app.services.admission_change import request_self_service_change
from app.services.admission_verification import (
    confirm_slot,
    create_migrated_candidate,
    update_migrated_candidate,
)
from app.services.housing import create_housing_assignment, transfer_student
from app.services.immigration import get_or_create_immigration_profile, update_immigration_profile
from app.services.placement import create_placement
from app.storage import get_storage
from app.storage.base import build_object_key

SOURCE_SEMESTER = "2026-autumn"
PERIOD_CODE = "2026-FALL"
PASSWORD = os.environ.get("UAT_PASSWORD", "")


def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(2)


def _pdf_bytes(title: str) -> bytes:
    """A small synthetic PDF payload; it is never a real student record."""
    return f"%PDF-1.4\n% UAT synthetic document: {title}\n%%EOF\n".encode()


def _ensure_reference_programs(db) -> dict[str, Program]:
    """Canonical UAT mappings for source programmes with no official parent."""
    specs = [
        ("AI", "Artificial Intelligence", "AI-INT", "Artificial Intelligence (International)"),
        ("CE", "Civil Engineering", "CE-INT", "Civil Engineering (International)"),
        (
            "CL",
            "Chinese Language",
            "CLE-INT",
            "Chinese Language (Elementary Level)",
        ),
        (
            "CL",
            "Chinese Language",
            "CLI-INT",
            "Chinese Language (Intermediate Level)",
        ),
    ]
    programs: dict[str, Program] = {}
    for major_code, major_name, program_code, program_name in specs:
        major = db.query(Major).filter(Major.code == major_code).first()
        if major is None:
            major = Major(
                code=major_code,
                name=major_name,
                description="UAT canonical mapping; source has no official programme code.",
                status=EntityStatus.ACTIVE,
            )
            db.add(major)
            db.flush()
        program = db.query(Program).filter(Program.code == program_code).first()
        if program is None:
            program = Program(
                major_id=major.id,
                code=program_code,
                name=program_name,
                description=(
                    "Canonical UAT mapping for the SCU timetable source. "
                    "The code is internal, not an official institutional code."
                ),
                status=EntityStatus.ACTIVE,
            )
            db.add(program)
            db.flush()
        programs[program_code] = program
    for code in ("BCS", "BBA", "BAL"):
        program = db.query(Program).filter(Program.code == code).first()
        if program is not None:
            programs[code] = program
    return programs


def _offerings(db) -> dict[str, ProgramOffering]:
    rows = (
        db.query(ProgramOffering)
        .filter(ProgramOffering.source_id.like("%2026a"))
        .all()
    )
    by_source = {row.source_id: row for row in rows}
    if len(by_source) != 6:
        _fail(
            "2026 Autumn is not applied. Run academic-import prepare/apply first; "
            f"found {len(by_source)} of 6 source offerings."
        )
    return by_source


def _period(db):
    from app.models.academic import AcademicPeriod

    period = db.query(AcademicPeriod).filter(AcademicPeriod.code == PERIOD_CODE).first()
    if period is None or period.start_date is None or period.end_date is None:
        _fail(f"{PERIOD_CODE} must exist with official start/end dates.")
    return period


def _ensure_account(db, email: str, full_name: str, roles: list[str]) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        return user
    user, _ = create_account(
        db,
        email=email,
        full_name=full_name,
        roles=roles,
        password=PASSWORD,
        must_change_password=False,
    )
    db.commit()
    db.refresh(user)
    return user


def _ensure_student(
    db,
    *,
    email: str,
    student_number: str,
    first_name: str,
    last_name: str,
    nationality: str,
    status: StudentStatus = StudentStatus.ACTIVE,
) -> tuple[Student, bool]:
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        user = _ensure_account(db, email, f"{first_name} {last_name}", ["STUDENT"])
    student = db.query(Student).filter(Student.user_id == user.id).first()
    if student is not None:
        return student, False
    student = Student(
        user_id=user.id,
        student_id=student_number,
        first_name=first_name,
        last_name=last_name,
        date_of_birth=datetime(2004, 3, 14),
        nationality=nationality,
        phone="+86 000 0000 0000",
        emergency_contact_name="UAT Emergency Contact",
        emergency_contact_phone="+86 000 0000 0001",
        status=status,
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student, True


def _audit(db, action: str, actor: User, entity_type: str, entity_id, context: dict):
    record_audit(
        db,
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        context=context,
    )


def _episode(db, student: Student, offering: ProgramOffering, actor: User, status: str):
    episode = create_admission(
        db,
        student,
        AdmissionCreate(
            admission_intake_id=offering.academic_period_id,
            program_offering_id=offering.id,
            initial_status=status,
        ),
        actor,
    )
    _audit(
        db,
        "admission.created",
        actor,
        "academic_admission",
        episode.id,
        {
            "student_id": str(student.id),
            "intake_id": str(episode.admission_intake_id),
            "program_offering_id": str(offering.id),
            "initial_status": status,
            "demo": "UAT",
        },
    )
    db.commit()
    db.refresh(episode)
    return episode


def _placement(db, student: Student, episode: AcademicAdmission, actor: User):
    placement, previous = create_placement(
        db,
        student,
        PlacementCreate(
            admission_id=episode.id,
            program_offering_id=episode.admitted_program_offering_id,
        ),
        actor,
        can_authorize_earlier=False,
    )
    _audit(
        db,
        "academic.placement.created",
        actor,
        "academic_placement",
        placement.id,
        {
            "student_id": str(student.id),
            "admission_id": str(episode.id),
            "program_offering_id": str(placement.program_offering_id),
            "previous_placement_id": str(previous.id) if previous else None,
            "demo": "UAT",
        },
    )
    db.commit()
    db.refresh(placement)
    return placement


def _transition(
    db,
    student: Student,
    episode: AcademicAdmission,
    status: str,
    actor: User,
    reason: str,
):
    transitioned = transition_admission(
        db,
        student,
        episode.id,
        AdmissionTransition(status=status, reason=reason),
        actor,
    )
    _audit(
        db,
        "admission.status_changed",
        actor,
        "academic_admission",
        episode.id,
        {
            "student_id": str(student.id),
            "status": status,
            "reason": reason,
            "demo": "UAT",
        },
    )
    db.commit()
    db.refresh(transitioned)
    return transitioned


def _sections_for(db, offering: ProgramOffering):
    return (
        db.query(ClassSection)
        .join(
            ClassSectionProgramOffering,
            ClassSectionProgramOffering.class_section_id == ClassSection.id,
        )
        .filter(ClassSectionProgramOffering.program_offering_id == offering.id)
        .order_by(ClassSection.id)
        .all()
    )


def _enroll(db, student: Student, sections: list[ClassSection]):
    for section in sections:
        try:
            enroll_student(db, section.id, EnrollmentCreate(student_id=student.id))
        except ValueError as exc:
            if "already enrolled" not in str(exc):
                raise


def _academic_evidence(db, student: Student, sections: list[ClassSection], actor: User):
    """Add attendance and a grade to the first two enrolled sections."""
    if not sections:
        return
    section = sections[0]
    assessment = (
        db.query(Assessment)
        .filter(
            Assessment.class_section_id == section.id,
            Assessment.name == "UAT Continuous Assessment",
        )
        .first()
    )
    if assessment is None:
        assessment = Assessment(
            class_section_id=section.id,
            name="UAT Continuous Assessment",
            assessment_type=AssessmentType.ASSIGNMENT,
            max_score=100,
            weight=30,
            due_date=date(2026, 10, 15),
        )
        db.add(assessment)
        db.flush()
    existing_grade = (
        db.query(Grade)
        .filter(
            Grade.assessment_id == assessment.id,
            Grade.student_id == student.id,
        )
        .first()
    )
    if existing_grade is None:
        db.add(
            Grade(
                assessment_id=assessment.id,
                student_id=student.id,
                score=84.0,
                letter_grade="A-",
                recorded_by=actor.id,
                note="UAT synthetic assessment",
            )
        )
    for session_date, status in (
        (date(2026, 9, 21), AttendanceStatus.PRESENT),
        (date(2026, 9, 28), AttendanceStatus.LATE),
        (date(2026, 10, 5), AttendanceStatus.PRESENT),
    ):
        existing = (
            db.query(AttendanceRecord)
            .filter(
                AttendanceRecord.student_id == student.id,
                AttendanceRecord.class_section_id == section.id,
                AttendanceRecord.session_date == session_date,
            )
            .first()
        )
        if existing is None:
            db.add(
                AttendanceRecord(
                    student_id=student.id,
                    class_section_id=section.id,
                    session_date=session_date,
                    status=status,
                    recorded_by=actor.id,
                    note="UAT synthetic attendance",
                )
            )
    db.commit()


def _immigration(db, student: Student, actor: User, data: dict, verified: bool):
    profile = get_or_create_immigration_profile(db, student.id, actor_id=actor.id)
    if verified:
        update_immigration_profile(
            db,
            profile,
            data,
            actor_id=actor.id,
            reason="UAT synthetic verified profile",
            data_source="UAT_FIXTURE",
        )
    else:
        for key, value in data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        profile.data_source = "UAT_FIXTURE"
        profile.verification_status = "UNVERIFIED"
        db.commit()
    return profile


def _save_document(db, student: Student, actor: User, *, title: str, filename: str, doc_type: str):
    payload = _pdf_bytes(title)
    key = build_object_key(
        scope=f"student/{student.id}",
        owner_id=str(actor.id),
        filename=filename,
        unique_prefix=uuid.uuid4().hex,
    )
    stored = get_storage().save(key, payload, "application/pdf")
    document = Document(
        student_id=student.id,
        uploaded_by=actor.id,
        document_type=doc_type,
        title=title,
        description="Synthetic UAT fixture; no real student document.",
        storage_provider=stored.provider,
        object_key=stored.key,
        original_filename=filename,
        content_type="application/pdf",
        file_size=stored.size,
        checksum_sha256=hashlib.sha256(payload).hexdigest(),
        visibility=DocumentVisibility.STUDENT_VISIBLE,
        status=DocumentStatus.ACTIVE,
        review_status=DocumentReviewStatus.APPROVED,
        reviewed_by=actor.id,
        reviewed_at=datetime.now(UTC),
        scan_status=DocumentScanStatus.CLEAN,
        scan_engine="uat-fixture",
        scanned_at=datetime.now(UTC),
        is_required=True,
    )
    db.add(document)
    db.flush()
    _audit(
        db,
        "document.uploaded",
        actor,
        "document",
        document.id,
        {"student_id": str(student.id), "document_type": doc_type, "demo": "UAT"},
    )
    return document, stored


def _immigration_document(db, profile: ImmigrationProfile, stored, actor: User, doc_type):
    row = ImmigrationDocument(
        immigration_profile_id=profile.id,
        uploaded_by=actor.id,
        document_type=doc_type,
        storage_reference=stored.key,
        original_filename="uat-synthetic-immigration.pdf",
        content_type="application/pdf",
        file_size=stored.size,
        notes="UAT synthetic document",
    )
    db.add(row)
    db.flush()
    return row


def _free_beds(db):
    return (
        db.query(Bed)
        .join(Room, Room.id == Bed.room_id)
        .join(Floor, Floor.id == Room.floor_id)
        .join(Building, Building.id == Floor.building_id)
        .filter(
            Bed.is_active.is_(True),
            Room.is_active.is_(True),
            Floor.is_active.is_(True),
            Building.is_active.is_(True),
            Room.status == "AVAILABLE",
            ~Bed.id.in_(
                db.query(HousingAssignment.bed_id).filter(
                    HousingAssignment.status == HousingAssignmentStatus.ACTIVE
                )
            ),
        )
        .order_by(Building.name, Floor.floor_number, Room.room_number, Bed.bed_number)
        .all()
    )


def _seed_housing(db, student: Student, actor: User):
    existing = (
        db.query(HousingAssignment)
        .filter(
            HousingAssignment.student_id == student.user_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
        .first()
    )
    if existing is not None:
        return existing
    beds = _free_beds(db)
    if len(beds) < 2:
        _fail("Two free active beds are required for the UAT housing scenario.")
    first = create_housing_assignment(
        db,
        student_id=student.user_id,
        bed_id=beds[0].id,
        start_date=datetime(2026, 9, 1, tzinfo=UTC),
        notes="UAT synthetic arrival allocation",
        actor_id=actor.id,
    )
    _audit(
        db,
        "housing.assignment_created",
        actor,
        "housing_assignment",
        first.id,
        {"student_id": str(student.id), "demo": "UAT"},
    )
    second = transfer_student(
        db,
        assignment_id=first.id,
        new_bed_id=beds[1].id,
        transfer_date=datetime(2026, 10, 15, tzinfo=UTC),
        notes="UAT synthetic room transfer to demonstrate preserved history",
        actor_id=actor.id,
    )
    _audit(
        db,
        "housing.assignment_transferred",
        actor,
        "housing_assignment",
        second.id,
        {"student_id": str(student.id), "previous_assignment_id": str(first.id), "demo": "UAT"},
    )
    db.commit()
    return second


def _seed_teacher(db, teacher: User, cs_offering: ProgramOffering):
    staff = db.query(Staff).filter(Staff.user_id == teacher.id).first()
    if staff is None:
        _fail("UAT teacher account has no staff profile.")
    sections = _sections_for(db, cs_offering)
    # Assigning every CS group would put one teacher in two rooms at the same
    # time. Group 1 is the group used by the demo student.
    chosen = [
        section
        for section in sections
        if "Group 2" not in (section.source_label or "")
    ]
    for section in chosen:
        existing = (
            db.query(ClassSection)
            .join(ClassSectionProgramOffering)
            .filter(ClassSection.id == section.id)
            .first()
        )
        if existing is None:
            continue
        from app.models.academic import TeacherAssignment

        if (
            db.query(TeacherAssignment)
            .filter(
                TeacherAssignment.class_section_id == section.id,
                TeacherAssignment.staff_id == staff.id,
                TeacherAssignment.is_active.is_(True),
            )
            .first()
            is not None
        ):
            continue
        try:
            assign_teacher(
                db,
                section.id,
                TeacherAssignmentCreate(staff_id=staff.id),
            )
        except Exception as exc:  # noqa: BLE001 - report the exact conflict
            print(f"  teacher assignment skipped for {section.source_label}: {exc}")


def main() -> int:
    if not PASSWORD or len(PASSWORD) < 12:
        _fail("Set UAT_PASSWORD to a local-only password of at least 12 characters.")

    db = SessionLocal()
    created: list[str] = []
    try:
        programs = _ensure_reference_programs(db)
        offerings = _offerings(db)
        period = _period(db)
        cs = offerings["cs-2026a"]
        ai = offerings["ai-2026a"]
        business = offerings["business-2026a"]

        admin = _ensure_account(db, "uat.admin@uat.scu.example", "UAT Administrator", ["ADMIN"])
        management = _ensure_account(
            db, "uat.management@uat.scu.example", "UAT Management Officer", ["MANAGEMENT"]
        )
        teacher = _ensure_account(db, "uat.teacher@uat.scu.example", "UAT Teacher", ["TEACHER"])

        # 1. Newly registered, ADMITTED, no placement yet.
        s1, is_new = _ensure_student(
            db,
            email="uat.student01@uat.scu.example",
            student_number="UAT-2026-001",
            first_name="Amara",
            last_name="Okonkwo",
            nationality="Nigeria",
        )
        if is_new:
            _episode(db, s1, cs, admin, "ADMITTED")
            created.append("01 ADMITTED / no placement")

        # 2, 12, 13, 15. Active student, verified immigration, current housing,
        # enrolments, attendance and a grade.
        s2, is_new = _ensure_student(
            db,
            email="uat.student02@uat.scu.example",
            student_number="UAT-2026-002",
            first_name="Mateo",
            last_name="Alvarez",
            nationality="Mexico",
        )
        if is_new:
            ep2 = _episode(db, s2, cs, admin, "ACTIVE")
            _placement(db, s2, ep2, admin)
            sections = _sections_for(db, cs)
            chosen = [s for s in sections if "Group 2" not in (s.source_label or "")]
            _enroll(db, s2, chosen)
            _academic_evidence(db, s2, chosen, admin)
            profile = _immigration(
                db,
                s2,
                admin,
                {
                    "passport_number": "UAT-P-MX-000002",
                    "passport_issuing_country": "Mexico",
                    "passport_issue_date": date(2023, 4, 1),
                    "passport_expiry_date": date(2033, 3, 31),
                    "passport_name_as_shown": "MATEO ALVAREZ",
                    "visa_type": "X1",
                    "visa_number": "UAT-V-MX-000002",
                    "visa_issue_date": date(2026, 6, 1),
                    "visa_expiry_date": date(2027, 9, 30),
                    "visa_entries": "MULTIPLE",
                    "visa_issuing_authority": "SCU International Office (synthetic)",
                    "residence_permit_number": "UAT-RP-MX-000002",
                    "residence_permit_issue_date": date(2026, 8, 20),
                    "residence_permit_expiry_date": date(2027, 8, 31),
                    "residence_permit_issuing_authority": (
                        "Shenyang Exit-Entry Administration (synthetic)"
                    ),
                },
                verified=True,
            )
            doc, stored = _save_document(
                db,
                s2,
                admin,
                title="UAT synthetic passport data page",
                filename="uat-passport.pdf",
                doc_type="PASSPORT",
            )
            _immigration_document(db, profile, stored, admin, ImmigrationDocumentType.PASSPORT)
            _save_document(
                db,
                s2,
                admin,
                title="UAT synthetic admission letter",
                filename="uat-admission-letter.pdf",
                doc_type="ADMISSION",
            )
            db.commit()
            _seed_housing(db, s2, admin)
            created.append(
                "02 ACTIVE / placement / housing / verified immigration / academic record"
            )

        # 3. One of two independent verification slots confirmed.
        s3, is_new = _ensure_student(
            db,
            email="uat.student03@uat.scu.example",
            student_number="UAT-2026-003",
            first_name="Anaya",
            last_name="Sharma",
            nationality="India",
        )
        if is_new:
            candidate = create_migrated_candidate(
                db,
                s3,
                MigratedAdmissionCreate(
                    admission_intake_id=period.id, program_offering_id=cs.id
                ),
                admin,
            )
            db.commit()
            confirm_slot(
                db,
                s3,
                candidate.id,
                AdmissionVerificationSlot.ADMIN,
                VerificationConfirm(
                    evidence_type=AdmissionEvidenceType.ADMISSION_LETTER,
                    evidence_reference="UAT-EVIDENCE-003",
                    evidence_note="UAT synthetic first confirmation",
                ),
                admin,
            )
            db.commit()
            created.append("03 migration candidate / ADMIN confirmed / MANAGEMENT pending")

        # 4. Both slots confirmed against different candidate snapshots.
        s4, is_new = _ensure_student(
            db,
            email="uat.student04@uat.scu.example",
            student_number="UAT-2026-004",
            first_name="Kwame",
            last_name="Mensah",
            nationality="Ghana",
        )
        if is_new:
            candidate = create_migrated_candidate(
                db,
                s4,
                MigratedAdmissionCreate(
                    admission_intake_id=period.id, program_offering_id=ai.id
                ),
                management,
            )
            db.commit()
            confirm_slot(
                db,
                s4,
                candidate.id,
                AdmissionVerificationSlot.MANAGEMENT,
                VerificationConfirm(
                    evidence_type=AdmissionEvidenceType.REGISTER_EXTRACT,
                    evidence_reference="UAT-EVIDENCE-004-M",
                    evidence_note="UAT synthetic management snapshot: AI",
                ),
                management,
            )
            db.commit()
            update_migrated_candidate(
                db,
                s4,
                candidate.id,
                MigratedAdmissionUpdate(program_offering_id=cs.id),
                admin,
            )
            db.commit()
            confirm_slot(
                db,
                s4,
                candidate.id,
                AdmissionVerificationSlot.ADMIN,
                VerificationConfirm(
                    evidence_type=AdmissionEvidenceType.ENROLMENT_RECORD,
                    evidence_reference="UAT-EVIDENCE-004-A",
                    evidence_note="UAT synthetic admin snapshot: Computer Science",
                ),
                admin,
            )
            db.commit()
            created.append("04 DISPUTED admission / conflicting slot snapshots")

        # 5. Active CS student with a pending same-intake programme change.
        s5, is_new = _ensure_student(
            db,
            email="uat.student05@uat.scu.example",
            student_number="UAT-2026-005",
            first_name="Sofia",
            last_name="Petrova",
            nationality="Bulgaria",
        )
        if is_new:
            ep5 = _episode(db, s5, cs, admin, "ACTIVE")
            _placement(db, s5, ep5, admin)
            change = request_self_service_change(
                db,
                s5,
                to_program_id=programs["AI-INT"].id,
                to_program_offering_id=ai.id,
                actor=s5.user,
                reason=(
                    "UAT synthetic request: move from Computer Science "
                    "to Artificial Intelligence."
                ),
            )
            _audit(
                db,
                "academic.admission.change_requested",
                s5.user,
                "academic_admission_change",
                change.id,
                {"student_id": str(s5.id), "change_type": "PROGRAM_CHANGE", "demo": "UAT"},
            )
            db.commit()
            created.append("05 pending CS to AI programme change")

        # 6. Completed first episode and a new live admission episode.
        s6, is_new = _ensure_student(
            db,
            email="uat.student06@uat.scu.example",
            student_number="UAT-2026-006",
            first_name="Chen",
            last_name="Hao",
            nationality="China",
        )
        if is_new:
            first = _episode(db, s6, business, admin, "ACTIVE")
            _placement(db, s6, first, admin)
            _transition(
                db,
                s6,
                first,
                "COMPLETED",
                admin,
                "UAT synthetic prior programme completed",
            )
            second = _episode(db, s6, ai, admin, "ACTIVE")
            _placement(db, s6, second, admin)
            _enroll(db, s6, _sections_for(db, ai))
            created.append("06 prior COMPLETED episode + new ACTIVE AI episode")

        # 8. Graduated student with preserved academic history.
        s8, is_new = _ensure_student(
            db,
            email="uat.student08@uat.scu.example",
            student_number="UAT-2026-008",
            first_name="Fatima",
            last_name="Zahra",
            nationality="Morocco",
            status=StudentStatus.GRADUATED,
        )
        if is_new:
            ep8 = _episode(db, s8, business, admin, "ACTIVE")
            _placement(db, s8, ep8, admin)
            sections = _sections_for(db, business)
            _enroll(db, s8, sections)
            _academic_evidence(db, s8, sections, admin)
            _transition(db, s8, ep8, "COMPLETED", admin, "UAT synthetic programme completed")
            created.append("08 GRADUATED / preserved historical enrolment and grade")

        # 9. Withdrawn student with a closed placement.
        s9, is_new = _ensure_student(
            db,
            email="uat.student09@uat.scu.example",
            student_number="UAT-2026-009",
            first_name="Lucas",
            last_name="Silva",
            nationality="Brazil",
            status=StudentStatus.WITHDRAWN,
        )
        if is_new:
            ep9 = _episode(db, s9, business, admin, "ACTIVE")
            _placement(db, s9, ep9, admin)
            _transition(db, s9, ep9, "WITHDRAWN", admin, "UAT synthetic withdrawal")
            s9.status = StudentStatus.WITHDRAWN
            db.commit()
            created.append("09 WITHDRAWN / closed placement / preserved history")

        # 10. Residence permit approaching expiry.
        s10, is_new = _ensure_student(
            db,
            email="uat.student10@uat.scu.example",
            student_number="UAT-2026-010",
            first_name="Priya",
            last_name="Nair",
            nationality="India",
        )
        if is_new:
            ep10 = _episode(db, s10, cs, admin, "ACTIVE")
            _placement(db, s10, ep10, admin)
            _immigration(
                db,
                s10,
                admin,
                {
                    "passport_number": "UAT-P-IN-000010",
                    "passport_issuing_country": "India",
                    "passport_expiry_date": date(2032, 5, 1),
                    "passport_name_as_shown": "PRIYA NAIR",
                    "visa_type": "X1",
                    "visa_number": "UAT-V-IN-000010",
                    "visa_expiry_date": date(2027, 6, 30),
                    "residence_permit_number": "UAT-RP-IN-000010",
                    "residence_permit_issue_date": date(2026, 1, 1),
                    "residence_permit_expiry_date": date.today() + timedelta(days=21),
                    "residence_permit_issuing_authority": (
                        "Shenyang Exit-Entry Administration (synthetic)"
                    ),
                },
                verified=True,
            )
            created.append("10 residence permit expiring within 30 days")

        # 11. Incomplete immigration profile.
        s11, is_new = _ensure_student(
            db,
            email="uat.student11@uat.scu.example",
            student_number="UAT-2026-011",
            first_name="Omar",
            last_name="Haddad",
            nationality="Jordan",
        )
        if is_new:
            ep11 = _episode(db, s11, business, admin, "ACTIVE")
            _placement(db, s11, ep11, admin)
            _immigration(
                db,
                s11,
                admin,
                {
                    "passport_number": "UAT-P-JO-000011",
                    "passport_issuing_country": "Jordan",
                    "passport_name_as_shown": "OMAR HADDAD",
                },
                verified=False,
            )
            created.append("11 incomplete UNVERIFIED immigration profile")

        # 12. Verified immigration profile with document history.
        s12, is_new = _ensure_student(
            db,
            email="uat.student12@uat.scu.example",
            student_number="UAT-2026-012",
            first_name="Yuki",
            last_name="Tanaka",
            nationality="Japan",
        )
        if is_new:
            ep12 = _episode(db, s12, ai, admin, "ACTIVE")
            _placement(db, s12, ep12, admin)
            profile = _immigration(
                db,
                s12,
                admin,
                {
                    "passport_number": "UAT-P-JP-000012",
                    "passport_issuing_country": "Japan",
                    "passport_expiry_date": date(2034, 8, 1),
                    "passport_name_as_shown": "YUKI TANAKA",
                    "visa_type": "X1",
                    "visa_number": "UAT-V-JP-000012",
                    "visa_expiry_date": date(2027, 3, 31),
                    "residence_permit_number": "UAT-RP-JP-000012",
                    "residence_permit_expiry_date": date(2027, 2, 28),
                },
                verified=True,
            )
            _, stored = _save_document(
                db,
                s12,
                admin,
                title="UAT synthetic residence permit",
                filename="uat-residence-permit.pdf",
                doc_type="RESIDENCE_PERMIT",
            )
            _immigration_document(
                db, profile, stored, admin, ImmigrationDocumentType.RESIDENCE_PERMIT
            )
            db.commit()
            created.append("12 VERIFIED immigration profile with document history")

        _seed_teacher(db, teacher, cs)

        print("UAT seed complete.")
        for item in created:
            print(f"  added: {item}")
        if not created:
            print("  no new scenario rows (already seeded).")
        print("Accounts:")
        for email in (
            "uat.admin@uat.scu.example",
            "uat.management@uat.scu.example",
            "uat.teacher@uat.scu.example",
            "uat.student02@uat.scu.example",
        ):
            print(f"  {email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
