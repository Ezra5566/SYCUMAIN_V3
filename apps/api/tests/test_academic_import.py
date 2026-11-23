"""Staged SCU timetable import, nullability, isolation and weekend tests."""

from __future__ import annotations

from datetime import date

import pytest

from app.database.session import SessionLocal
from app.models.academic import (
    AcademicImportBatch,
    AcademicImportRow,
    AcademicPeriod,
    AcademicPeriodStatus,
    Classroom,
    ClassSection,
    Course,
    ProgramOffering,
    TimetableEntry,
)
from app.seed_academic import seed_academic
from app.services.academic import get_teacher_class_section_ids
from app.services.academic_import import (
    DEFAULT_SOURCE,
    apply_import,
    prepare_import,
    rollback_batch,
    section_key,
)


@pytest.fixture(scope="module", autouse=True)
def academic_structure():
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()
    yield


def _mapped_periods(db_session) -> dict[str, str]:
    fall = db_session.query(AcademicPeriod).filter(AcademicPeriod.code == "2026-FALL").one()
    result = {"2026-autumn": str(fall.id)}
    for source_id, code, name in (
        ("2025-autumn", "TEST-2025A", "Test 2025 Autumn"),
        ("2026-spring", "TEST-2026S", "Test 2026 Spring"),
    ):
        period = (
            db_session.query(AcademicPeriod)
            .filter(AcademicPeriod.code == code)
            .first()
        )
        if period is None:
            period = AcademicPeriod(
                name=name,
                code=code,
                start_date=date(2025, 9, 1) if "2025" in code else date(2026, 2, 1),
                end_date=date(2026, 1, 15) if "2025" in code else date(2026, 7, 1),
                status=AcademicPeriodStatus.PLANNED,
            )
            db_session.add(period)
            db_session.flush()
        result[source_id] = str(period.id)
    return result


def _login_admin(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    )
    assert response.status_code == 200, response.text


def test_prepare_is_staged_only(db_session):
    report = prepare_import(db_session, DEFAULT_SOURCE)
    assert report["periods"] == 3
    assert report["offerings"] == 15
    assert report["courses"] == 26
    assert report["rooms"] == 11
    assert report["sections"] == 33
    assert report["section_offerings"] == 51
    assert report["sessions"] == 52
    assert report["raw_schedule_rows"] == 76
    assert report["merged_schedule_rows"] == 24
    # Nine shared session identities collapse into seven canonical sections.
    assert report["shared_session_groups"] == 9
    assert report["shared_sections"] == 7
    assert report["held_sections"] == 2
    assert report["held_sessions"] == 4

    batch = db_session.query(AcademicImportBatch).filter(
        AcademicImportBatch.id == report["batch_id"]
    ).one()
    assert batch.status == "READY"
    assert batch.dry_run is True

    # A dry run does not write academic rows.
    assert db_session.query(ProgramOffering).count() == 0
    assert db_session.query(AcademicImportRow).filter(
        AcademicImportRow.batch_id == batch.id,
        AcademicImportRow.entity_type == "raw_schedule_row",
    ).count() == 76


def test_apply_nullability_idempotence_and_rollback(client, db_session):
    periods = _mapped_periods(db_session)
    report = prepare_import(db_session, DEFAULT_SOURCE)
    batch_id = report["batch_id"]

    applied = apply_import(db_session, batch_id, period_map=periods)
    assert applied["status"] == "APPLIED"
    assert applied["applied_periods"] == 3
    assert applied["applied_offerings"] == 15
    assert applied["applied_sections"] == 31

    batch = db_session.query(AcademicImportBatch).filter(
        AcademicImportBatch.id == batch_id
    ).one()
    imported_sections = db_session.query(ClassSection).filter(
        ClassSection.import_batch_id == batch.id
    ).all()
    assert len(imported_sections) == 31
    assert all(section.section_code is None for section in imported_sections)
    assert all(section.capacity is None for section in imported_sections)

    imported_courses = db_session.query(Course).filter(
        Course.import_batch_id == batch.id
    ).all()
    assert len(imported_courses) == 26
    assert all(course.code is None for course in imported_courses)
    assert all(course.credits is None for course in imported_courses)

    imported_rooms = db_session.query(Classroom).filter(
        Classroom.import_batch_id == batch.id
    ).all()
    assert len(imported_rooms) == 11
    assert all(room.capacity is None for room in imported_rooms)

    # The two N103 sections and their four sessions are never live.
    held_course_sections = (
        db_session.query(ClassSection)
        .join(Course)
        .filter(Course.name.in_(
            ["AI Ethics (International)", "AI Thinking and Ethics (International)"]
        ))
        .all()
    )
    assert held_course_sections == []
    assert (
        db_session.query(TimetableEntry)
        .join(ClassSection)
        .join(Course)
        .filter(Course.name.in_(
            ["AI Ethics (International)", "AI Thinking and Ethics (International)"]
        ))
        .count()
        == 0
    )

    # A shared group is one section with two live sessions, not two bookings.
    shared = (
        db_session.query(ClassSection)
        .filter(
            ClassSection.source_key
            == section_key(
                "2026-autumn",
                "Chinese Language",
                ["ai-2026a", "civil-2026a", "business-2026a", "cs-2026a"],
            )
        )
        .one()
    )
    assert len(shared.timetable_entries) == 2
    assert len(shared.timetable_entries) == len(
        {entry.source_key for entry in shared.timetable_entries}
    )

    # The API preserves NULL rather than substituting 3/30/empty strings.
    _login_admin(client)
    courses = client.get("/api/v1/academics/courses?page_size=100").json()["items"]
    null_course = next(
        course
        for course in courses
        if course["source_key"] and course["code"] is None
    )
    assert null_course["credits"] is None
    rooms = client.get("/api/v1/academics/classrooms?page_size=100").json()["items"]
    assert any(room["source_key"] and room["capacity"] is None for room in rooms)
    classes = client.get("/api/v1/academics/classes?page_size=100").json()["items"]
    assert any(
        section["source_label"] and section["section_code"] is None and section["capacity"] is None
        for section in classes
    )

    # A second apply does not duplicate any source-owned row.
    before_counts = (
        db_session.query(ClassSection).count(),
        db_session.query(TimetableEntry).count(),
        db_session.query(Course).count(),
        db_session.query(Classroom).count(),
    )
    again = apply_import(db_session, batch_id, period_map=periods)
    assert again["status"] == "APPLIED"
    assert (
        db_session.query(ClassSection).count(),
        db_session.query(TimetableEntry).count(),
        db_session.query(Course).count(),
        db_session.query(Classroom).count(),
    ) == before_counts

    rolled = rollback_batch(db_session, batch_id)
    assert rolled["status"] == "ROLLED_BACK"
    assert db_session.query(ClassSection).filter(
        ClassSection.import_batch_id == batch.id
    ).count() == 0
    assert db_session.query(Course).filter(Course.import_batch_id == batch.id).count() == 0
    assert db_session.query(Classroom).filter(
        Classroom.import_batch_id == batch.id
    ).count() == 0
    assert db_session.query(AcademicPeriod).filter(
        AcademicPeriod.code == "2026-FALL"
    ).one().source_key is None


