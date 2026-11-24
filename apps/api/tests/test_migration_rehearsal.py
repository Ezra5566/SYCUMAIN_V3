"""Synthetic migration rehearsal across all four intakes.

This is the end-to-end proof the migration plan asks for, on synthetic data:

    intakes -> students -> placements -> housing -> immigration
            -> timetable -> account activation

Every link is asserted on the same student record, and the run is repeated to
show that re-running the migration neither duplicates nor overwrites anything.

Nothing here uses real institutional data.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import time

INTAKES = [
    ("2025-FALL", "Fall 2025", "2025-09-01", "2025-12-20"),
    ("2026-SPRING", "Spring 2026", "2026-02-01", "2026-06-15"),
    ("2026-FALL-RH", "Fall 2026", "2026-09-01", "2026-12-20"),
    ("2027-SPRING", "Spring 2027", "2027-02-01", "2027-06-15"),
]

STUDENTS_PER_INTAKE = 2


def _login(client, email="admin@school.portal", password="password123"):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text


def _plan_intakes(client, program_code: str):
    intakes = [
        {
            "code": code,
            "name": name,
            "start_date": start,
            "end_date": end,
            "status": "PLANNED",
            "offerings": [
                {
                    "source_id": f"rh-{code.lower()}",
                    "name": f"Rehearsal {name}",
                    "program_code": program_code,
                }
            ],
        }
        for code, name, start, end in INTAKES
    ]
    response = client.post("/api/v1/academics/intakes/plan", json={"intakes": intakes})
    assert response.status_code == 200, response.text
    return {item["intake"]: item for item in response.json()["intakes"]}


def _student_rows():
    rows = []
    for code, _name, _start, _end in INTAKES:
        for index in range(STUDENTS_PER_INTAKE):
            number = f"RH-{code}-{index + 1}"
            rows.append((code, number, f"{number.lower()}@example.com"))
    return rows


def _csv(rows) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "student_id",
            "first_name",
            "last_name",
            "email",
            "nationality",
            "phone",
        ]
    )
    for _code, number, email in rows:
        writer.writerow([number, "Rehearsal", "Student", email, "Kenya", "+254700000000"])
    return buffer.getvalue().encode()


def _import(client, rows):
    return client.post(
        "/api/v1/students/import",
        params={"dry_run": False, "skip_invalid": False},
        files={"file": ("rehearsal.csv", _csv(rows), "text/csv")},
    )


def test_full_synthetic_migration_rehearsal(client, db_session, monkeypatch):
    from app.config.settings import get_settings
    from app.models.academic import (
        AcademicPeriod,
        Classroom,
        ClassroomStatus,
        ClassSection,
        ClassSectionProgramOffering,
        Course,
        TeacherAssignment,
        TimetableEntry,
    )
    from app.models.admission import AcademicPlacement
    from app.models.housing import (
        Bed,
        Building,
        Floor,
        HousingAssignment,
        Room,
    )
    from app.models.identity import Staff, Student, User
    from app.models.immigration import ImmigrationProfile
    from app.services import housing_import
    from app.services.immigration import import_immigration_profile

    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)

    _login(client)
    admin = db_session.query(User).filter(User.email == "admin@school.portal").first()

    # A canonical programme is required before an offering can be placed. The
    # rehearsal keeps this mapping explicit rather than inventing one.
    suffix_code = uuid.uuid4().hex[:6].upper()
    major = client.post(
        "/api/v1/academics/majors",
        json={"code": f"RM-{suffix_code}", "name": "Rehearsal Major"},
    )
    assert major.status_code == 201, major.text
    program = client.post(
        "/api/v1/academics/programs",
        json={
            "major_id": major.json()["id"],
            "code": f"RP-{suffix_code}",
            "name": "Rehearsal Programme",
        },
    )
    assert program.status_code == 201, program.text
    program_code = program.json()["code"]

    # --- 1. Academic intakes -------------------------------------------------
    plan = _plan_intakes(client, program_code)
    assert len(plan) == 4
    periods = {
        code: db_session.query(AcademicPeriod)
        .filter(AcademicPeriod.code == code)
        .first()
        for code in plan
    }
    assert all(period is not None for period in periods.values())
    assert periods["2027-SPRING"].status == "PLANNED"
    offering_ids = {
        code: plan[code]["offerings"][0]["program_offering_id"] for code in plan
    }

    # --- 2. Students ---------------------------------------------------------
    rows = _student_rows()
    imported = _import(client, rows)
    assert imported.status_code == 200, imported.text
    report = imported.json()
    assert report["created"] == len(rows), report
    assert report["accounts"]["activation_required"] == len(rows)

    db_session.expire_all()
    students = {
        number: db_session.query(Student)
        .filter(Student.student_id == number)
        .first()
        for _code, number, _email in rows
    }
    assert all(student is not None for student in students.values())
    # Exactly one account per student number: no duplicates from the import.
    emails = [email for _code, _number, email in rows]
    assert (
        db_session.query(User).filter(User.email.in_(emails)).count() == len(rows)
    )

    # --- 3. Admission and intake placement -----------------------------------
    for code, number, _email in rows:
        student = students[number]
        admission = client.post(
            f"/api/v1/students/{student.id}/admissions",
            json={
                "admission_intake_id": str(periods[code].id),
                "program_offering_id": offering_ids[code],
                "initial_status": "ACTIVE",
            },
        )
        assert admission.status_code == 201, admission.text
        placement = client.post(
            f"/api/v1/students/{student.id}/placements",
            json={
                "admission_id": admission.json()["id"],
                "program_offering_id": offering_ids[code],
            },
        )
        assert placement.status_code == 201, placement.text

    db_session.expire_all()
    for code, number, _email in rows:
        placement = (
            db_session.query(AcademicPlacement)
            .filter(AcademicPlacement.student_id == students[number].id)
            .first()
        )
        assert placement is not None
        assert placement.academic_period_id == periods[code].id

    # --- 4. Housing ----------------------------------------------------------
    suffix = uuid.uuid4().hex[:6]
    building = Building(name=f"Rehearsal Hall {suffix}")
    db_session.add(building)
    db_session.flush()
    floor = Floor(building_id=building.id, floor_number=1)
    db_session.add(floor)
    db_session.flush()
    room = Room(floor_id=floor.id, room_number="101", capacity=len(rows))
    db_session.add(room)
    db_session.flush()
    for index in range(len(rows)):
        db_session.add(Bed(room_id=room.id, bed_number=index + 1))
    db_session.commit()

    housing_csv = io.StringIO()
    writer = csv.writer(housing_csv)
    writer.writerow(["student_id", "building", "floor", "room", "bed", "start_date"])
    for index, (_code, number, _email) in enumerate(rows, start=1):
        writer.writerow([number, building.name, 1, "101", index, "2026-09-01"])

    parsed = housing_import.parse_rows(housing_csv.getvalue().encode(), max_rows=100)
    housing_report = housing_import.apply_housing_import(
        db_session, parsed, actor_id=admin.id, source_reference="rehearsal"
    )
    assert housing_report.created == len(rows), housing_report

    db_session.expire_all()
    # Housing assignments reference the account (users.id), unlike academic and
    # immigration rows, which reference students.id. The rehearsal asserts the
    # link through the student's account on purpose.
    all_assignments = db_session.query(HousingAssignment).all()
    assert len(all_assignments) == len(rows)
    assigned_user_ids = {item.student_id for item in all_assignments}
    for _code, number, _email in rows:
        assert students[number].user_id in assigned_user_ids, number

    # --- 5. Immigration ------------------------------------------------------
    for _code, number, _email in rows:
        profile, conflicts, changed = import_immigration_profile(
            db_session,
            student_id=students[number].id,
            data={"passport_number": f"P-{number}", "visa_type": "STUDENT"},
            source_reference="rehearsal",
            actor_id=admin.id,
        )
        assert conflicts == []
        assert changed is True
        assert profile.verification_status == "UNVERIFIED"
        assert profile.verified_at is None
    db_session.commit()

    # --- 6. Timetable per intake --------------------------------------------
    from app.models.academic import Program

    program = db_session.query(Program).filter(Program.code == program_code).first()
    teacher_user = (
        db_session.query(User).filter(User.email == "teacher@school.portal").first()
    )
    staff = db_session.query(Staff).filter(Staff.user_id == teacher_user.id).first()
    if staff is None:
        staff = Staff(user_id=teacher_user.id, first_name="Tess", last_name="Teacher")
        db_session.add(staff)
        db_session.flush()

    sections_by_intake: dict[str, object] = {}
    for code, _name, _start, _end in INTAKES:
        period = periods[code]
        course = Course(
            code=f"RH-{code}",
            name=f"Rehearsal Course {code}",
            program_id=program.id if program else None,
        )
        db_session.add(course)
        db_session.flush()
        section = ClassSection(
            course_id=course.id,
            academic_period_id=period.id,
            section_code="A",
            status="PLANNED",
        )
        classroom = Classroom(room_code=f"RH-{code}", status=ClassroomStatus.AVAILABLE)
        db_session.add_all([section, classroom])
        db_session.flush()
        db_session.add(
            ClassSectionProgramOffering(
                class_section_id=section.id,
                program_offering_id=offering_ids[code],
            )
        )
        db_session.add(TeacherAssignment(class_section_id=section.id, staff_id=staff.id))
        db_session.add(
            TimetableEntry(
                class_section_id=section.id,
                classroom_id=classroom.id,
                day_of_week=0,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )
        )
        sections_by_intake[code] = section
    db_session.commit()

    # --- 7. Reconciliation is clean for every intake -------------------------
    for code, _name, _start, _end in INTAKES:
        reconciliation = client.get(
            "/api/v1/academics/timetable/reconciliation",
            params={"period_id": str(periods[code].id)},
        )
        assert reconciliation.status_code == 200, reconciliation.text
        body = reconciliation.json()
        assert body["status"] == "CLEAN", (code, body["findings"])
        assert body["totals"]["live_entries"] == 1

    # --- 8. Accounts: no password until activation ---------------------------
    activation_links: dict[str, str] = {}
    for _code, number, _email in rows:
        user = students[number].user
        state = client.get(f"/api/v1/users/{user.id}/activation").json()
        assert state["state"] == "PENDING" or state["state"] == "NONE"
        assert state["activation_required"] is True

        issued = client.post(
            f"/api/v1/users/{user.id}/activation",
            json={"identity_verified": True, "verification_reference": "REHEARSAL"},
        )
        assert issued.status_code == 200, issued.text
        activation_links[number] = issued.json()["activation_url"].split("token=", 1)[1]

    # Complete activation for one student per intake.
    activated: list[tuple[str, str]] = []
    for code, _name, _start, _end in INTAKES:
        number = f"RH-{code}-1"
        email = next(email for _c, n, email in rows if n == number)
        response = client.post(
            "/api/v1/auth/activation",
            json={
                "token": activation_links[number],
                "new_password": "Rehearsal1!Pass",
            },
        )
        assert response.status_code == 200, response.text
        activated.append((email, number))

    # A token is single use.
    reuse = client.post(
        "/api/v1/auth/activation",
        json={"token": activation_links["RH-2025-FALL-1"], "new_password": "Rehearsal1!Pass"},
    )
    assert reuse.status_code == 404

    # An un-activated account still cannot sign in.
    pending_email = next(
        email for _c, n, email in rows if n == "RH-2026-SPRING-2"
    )
    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": pending_email, "password": "Rehearsal1!Pass"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "ACCOUNT_NOT_ACTIVATED"

    # --- 9. The activated student sees only their own intake's timetable -----
    email, number = activated[0]  # 2025 Fall
    student = students[number]
    _login(client, email, "Rehearsal1!Pass")
    own = client.get(
        f"/api/v1/academics/students/{student.id}/timetable",
        params={"period_id": str(periods["2025-FALL"].id)},
    )
    assert own.status_code == 200, own.text
    assert [item["class_section_id"] for item in own.json()["items"]] == [
        str(sections_by_intake["2025-FALL"].id)
    ]

    other_intake = client.get(
        f"/api/v1/academics/students/{student.id}/timetable",
        params={"period_id": str(periods["2027-SPRING"].id)},
    )
    assert other_intake.json()["items"] == []

    # Another student's record is refused outright.
    other_student = students["RH-2027-SPRING-1"]
    assert client.get(
        f"/api/v1/academics/students/{other_student.id}/timetable"
    ).status_code == 403

    # --- 10. Teacher sees only assigned sections -----------------------------
    _login(client, "teacher@school.portal")
    teacher_view = client.get(
        "/api/v1/academics/timetable",
        params={"period_id": str(periods["2026-SPRING"].id)},
    ).json()
    assert [item["class_section_id"] for item in teacher_view["items"]] == [
        str(sections_by_intake["2026-SPRING"].id)
    ]

    # --- 11. Reports ---------------------------------------------------------
    _login(client)
    account_report = client.get("/api/v1/users/migration/account-report").json()
    totals = account_report["totals"]
    assert totals["activated"] >= 4
    assert totals["activation_pending"] >= 4
    by_intake = {item["intake"]: item for item in account_report["by_intake"]}
    for code, _name, _start, _end in INTAKES:
        assert by_intake[code]["students"] == STUDENTS_PER_INTAKE
    serialized = str(account_report)
    assert "token=" not in serialized

    # --- 12. Re-running the migration changes nothing -----------------------
    again = _import(client, rows)
    assert again.status_code == 200, again.text
    rerun = again.json()
    assert rerun["created"] == 0
    assert rerun["accounts"]["matched"] == len(rows)
    assert rerun["rows"][0]["status"] == "MATCHED"

    db_session.expire_all()
    for _code, number, _email in rows:
        assert (
            db_session.query(Student).filter(Student.student_id == number).count() == 1
        )
    assert (
        db_session.query(HousingAssignment)
        .filter(HousingAssignment.bed_id.isnot(None))
        .count()
        >= len(rows)
    )
    profiles = db_session.query(ImmigrationProfile).count()
    assert profiles >= len(rows)

    replan = _plan_intakes(client, program_code)
    assert all(item["status"] == "EXISTING" for item in replan.values())

    # No table gained a second copy of a student's timetable.
    assert (
        db_session.query(TimetableEntry)
        .filter(TimetableEntry.class_section_id.in_([s.id for s in sections_by_intake.values()]))
        .count()
        == len(INTAKES)
    )
