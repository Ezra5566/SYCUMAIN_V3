"""Phase 0 attendance preconditions.

Four defects had to be closed before any attendance calendar work could start:

* ``has_housing`` joined ``HousingAssignment.student_id`` (a *user* id) against
  ``Student.id`` (a *student* id), so every student read as unhoused.
* Bulk attendance committed once per row, so a rejected row left the rows
  before it behind and the audit trail recorded only a count.
* Management could edit attendance but not read it.
* ``GET /classes/{id}/assessments`` required only ``academic.view``, which every
  student holds, so any academic viewer could enumerate a class's assessments.

These tests pin the corrected behaviour. They deliberately assert on the
persisted rows and audit entries, not only on response codes: a 400 that still
left half a register behind would pass a status-code-only check.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest

from app.auth.service import hash_password
from app.models.academic import (
    AcademicPeriod,
    AttendanceRecord,
    AttendanceStatus,
    ClassSection,
    Course,
    Enrollment,
    EnrollmentStatus,
    TeacherAssignment,
)
from app.models.audit import AuditLog
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Role, Staff, Student, User
from app.permissions.constants import ALL_PERMISSIONS
from app.services.student import list_students

API = "/api/v1"
SESSION_DATE = date(2032, 9, 6)


def _login(client, email: str = "admin@school.portal") -> None:
    response = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _mk_student(db, tag: str) -> Student:
    user = User(
        email=f"{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Phase0 {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"P0-{tag}-{uuid.uuid4().hex[:6]}",
        first_name="Phase0",
        last_name=tag,
        status="ACTIVE",
    )
    db.add(student)
    db.flush()
    return student


def _mk_section(db, tag: str, code: str = "A") -> ClassSection:
    period = AcademicPeriod(
        code=f"P0-{tag}-{code}",
        name=f"Phase 0 intake {tag} {code}",
        start_date=date(2032, 9, 1),
        end_date=date(2032, 12, 20),
        status="PLANNED",
    )
    db.add(period)
    db.flush()
    course = Course(code=f"P0C-{tag}-{code}", name=f"Phase 0 course {tag} {code}")
    db.add(course)
    db.flush()
    section = ClassSection(
        course_id=course.id,
        academic_period_id=period.id,
        section_code=code,
        capacity=30,
        status="ACTIVE",
    )
    db.add(section)
    db.flush()
    return section


def _enroll(db, student: Student, section: ClassSection) -> Enrollment:
    enrollment = Enrollment(
        student_id=student.id,
        class_section_id=section.id,
        status=EnrollmentStatus.ENROLLED,
    )
    db.add(enrollment)
    db.flush()
    return enrollment


def _mk_assignment(
    db,
    student: Student,
    *,
    start: datetime,
    end: datetime | None = None,
    status: HousingAssignmentStatus = HousingAssignmentStatus.ACTIVE,
) -> HousingAssignment:
    """Create a bed and assign one student to it.

    Each call makes its own building so the per-bed and per-student ACTIVE
    uniqueness indexes are never in play, keeping each case independent.
    """
    tag = uuid.uuid4().hex[:8]
    building = Building(name=f"P0-{tag}")
    db.add(building)
    db.flush()
    floor = Floor(building_id=building.id, floor_number=1)
    db.add(floor)
    db.flush()
    room = Room(floor_id=floor.id, room_number=tag[:4], capacity=1)
    db.add(room)
    db.flush()
    bed = Bed(room_id=room.id, bed_number=1)
    db.add(bed)
    db.flush()
    assignment = HousingAssignment(
        student_id=student.user_id,
        bed_id=bed.id,
        start_date=start,
        end_date=end,
        status=status,
    )
    db.add(assignment)
    db.flush()
    return assignment


def _role_permissions(db, role_name: str) -> set[str]:
    role = db.query(Role).filter(Role.name == role_name).first()
    assert role is not None, f"role {role_name} is not seeded"
    return {permission.codename for permission in role.permissions}


# ── A. Housing identity lookup ──────────────────────────────────────────────


class TestHousingIdentityLookup:
    """`HousingAssignment.student_id` is a user id, not a student id."""

    def test_housed_student_is_found_through_the_user_account(self, db_session):
        tag = uuid.uuid4().hex[:7]
        housed = _mk_student(db_session, f"housed-{tag}")
        _mk_assignment(db_session, housed, start=datetime(2020, 1, 15))
        db_session.commit()

        result = list_students(db_session, has_housing=True, search=f"housed-{tag}")

        assert [item.id for item in result.items] == [housed.id]

    def test_unhoused_student_is_excluded(self, db_session):
        tag = uuid.uuid4().hex[:7]
        housed = _mk_student(db_session, f"flat-{tag}")
        unhoused = _mk_student(db_session, f"flat-{tag}")
        _mk_assignment(db_session, housed, start=datetime(2020, 1, 15))
        db_session.commit()

        result = list_students(db_session, has_housing=True, search=f"flat-{tag}")

        found = {item.id for item in result.items}
        assert housed.id in found
        assert unhoused.id not in found

    def test_negation_keeps_students_without_housing(self, db_session):
        tag = uuid.uuid4().hex[:7]
        housed = _mk_student(db_session, f"negate-{tag}")
        unhoused = _mk_student(db_session, f"negate-{tag}")
        _mk_assignment(db_session, housed, start=datetime(2020, 1, 15))
        db_session.commit()

        result = list_students(db_session, has_housing=False, search=f"negate-{tag}")

        found = {item.id for item in result.items}
        assert unhoused.id in found
        assert housed.id not in found

    def test_ended_assignment_is_history_not_housing(self, db_session):
        tag = uuid.uuid4().hex[:7]
        student = _mk_student(db_session, f"ended-{tag}")
        _mk_assignment(
            db_session,
            student,
            start=datetime(2020, 1, 15),
            end=datetime(2020, 6, 30),
            status=HousingAssignmentStatus.ENDED,
        )
        db_session.commit()

        assert list_students(
            db_session, has_housing=True, search=f"ended-{tag}"
        ).items == []

    def test_active_row_past_its_end_date_is_not_live(self, db_session):
        """Status and dates must agree; a stale ACTIVE row is not current housing."""
        tag = uuid.uuid4().hex[:7]
        student = _mk_student(db_session, f"stale-{tag}")
        _mk_assignment(
            db_session,
            student,
            start=datetime(2020, 1, 15),
            end=datetime(2020, 6, 30),
        )
        db_session.commit()

        assert list_students(
            db_session, has_housing=True, search=f"stale-{tag}"
        ).items == []

    def test_future_assignment_has_not_started(self, db_session):
        tag = uuid.uuid4().hex[:7]
        student = _mk_student(db_session, f"future-{tag}")
        _mk_assignment(db_session, student, start=datetime(2099, 1, 15))
        db_session.commit()

        assert list_students(
            db_session, has_housing=True, search=f"future-{tag}"
        ).items == []


# ── B. Atomic, audited bulk attendance ──────────────────────────────────────

BULK_KEYS = {
    "id",
    "student_id",
    "student_name",
    "class_section_id",
    "session_date",
    "status",
    "recorded_by",
    "note",
    "created_at",
    "updated_at",
}


def _post_bulk(client, section: ClassSection, records: list[dict]):
    return client.post(
        f"{API}/academics/classes/{section.id}/attendance",
        json={"session_date": SESSION_DATE.isoformat(), "records": records},
    )


class TestAtomicBulkAttendance:
    def test_multi_row_write_persists_every_row(self, client, db_session):
        tag = uuid.uuid4().hex[:7]
        section = _mk_section(db_session, tag)
        first = _mk_student(db_session, f"bulk-a-{tag}")
        second = _mk_student(db_session, f"bulk-b-{tag}")
        _enroll(db_session, first, section)
        _enroll(db_session, second, section)
        db_session.commit()

        _login(client)
        response = _post_bulk(
            client,
            section,
            [
                {"student_id": str(first.id), "status": "ABSENT"},
                {"student_id": str(second.id), "status": "ABSENT"},
            ],
        )

        assert response.status_code == 201, response.text
        payload = response.json()
        assert len(payload) == 2
        # The public response shape is unchanged by the transaction rework.
        assert set(payload[0]) == BULK_KEYS
        assert {row["student_id"] for row in payload} == {str(first.id), str(second.id)}

        db_session.expire_all()
        rows = (
            db_session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_section_id == section.id)
            .all()
        )
        assert len(rows) == 2
        assert {row.status for row in rows} == {AttendanceStatus.ABSENT}

    def test_one_invalid_row_rolls_back_the_whole_batch(self, client, db_session):
        tag = uuid.uuid4().hex[:7]
        section = _mk_section(db_session, tag)
        enrolled = _mk_student(db_session, f"rb-a-{tag}")
        unenrolled = _mk_student(db_session, f"rb-b-{tag}")
        _enroll(db_session, enrolled, section)
        db_session.commit()

        _login(client)
        response = _post_bulk(
            client,
            section,
            [
                {"student_id": str(enrolled.id), "status": "ABSENT"},
                {"student_id": str(unenrolled.id), "status": "ABSENT"},
            ],
        )

        assert response.status_code == 400, response.text
        assert "not enrolled" in response.json()["error"]["message"]

        db_session.expire_all()
        assert (
            db_session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_section_id == section.id)
            .count()
            == 0
        )

    def test_unknown_student_rolls_back(self, client, db_session):
        tag = uuid.uuid4().hex[:7]
        section = _mk_section(db_session, tag)
        enrolled = _mk_student(db_session, f"unk-a-{tag}")
        _enroll(db_session, enrolled, section)
        db_session.commit()

        _login(client)
        response = _post_bulk(
            client,
            section,
            [
                {"student_id": str(enrolled.id), "status": "ABSENT"},
                {"student_id": str(uuid.uuid4()), "status": "ABSENT"},
            ],
        )

        assert response.status_code == 400, response.text
        db_session.expire_all()
        assert (
            db_session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_section_id == section.id)
            .count()
            == 0
        )

    def test_duplicate_row_inside_one_payload_is_refused(self, client, db_session):
        tag = uuid.uuid4().hex[:7]
        section = _mk_section(db_session, tag)
        student = _mk_student(db_session, f"dup-{tag}")
        _enroll(db_session, student, section)
        db_session.commit()

        _login(client)
        response = _post_bulk(
            client,
            section,
            [
                {"student_id": str(student.id), "status": "ABSENT"},
                {"student_id": str(student.id), "status": "ABSENT"},
            ],
        )

        assert response.status_code == 400, response.text
        db_session.expire_all()
        assert (
            db_session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_section_id == section.id)
            .count()
            == 0
        )

    def test_audit_failure_rolls_back_the_attendance(
        self, client, db_session, monkeypatch
    ):
        tag = uuid.uuid4().hex[:7]
        section = _mk_section(db_session, tag)
        first = _mk_student(db_session, f"audit-a-{tag}")
        second = _mk_student(db_session, f"audit-b-{tag}")
        _enroll(db_session, first, section)
        _enroll(db_session, second, section)
        db_session.commit()

        def _explode(*_args, **_kwargs):
            raise RuntimeError("audit backend unavailable")

        # The service holds the reference, so patching the module attribute is
        # what the request actually calls.
        monkeypatch.setattr("app.services.academic.record_audit", _explode)

        _login(client)
        with pytest.raises(RuntimeError):
            _post_bulk(
                client,
                section,
                [
                    {"student_id": str(first.id), "status": "ABSENT"},
                    {"student_id": str(second.id), "status": "ABSENT"},
                ],
            )

        db_session.expire_all()
        assert (
            db_session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_section_id == section.id)
            .count()
            == 0
        )

    def test_each_record_gets_its_own_attributed_before_after_entry(
        self, client, db_session
    ):
        tag = uuid.uuid4().hex[:7]
        section = _mk_section(db_session, tag)
        first = _mk_student(db_session, f"ctx-a-{tag}")
        second = _mk_student(db_session, f"ctx-b-{tag}")
        _enroll(db_session, first, section)
        _enroll(db_session, second, section)
        db_session.commit()

        _login(client)
        response = _post_bulk(
            client,
            section,
            [
                {"student_id": str(first.id), "status": "ABSENT", "note": "no show"},
                {"student_id": str(second.id), "status": "LATE"},
            ],
        )
        assert response.status_code == 201, response.text

        db_session.expire_all()
        records = (
            db_session.query(AttendanceRecord)
            .filter(AttendanceRecord.class_section_id == section.id)
            .all()
        )
        record_ids = {row.id for row in records}
        entries = (
            db_session.query(AuditLog)
            .filter(
                AuditLog.entity_type == "attendance_record",
                AuditLog.entity_id.in_(record_ids),
            )
            .all()
        )
        # One entry per record, not one aggregate entry describing a count.
        assert len(entries) == 2
        assert {entry.entity_id for entry in entries} == record_ids

        admin = (
            db_session.query(User)
            .filter(User.email == "admin@school.portal")
            .first()
        )
        assert admin is not None
        assert {entry.actor_id for entry in entries} == {admin.id}

        by_student = {entry.context["student_id"]: entry for entry in entries}
        absent_entry = by_student[str(first.id)]
        assert absent_entry.context["previous_status"] is None
        assert absent_entry.context["new_status"] == "ABSENT"
        assert absent_entry.context["previous_note"] is None
        assert absent_entry.context["new_note"] == "no show"
        assert absent_entry.context["attendance_date"] == SESSION_DATE.isoformat()
        assert absent_entry.context["class_section_id"] == str(section.id)
        assert by_student[str(second.id)].context["new_status"] == "LATE"


# ── C. Permissions ──────────────────────────────────────────────────────────


def _declared_codenames() -> set[str]:
    return {
        permission["codename"]
        for group in ALL_PERMISSIONS.values()
        for permission in group
    }


class TestPhase0Permissions:
    def test_management_has_view_and_class_recording(self, db_session):
        permissions = _role_permissions(db_session, "MANAGEMENT")
        assert "attendance.view" in permissions
        assert "attendance.edit" in permissions
        assert "attendance.record_class" in permissions

    def test_management_records_dormitory_attendance(self, db_session):
        """The dormitory workflow now exists, so Management records it.

        The original guard asserted the permission was withheld because the
        workflow did not exist yet; the phase that built it granted both
        codenames, and Teachers still do not hold either.
        """
        permissions = _role_permissions(db_session, "MANAGEMENT")
        assert {"attendance.record_dormitory", "attendance.view_dormitory"} <= permissions

    def test_withheld_and_granted_codenames_stay_declared(self, db_session):
        declared = _declared_codenames()
        assert {"attendance.record_dormitory", "attendance.manage_calendar"} <= declared
        management = _role_permissions(db_session, "MANAGEMENT")
        # Phase 1 authorized calendar administration, and the dormitory phase
        # authorized dormitory recording, so Management holds both.
        assert "attendance.manage_calendar" in management
        assert "attendance.record_dormitory" in management

    def test_management_can_record_but_teachers_cannot_record_institution_wide(
        self, db_session
    ):
        teacher = _role_permissions(db_session, "TEACHER")
        assert "attendance.record_class" not in teacher
        assert "attendance.record_dormitory" not in teacher
        assert "attendance.manage_calendar" not in teacher
        assert "attendance.manage_commencement" not in teacher
        # Phase 3 records absences, not per-class registers; the scoped
        # permission is separate and still enforced per assigned section.
        assert "attendance.record_absence" in teacher

    def test_teacher_grants_are_unchanged(self, db_session):
        teacher = _role_permissions(db_session, "TEACHER")
        # Section-level records are still a teacher's job.
        assert {"attendance.view", "attendance.edit", "grades.view", "grades.edit"} <= teacher
        # Teachers still have no access to passports or private files.
        assert not {"documents.view", "immigration.view_all"} <= teacher

    def test_student_grants_are_unchanged(self, db_session):
        student = _role_permissions(db_session, "STUDENT")
        assert {"attendance.view", "grades.view", "immigration.view"} <= student
        assert "attendance.record_class" not in student
        assert "attendance.edit" not in student

    def test_management_role_is_the_only_role_that_changed(self, db_session):
        """Admin, Teacher and Student hold exactly their pre-change sets."""
        from app.permissions.constants import ROLE_PERMISSIONS

        for role_name in ("ADMIN", "TEACHER", "STUDENT"):
            assert _role_permissions(db_session, role_name) == set(
                ROLE_PERMISSIONS[role_name]
            )

    def test_admin_still_holds_every_declared_permission(self, db_session):
        declared = _declared_codenames()
        assert declared <= _role_permissions(db_session, "ADMIN")

    def test_examination_permissions_are_declared_and_granted(self, db_session):
        """Examination management shipped; grade publication did not move.

        The codenames were declared ahead of the feature. Now that Admin and
        Management schedule, record and publish examinations, they hold those
        four grants; publishing through the separate grades domain is still
        withheld.
        """
        declared = _declared_codenames()
        assert {"exams.view", "exams.manage", "exams.publish", "grades.publish"} <= declared
        management = _role_permissions(db_session, "MANAGEMENT")
        assert {
            "exams.view",
            "exams.manage",
            "exams.record_results",
            "exams.publish",
        } <= management
        assert "grades.publish" not in management


# ── D. Assessment enumeration guard ─────────────────────────────────────────


class TestAssessmentEndpointScope:
    def test_staff_keep_their_legitimate_access_and_students_are_refused(
        self, client, db_session
    ):
        tag = uuid.uuid4().hex[:7]
        taught = _mk_section(db_session, tag, code="A")
        other = _mk_section(db_session, tag, code="B")

        teacher_user = (
            db_session.query(User).filter(User.email == "teacher@school.portal").first()
        )
        assert teacher_user is not None
        teacher_staff = (
            db_session.query(Staff).filter(Staff.user_id == teacher_user.id).first()
        )
        assert teacher_staff is not None
        db_session.add(
            TeacherAssignment(
                class_section_id=taught.id,
                staff_id=teacher_staff.id,
                is_active=True,
            )
        )
        db_session.commit()

        _login(client, "admin@school.portal")
        assert (
            client.get(f"{API}/academics/classes/{taught.id}/assessments").status_code
            == 200
        )

        _login(client, "management@school.portal")
        assert (
            client.get(f"{API}/academics/classes/{taught.id}/assessments").status_code
            == 200
        )

        _login(client, "teacher@school.portal")
        assert (
            client.get(f"{API}/academics/classes/{taught.id}/assessments").status_code
            == 200
        )
        # A teacher is not a class-section browser: unassigned sections stay shut.
        assert (
            client.get(f"{API}/academics/classes/{other.id}/assessments").status_code
            == 403
        )

        _login(client, "student@school.portal")
        assert (
            client.get(f"{API}/academics/classes/{taught.id}/assessments").status_code
            == 403
        )

    def test_missing_class_still_reports_404_before_scope(self, client):
        _login(client, "admin@school.portal")
        response = client.get(f"{API}/academics/classes/{uuid.uuid4()}/assessments")
        assert response.status_code == 404