@pytest.mark.parametrize("day", [5, 6])
def test_weekend_sessions_are_returned(client, db_session, day):
    _login_admin(client)
    course = client.post(
        "/api/v1/academics/courses",
        json={"name": f"Weekend Course {day}"},
    ).json()
    period = db_session.query(AcademicPeriod).filter(
        AcademicPeriod.code == "2026-FALL"
    ).one()
    section = client.post(
        "/api/v1/academics/classes",
        json={
            "course_id": course["id"],
            "academic_period_id": str(period.id),
            "section_code": None,
            "capacity": None,
        },
    ).json()
    room = client.post(
        "/api/v1/academics/classrooms",
        json={"room_code": f"WKND-{day}", "capacity": None},
    ).json()
    response = client.post(
        "/api/v1/academics/timetable",
        json={
            "class_section_id": section["id"],
            "classroom_id": room["id"],
            "day_of_week": day,
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        },
    )
    assert response.status_code == 201, response.text
    entries = client.get(
        f"/api/v1/academics/timetable?period_id={period.id}&class_section_id={section['id']}"
    ).json()["items"]
    assert [entry["day_of_week"] for entry in entries] == [day]


def test_period_isolation_and_teacher_scope(client, db_session):
    _login_admin(client)
    fall = db_session.query(AcademicPeriod).filter(
        AcademicPeriod.code == "2026-FALL"
    ).one()
    empty = AcademicPeriod(
        name="Isolation Test Period",
        code="TEST-ISOLATION",
        start_date=date(2035, 1, 1),
        end_date=date(2035, 5, 1),
        status=AcademicPeriodStatus.PLANNED,
    )
    db_session.add(empty)
    db_session.flush()

    student = client.get("/api/v1/academics/classes?period_id=" + str(empty.id))
    assert student.status_code == 200

    # A student's own academic overview never folds in another period.
    from app.models.identity import Student, User
    user = db_session.query(User).filter(User.email == "student@school.portal").one()
    student_row = db_session.query(Student).filter(Student.user_id == user.id).one()
    client.post(
        "/api/v1/auth/login",
        json={"email": "student@school.portal", "password": "password123"},
    )
    empty_overview = client.get(
        f"/api/v1/academics/students/{student_row.id}?period_id={empty.id}"
    )
    assert empty_overview.status_code == 200
    assert empty_overview.json()["enrolled_classes"] == []
    assert empty_overview.json()["timetable"] == []
    assert empty_overview.json()["selected_period"]["id"] == str(empty.id)

    # Teacher scope is enforced by the API even when a period is requested.
    teacher = client.post(
        "/api/v1/auth/login",
        json={"email": "teacher@school.portal", "password": "password123"},
    )
    assert teacher.status_code == 200
    teacher_sections = client.get(
        f"/api/v1/academics/classes?period_id={fall.id}"
    ).json()["items"]
    from app.models.identity import Staff, User

    teacher_user = db_session.query(User).filter(
        User.email == "teacher@school.portal"
    ).one()
    teacher_staff = db_session.query(Staff).filter(
        Staff.user_id == teacher_user.id
    ).one()
    assigned = get_teacher_class_section_ids(db_session, teacher_staff.id)
    returned = {section["id"] for section in teacher_sections}
    assert returned
    assert returned <= {str(section_id) for section_id in assigned}
    teacher_timetable = client.get(
        f"/api/v1/academics/timetable?period_id={fall.id}"
    ).json()["items"]
    assert all(
        entry["class_section_id"] in {str(section_id) for section_id in assigned}
        for entry in teacher_timetable
    )
    assert len(teacher_sections) >= 1
