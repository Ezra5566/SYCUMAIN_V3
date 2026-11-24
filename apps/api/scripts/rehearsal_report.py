"""Run the synthetic four-intake migration rehearsal and write its reports.

Usage (from apps/api):

    .venv/bin/python scripts/rehearsal_report.py [--database-url URL]

The default target is a dedicated scratch database, never the development or
production one. The script creates the schema, seeds roles and four demo
accounts, then performs the migration sequence on synthetic data:

    intakes -> students -> placements -> housing -> immigration
            -> timetable -> accounts and activation

and writes:

    docs/migration-rehearsal-report.md
    docs/migration-rehearsal-report.json

It refuses to run against a database whose name does not contain "rehearsal".
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import uuid
from datetime import date, datetime, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

DEFAULT_URL = "postgresql://portal:portal@localhost:5434/scumain_rehearsal"
REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs"

INTAKES = [
    ("2025-FALL", "Fall 2025", date(2025, 9, 1), date(2025, 12, 20), "PLANNED"),
    ("2026-SPRING", "Spring 2026", date(2026, 2, 1), date(2026, 6, 15), "PLANNED"),
    ("2026-FALL", "Fall 2026", date(2026, 9, 1), date(2026, 12, 20), "ACTIVE"),
    ("2027-SPRING", "Spring 2027", date(2027, 2, 1), date(2027, 6, 15), "PLANNED"),
]
PER_INTAKE = 3


def _ensure_database(url: str) -> None:
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if "rehearsal" not in (parsed.database or ""):
        raise SystemExit(
            "Refusing to run: the database name must contain 'rehearsal'. "
            f"Got {parsed.database!r}."
        )
    admin_url = parsed.set(database="postgres")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": parsed.database},
        ).scalar()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("REHEARSAL_DATABASE_URL", DEFAULT_URL),
    )
    args = parser.parse_args()

    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ["DATABASE_URL"] = args.database_url
    os.environ.setdefault("ADMISSIONS_WRITE_ENABLED", "true")

    import app.models  # noqa: F401 - registers every table on Base.metadata
    from app.database.session import Base

    _ensure_database(args.database_url)
    engine = create_engine(args.database_url)

    # A scratch database is rebuilt from scratch every run: a rehearsal that
    # accumulates yesterday's rows cannot prove idempotency.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    from app.models.academic import (
        AcademicPeriod,
        Classroom,
        ClassroomStatus,
        ClassSection,
        ClassSectionProgramOffering,
        Course,
        Major,
        Program,
        ProgramOffering,
        TeacherAssignment,
        TimetableEntry,
    )
    from app.models.admission import AcademicAdmission, AcademicPlacement
    from app.models.housing import Bed, Building, Floor, HousingAssignment, Room
    from app.models.identity import Role, Staff, Student, StudentStatus, User
    from app.models.immigration import ImmigrationProfile
    from app.seed import seed_roles_and_permissions, seed_test_users
    from app.services import housing_import, timetable_reconciliation
    from app.services.immigration import import_immigration_profile
    from app.services.intake_plan import (
        IntakeOfferingSpec,
        IntakeSpec,
        plan_intakes,
    )
    from app.services.migration_report import student_account_migration_report

    db = session_factory()
    seed_roles_and_permissions(db)
    seed_test_users(db)
    admin = db.query(User).filter(User.email == "admin@school.portal").first()

    # --- academic structure -------------------------------------------------
    suffix = uuid.uuid4().hex[:6].upper()
    major = Major(code=f"RM-{suffix}", name="Rehearsal Major")
    db.add(major)
    db.flush()
    program = Program(
        major_id=major.id, code=f"RP-{suffix}", name="Rehearsal Programme"
    )
    db.add(program)
    db.flush()

    specs = [
        IntakeSpec(
            code=code,
            name=name,
            start_date=start,
            end_date=end,
            status=status,
            offerings=(
                IntakeOfferingSpec(
                    source_id=f"rh-{code.lower()}",
                    name=f"Rehearsal {name}",
                    program_code=program.code,
                ),
            ),
        )
        for code, name, start, end, status in INTAKES
    ]
    plan = plan_intakes(db, specs, actor_id=admin.id)
    periods = {
        period.code: period
        for period in db.query(AcademicPeriod)
        .filter(AcademicPeriod.code.in_([spec.code for spec in specs]))
        .all()
    }
    offerings = {
        offering.source_key.split(":")[1]: offering
        for offering in db.query(ProgramOffering)
        .filter(ProgramOffering.source_key.like("intake:%"))
        .all()
    }

    # --- students -----------------------------------------------------------
    rows = [
        (code, f"RH-{code}-{index + 1}")
        for code, _n, _s, _e, _st in INTAKES
        for index in range(PER_INTAKE)
    ]
    for _code, number in rows:
        email = f"{number.lower()}@example.com"
        user = User(
            email=email,
            username=number.lower(),
            hashed_password="!",
            full_name=f"Rehearsal {number}",
            activation_required=True,
            is_active=True,
        )
        user.roles.append(db.query(Role).filter(Role.name == "STUDENT").first())
        db.add(user)
        db.flush()
        db.add(
            Student(
                user_id=user.id,
                student_id=number,
                first_name="Rehearsal",
                last_name="Student",
                nationality="Kenya",
                status=StudentStatus.ACTIVE,
            )
        )
    db.commit()

    students = {
        student.student_id: student for student in db.query(Student).all()
    }

    # --- admissions and placements -----------------------------------------
    for code, number in rows:
        student = students[number]
        offering = offerings[code]
        admission = AcademicAdmission(
            student_id=student.id,
            admission_intake_id=periods[code].id,
            admitted_program_id=program.id,
            admitted_program_offering_id=offering.id,
            status="ADMITTED",
            initial_status="ADMITTED",
            record_origin="MIGRATED",
            created_by_id=admin.id,
        )
        db.add(admission)
        db.flush()
        db.add(
            AcademicPlacement(
                student_id=student.id,
                admission_id=admission.id,
                academic_period_id=periods[code].id,
                program_offering_id=offering.id,
                effective_from=periods[code].start_date,
                created_by_id=admin.id,
            )
        )
    db.commit()

    # --- housing ------------------------------------------------------------
    building = Building(name=f"Rehearsal Hall {suffix}")
    db.add(building)
    db.flush()
    floor = Floor(building_id=building.id, floor_number=1)
    db.add(floor)
    db.flush()
    room = Room(floor_id=floor.id, room_number="101", capacity=len(rows))
    db.add(room)
    db.flush()
    for index in range(len(rows)):
        db.add(Bed(room_id=room.id, bed_number=index + 1))
    db.commit()

    housing_csv = io.StringIO()
    writer = csv.writer(housing_csv)
    writer.writerow(["student_id", "building", "floor", "room", "bed", "start_date"])
    for index, (_code, number) in enumerate(rows, start=1):
        writer.writerow([number, building.name, 1, "101", index, "2026-09-01"])
    parsed = housing_import.parse_rows(housing_csv.getvalue().encode(), max_rows=200)
    housing_report = housing_import.apply_housing_import(
        db, parsed, actor_id=admin.id, source_reference="rehearsal"
    )

    # --- immigration --------------------------------------------------------
    immigration_results = []
    for _code, number in rows:
        profile, conflicts, changed = import_immigration_profile(
            db,
            student_id=students[number].id,
            data={"passport_number": f"P-{number}", "visa_type": "STUDENT"},
            source_reference="rehearsal",
            actor_id=admin.id,
        )
        immigration_results.append(
            {
                "student": number,
                "conflicts": conflicts,
                "changed": changed,
                "verification_status": profile.verification_status,
            }
        )
    db.commit()

    # --- timetable ----------------------------------------------------------
    staff = db.query(Staff).first()
    if staff is None:
        teacher = db.query(User).filter(User.email == "teacher@school.portal").first()
        staff = Staff(user_id=teacher.id, first_name="Tess", last_name="Teacher")
        db.add(staff)
        db.flush()

    sections = {}
    for index, (code, _name, _start, _end, _status) in enumerate(INTAKES):
        course = Course(code=f"RH-{code}", name=f"Rehearsal {code}", program_id=program.id)
        db.add(course)
        db.flush()
        section = ClassSection(
            course_id=course.id,
            academic_period_id=periods[code].id,
            section_code="A",
        )
        classroom = Classroom(room_code=f"RH-{code}", status=ClassroomStatus.AVAILABLE)
        db.add_all([section, classroom])
        db.flush()
        db.add(
            ClassSectionProgramOffering(
                class_section_id=section.id,
                program_offering_id=offerings[code].id,
            )
        )
        db.add(TeacherAssignment(class_section_id=section.id, staff_id=staff.id))
        db.add(
            TimetableEntry(
                class_section_id=section.id,
                classroom_id=classroom.id,
                day_of_week=index % 5,
                start_time=time(9, 0),
                end_time=time(10, 0),
            )
        )
        sections[code] = section
    db.commit()

    # --- accounts and activation -------------------------------------------
    activation = {"issued": 0, "completed": 0}
    from app.auth.activation import consume_activation, issue_activation

    for _code, number in rows:
        user = students[number].user
        _record, raw = issue_activation(
            db,
            user,
            actor_id=admin.id,
            reason="MIGRATION",
            delivery="ADMIN_COUNTER",
            identity_verified=True,
            verification_reference="REHEARSAL",
            audit=False,
        )
        db.commit()
        activation["issued"] += 1

        if number.endswith("-1"):
            consume_activation(db, token=raw, password="Rehearsal1!Pass")
            db.commit()
            activation["completed"] += 1

    # --- reports ------------------------------------------------------------
    per_intake = []
    for code, name, start, end, status in INTAKES:
        reconciliation = timetable_reconciliation.reconcile_timetable(
            db, period_id=periods[code].id
        )
        placed = (
            db.query(AcademicPlacement)
            .filter(AcademicPlacement.academic_period_id == periods[code].id)
            .count()
        )
        housed = (
            db.query(HousingAssignment)
            .join(Student, Student.user_id == HousingAssignment.student_id)
            .join(AcademicPlacement, AcademicPlacement.student_id == Student.id)
            .filter(AcademicPlacement.academic_period_id == periods[code].id)
            .count()
        )
        profiles = (
            db.query(ImmigrationProfile)
            .join(Student, Student.id == ImmigrationProfile.student_id)
            .join(AcademicPlacement, AcademicPlacement.student_id == Student.id)
            .filter(AcademicPlacement.academic_period_id == periods[code].id)
            .count()
        )
        per_intake.append(
            {
                "intake": code,
                "name": name,
                "status": status,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "placed_students": placed,
                "housed_students": housed,
                "immigration_profiles": profiles,
                "timetable_sections": len(
                    [key for key in sections if key == code]
                ),
                "timetable_status": reconciliation["status"],
                "blocking_findings": reconciliation["totals"]["blocking"],
                "warnings": reconciliation["totals"]["warnings"],
                "findings": reconciliation["findings"],
            }
        )

    account_report = student_account_migration_report(db)
    overall = {
        "generated_at": datetime.now().isoformat(),
        "database": args.database_url.rsplit("/", 1)[-1],
        "intakes_planned": plan,
        "students": len(rows),
        "students_by_intake": {
            code: sum(1 for row in rows if row[0] == code) for code in periods
        },
        "housing": {
            "created": housing_report.created,
            "skipped": housing_report.skipped,
            "errors": housing_report.failed,
        },
        "immigration": {
            "profiles": len(immigration_results),
            "conflicts": sum(len(item["conflicts"]) for item in immigration_results),
            "auto_verified": sum(
                1
                for item in immigration_results
                if item["verification_status"] != "UNVERIFIED"
            ),
        },
        "activation": activation,
        "accounts": account_report["totals"],
        "per_intake": per_intake,
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "migration-rehearsal-report.json").write_text(
        json.dumps(overall, indent=2, default=str) + "\n", encoding="utf-8"
    )

    lines = [
        "# Migration rehearsal report (synthetic data)",
        "",
        f"Generated: {overall['generated_at']}",
        f"Database: `{overall['database']}` (rebuilt from scratch for this run)",
        "",
        "## Institutional totals",
        "",
        "| Measure | Count |",
        "|---|---:|",
        "| Intakes planned | 4 |",
        f"| Students | {overall['students']} |",
        f"| Housing assignments created | {overall['housing']['created']} |",
        f"| Immigration profiles | {overall['immigration']['profiles']} |",
        f"| Immigration conflicts | {overall['immigration']['conflicts']} |",
        f"| Immigration auto-verified | {overall['immigration']['auto_verified']} |",
        f"| Activation links issued | {overall['activation']['issued']} |",
        f"| Accounts activated | {overall['activation']['completed']} |",
        f"| Accounts awaiting activation | {overall['accounts']['activation_pending']} |",
        "",
        "## Per intake",
        "",
        "| Intake | Status | Students | Housed | Immigration | Timetable | Blocking | Warnings |",
        "|---|---|---:|---:|---:|---|---:|---:|",
    ]
    for item in per_intake:
        lines.append(
            f"| {item['intake']} | {item['status']} | {item['placed_students']} | "
            f"{item['housed_students']} | {item['immigration_profiles']} | "
            f"{item['timetable_status']} | {item['blocking_findings']} | {item['warnings']} |"
        )
    lines += [
        "",
        "## Unresolved findings",
        "",
    ]
    findings = [
        (item["intake"], finding)
        for item in per_intake
        for finding in item["findings"]
    ]
    if not findings:
        lines.append("None. Every intake's timetable matched its academic structure.")
    else:
        for intake, finding in findings:
            lines.append(
                f"- {intake}: `{finding['code']}` ({finding['severity']}) — "
                f"{finding['suggested_action']}"
            )
    lines += [
        "",
        "## Notes",
        "",
        "- Synthetic data only; no institutional records were used.",
        "- Accounts are created without a password and cannot sign in until the",
        "  single-use activation link is completed.",
        "- The rehearsal is repeatable: re-running the migration matches existing",
        "  records instead of duplicating them (asserted by",
        "  `tests/test_migration_rehearsal.py`).",
        "",
    ]
    (DOCS / "migration-rehearsal-report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    db.close()
    summary_keys = ("students", "housing", "immigration", "activation")
    print(json.dumps({k: overall[k] for k in summary_keys}, default=str))
    print(f"wrote {DOCS / 'migration-rehearsal-report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
