"""Student offering assignment, shared sections and audit coverage."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.models.academic import ProgramOffering
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.audit import AuditLog
from app.models.identity import Staff, Student, User


def _login(client, email: str = "admin@school.portal") -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _mk_student(db, number: str, suffix: str) -> Student:
    user = User(
        email=f"{suffix}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"{suffix}-{uuid.uuid4().hex[:8]}",
        hashed_password="not-used",
        full_name=f"Test {number}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=number,
        first_name="Test",
        last_name=number,
    )
    db.add(student)
    db.flush()
    return student


def _scenario(client, db) -> dict:
    _login(client)
    tag = uuid.uuid4().hex[:6]
    period = client.post(
        "/api/v1/academics/periods",
        json={
            "name": f"Offering {tag}",
            "code": f"P-{tag}",
            "start_date": "2032-09-01",
            "end_date": "2032-12-20",
            "status": "PLANNED",
        },
    ).json()
    courses = {}
    for key, name in (
        ("shared", "Chinese Language"),
        ("math_a", "Advanced Mathematics"),
        ("math_b", "Advanced Mathematics"),
    ):
        courses[key] = client.post(
            "/api/v1/academics/courses",
            json={"code": f"{tag}-{key}", "name": name},
        ).json()

    offerings = {}
    for key, label in (("a", "Program A"), ("b", "Program B")):
        offerings[key] = client.post(
            "/api/v1/academics/program-offerings",
            json={
                "academic_period_id": period["id"],
                "source_id": f"{tag}-{key}",
                "name": f"{label} {tag}",
            },
        ).json()

    sections = {}
    for key, course_key, code in (
        ("shared", "shared", "SH"),
        ("math_a", "math_a", "A"),
        ("math_b", "math_b", "B"),
    ):
        sections[key] = client.post(
            "/api/v1/academics/classes",
            json={
                "course_id": courses[course_key]["id"],
                "academic_period_id": period["id"],
                "section_code": code,
                "capacity": 30,
            },
        ).json()

    client.put(
        f"/api/v1/academics/classes/{sections['shared']['id']}/program-offerings",
        json={"program_offering_ids": [offerings["a"]["id"], offerings["b"]["id"]]},
    )
    client.put(
        f"/api/v1/academics/classes/{sections['math_a']['id']}/program-offerings",
        json={"program_offering_ids": [offerings["a"]["id"]]},
    )
    client.put(
        f"/api/v1/academics/classes/{sections['math_b']['id']}/program-offerings",
        json={"program_offering_ids": [offerings["b"]["id"]]},
    )

    for index, section in enumerate(sections.values()):
        response = client.post(
            "/api/v1/academics/timetable",
            json={
                "class_section_id": section["id"],
                "day_of_week": index,
                "start_time": "09:00:00",
                "end_time": "10:00:00",
            },
        )
        assert response.status_code == 201, response.text

    student_a = _mk_student(db, f"A-{tag}", f"student-a-{tag}")
    student_b = _mk_student(db, f"B-{tag}", f"student-b-{tag}")
    legacy = _mk_student(db, f"L-{tag}", f"student-l-{tag}")
    return {
        "period": period,
        "courses": courses,
        "offerings": offerings,
        "sections": sections,
        "student_a": student_a,
        "student_b": student_b,
        "legacy": legacy,
    }


def _assign(db, student: Student, offering_id: str | None) -> None:
    """Arrange authoritative admission and placement history for read tests."""
    if offering_id is None:
        db.commit()
        return
    offering = db.get(ProgramOffering, uuid.UUID(offering_id))
    assert offering is not None
    now = datetime.now()
    admission = AcademicAdmission(
        student_id=student.id,
        admission_intake_id=offering.academic_period_id,
        admitted_program_id=offering.program_id,
        admitted_program_offering_id=offering.id,
        current_program_id=offering.program_id,
        status="ACTIVE",
        initial_status="ACTIVE",
        verification_status="VERIFIED",
        verified_at=now,
        activated_at=now,
        created_by_id=student.user_id,
    )
    db.add(admission)
    db.flush()
    db.add(
        AcademicPlacement(
            student_id=student.id,
            admission_id=admission.id,
            academic_period_id=offering.academic_period_id,
            program_offering_id=offering.id,
            effective_from=date.today(),
            created_by_id=student.user_id,
        )
    )
    db.commit()


def _student_timetable(client, student_id: str, period_id: str) -> list[dict]:
    response = client.get(
        f"/api/v1/academics/students/{student_id}/timetable?period_id={period_id}"
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_assigned_offering_scopes_shared_and_similar_subjects(client, db_session):
    scenario = _scenario(client, db_session)
    period_id = scenario["period"]["id"]
    a_id = str(scenario["student_a"].id)
    b_id = str(scenario["student_b"].id)

    _assign(db_session, scenario["student_a"], scenario["offerings"]["a"]["id"])
    _assign(db_session, scenario["student_b"], scenario["offerings"]["b"]["id"])

    a_entries = _student_timetable(client, a_id, period_id)
    b_entries = _student_timetable(client, b_id, period_id)
    assert [entry["course_name"] for entry in a_entries] == [
        "Chinese Language",
        "Advanced Mathematics",
    ]
    assert [entry["course_name"] for entry in b_entries] == [
        "Chinese Language",
        "Advanced Mathematics",
    ]
    assert {entry["class_section_id"] for entry in a_entries} == {
        scenario["sections"]["shared"]["id"],
        scenario["sections"]["math_a"]["id"],
    }
    assert {entry["class_section_id"] for entry in b_entries} == {
        scenario["sections"]["shared"]["id"],
        scenario["sections"]["math_b"]["id"],
    }
    assert (
        len(
            [
                entry
                for entry in a_entries
                if entry["class_section_id"] == scenario["sections"]["shared"]["id"]
            ]
        )
        == 1
    )
    assert scenario["sections"]["math_a"]["id"] != scenario["sections"]["math_b"]["id"]

    overview = client.get(
        f"/api/v1/academics/students/{a_id}?period_id={period_id}"
    ).json()
    assert overview["program_offering"]["id"] == scenario["offerings"]["a"]["id"]
    assert len(overview["enrolled_classes"]) == 2


def test_enrollments_narrow_parallel_offering_groups(client, db_session):
    """An enrolled student must not see a parallel group they are not in."""
    scenario = _scenario(client, db_session)
    student_id = str(scenario["student_a"].id)
    period_id = scenario["period"]["id"]
    _assign(db_session, scenario["student_a"], scenario["offerings"]["a"]["id"])

    enrolled = client.post(
        f"/api/v1/academics/classes/{scenario['sections']['shared']['id']}/enrollments",
        json={"student_id": student_id},
    )
    assert enrolled.status_code == 201, enrolled.text

    entries = _student_timetable(client, student_id, period_id)
    assert {entry["class_section_id"] for entry in entries} == {
        scenario["sections"]["shared"]["id"]
    }

    overview = client.get(
        f"/api/v1/academics/students/{student_id}?period_id={period_id}"
    ).json()
    assert {entry["class_section_id"] for entry in overview["timetable"]} == {
        scenario["sections"]["shared"]["id"]
    }


def test_null_offering_keeps_enrollment_fallback(client, db_session):
    scenario = _scenario(client, db_session)
    legacy_id = str(scenario["legacy"].id)
    response = client.post(
        f"/api/v1/academics/classes/{scenario['sections']['math_b']['id']}/enrollments",
        json={"student_id": legacy_id},
    )
    assert response.status_code == 201, response.text

    entries = _student_timetable(client, legacy_id, scenario["period"]["id"])
    assert {entry["course_name"] for entry in entries} == {"Advanced Mathematics"}
    assert entries[0]["class_section_id"] == scenario["sections"]["math_b"]["id"]


def test_offering_change_is_retired_without_side_effects(client, db_session):
    scenario = _scenario(client, db_session)
    student_id = str(scenario["student_a"].id)
    a_id = scenario["offerings"]["a"]["id"]
    b_id = scenario["offerings"]["b"]["id"]

    _assign(db_session, scenario["student_a"], a_id)
    before_audits = db_session.query(AuditLog).count()
    refused = client.patch(
        f"/api/v1/students/{student_id}/program-offering",
        json={"program_offering_id": b_id, "reason": "Attempted direct change"},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == "PLACEMENT_DIRECT_WRITE_RETIRED"

    db_session.expire_all()
    placement = (
        db_session.query(AcademicPlacement)
        .filter(
            AcademicPlacement.student_id == uuid.UUID(student_id),
            AcademicPlacement.ended_at.is_(None),
        )
        .one()
    )
    assert placement.program_offering_id == uuid.UUID(a_id)
    assert db_session.query(AuditLog).count() == before_audits


def test_teacher_scope_remains_assignment_based(client, db_session):
    scenario = _scenario(client, db_session)
    teacher_user = db_session.query(User).filter(User.email == "teacher@school.portal").first()
    staff = db_session.query(Staff).filter(Staff.user_id == teacher_user.id).first()
    response = client.post(
        f"/api/v1/academics/classes/{scenario['sections']['shared']['id']}/teachers",
        json={"staff_id": str(staff.id), "role": "PRIMARY"},
    )
    assert response.status_code in (201, 400)

    _login(client, "teacher@school.portal")
    entries = client.get(
        f"/api/v1/academics/timetable?period_id={scenario['period']['id']}"
    ).json()["items"]
    assert {entry["class_section_id"] for entry in entries} == {
        scenario["sections"]["shared"]["id"]
    }
    denied = client.get(
        f"/api/v1/academics/classes/{scenario['sections']['math_a']['id']}"
    )
    assert denied.status_code == 403


def test_management_can_manage_offerings_and_shared_links(client, db_session):
    scenario = _scenario(client, db_session)
    _login(client, "management@school.portal")
    created = client.post(
        "/api/v1/academics/program-offerings",
        json={
            "academic_period_id": scenario["period"]["id"],
            "source_id": f"mgmt-{uuid.uuid4().hex[:6]}",
            "name": "Management Offering",
        },
    )
    assert created.status_code == 201, created.text
    offering_id = created.json()["id"]

    renamed = client.patch(
        f"/api/v1/academics/program-offerings/{offering_id}",
        json={"name": "Management Offering Renamed"},
    )
    assert renamed.status_code == 200, renamed.text
    linked = client.put(
        f"/api/v1/academics/classes/{scenario['sections']['shared']['id']}/program-offerings",
        json={
            "program_offering_ids": [
                scenario["offerings"]["a"]["id"],
                scenario["offerings"]["b"]["id"],
                offering_id,
            ]
        },
    )
    assert linked.status_code == 200, linked.text
    assert len(linked.json()["program_offerings"]) == 3

    other_period = client.post(
        "/api/v1/academics/periods",
        json={
            "name": "Other intake",
            "code": f"O-{uuid.uuid4().hex[:6]}",
            "start_date": "2033-01-01",
            "end_date": "2033-04-01",
            "status": "PLANNED",
        },
    ).json()
    other = client.post(
        "/api/v1/academics/program-offerings",
        json={
            "academic_period_id": other_period["id"],
            "source_id": f"other-{uuid.uuid4().hex[:6]}",
            "name": "Other Offering",
        },
    ).json()
    mismatch = client.put(
        f"/api/v1/academics/classes/{scenario['sections']['shared']['id']}/program-offerings",
        json={"program_offering_ids": [other["id"]]},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "PROGRAM_OFFERING_PERIOD_MISMATCH"
