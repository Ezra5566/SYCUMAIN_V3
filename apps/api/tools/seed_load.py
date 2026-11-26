"""Seed a synthetic cohort for load testing.

    python tools/seed_load.py --students 1450

Runs against the isolated performance database only. It refuses any other
database name, creates no admission records and imports no institutional data.

What it creates
---------------
* ``--students`` student accounts (default 1,450), ``--teachers`` teachers and
  ``--managers`` managers, so the total registered-user population matches the
  enrolment target (~1,500).
* Enrolments spread across the demonstration catalogue, so directory, class and
  timetable reads have realistic row counts.
* Verified immigration profiles, attendance history, housing assignments and a
  small set of stored documents for document retrieval load.
* A one-seat class section and a pool of unoccupied beds for contention tests.

Output is written to ``/perf/load_seed.json`` (workspace ``.perf/`` on the
host) so the load runner does not have to guess identifiers.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, insert, text

from app.auth.service import hash_password
from app.config.settings import get_settings
from app.database.session import SessionLocal
from app.models.academic import (
    AttendanceRecord,
    AttendanceStatus,
    ClassSection,
    ClassStatus,
    Enrollment,
    EnrollmentStatus,
)
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
)
from app.models.identity import Role, Staff, Student, StudentStatus, User, user_roles
from app.models.immigration import ImmigrationProfile
from app.models.platform import (
    Document,
    DocumentReviewStatus,
    DocumentScanStatus,
    DocumentStatus,
    DocumentVisibility,
)
from app.storage import get_storage

EXPECTED_DB = "school_portal_perf"
LOAD_PASSWORD = "load-password-123!"
NATIONALITIES = (
    "China",
    "Egypt",
    "India",
    "Nigeria",
    "Mexico",
    "Brazil",
    "Japan",
    "Italy",
    "Russia",
    "Morocco",
    "Ghana",
    "Jordan",
)


def _guard_database() -> None:
    url = get_settings().DATABASE_URL
    if EXPECTED_DB not in url:
        print(
            f"ERROR: refusing to seed {url.split('@')[-1]!r}; "
            f"this tool only targets {EXPECTED_DB}.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _now() -> datetime:
    return datetime.now(UTC)


def _student_number(index: int) -> str:
    return f"LOAD-{index:05d}"


def seed(
    *,
    student_count: int,
    teacher_count: int,
    manager_count: int,
) -> dict:
    db = SessionLocal()
    try:
        # Required for the runner's slow-query report; the extension is
        # loaded via shared_preload_libraries in the performance compose file.
        db.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
        db.commit()

        roles = {r.name: r for r in db.query(Role).all()}
        for required in ("STUDENT", "TEACHER", "MANAGEMENT"):
            if required not in roles:
                print(f"ERROR: role {required} is missing; start the API once.", file=sys.stderr)
                raise SystemExit(3)

        sections = (
            db.query(ClassSection)
            .filter(ClassSection.section_code.isnot(None))
            .order_by(ClassSection.created_at)
            .all()
        )
        if len(sections) < 4:
            print(
                "ERROR: the demonstration catalogue is missing; "
                "start the API with SEED_DEMO_DATA=true first.",
                file=sys.stderr,
            )
            raise SystemExit(3)

        if db.query(Student.id).filter(Student.student_id == _student_number(1)).first():
            print("Load cohort already present; nothing to do.")
            return _summary(db, sections)

        shared_hash = hash_password(LOAD_PASSWORD)
        created_at = _now()
        users: list[dict] = []
        students: list[dict] = []
        staff_members: list[dict] = []

        def add_user(index: int, kind: str) -> dict:
            local = f"{kind}{index:05d}"
            return {
                "id": uuid.uuid4(),
                "email": f"{local}@load.test",
                "username": local,
                "hashed_password": shared_hash,
                "full_name": f"Load {kind.title()} {index:05d}",
                "is_active": True,
                "is_superuser": False,
                "must_change_password": False,
                "activation_required": False,
                "created_at": created_at,
                "updated_at": created_at,
            }

        for index in range(1, student_count + 1):
            user = add_user(index, "student")
            users.append(user)
            students.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": user["id"],
                    "student_id": _student_number(index),
                    "first_name": "Load",
                    "last_name": f"Student {index:05d}",
                    "gender": "Female" if index % 2 else "Male",
                    "nationality": NATIONALITIES[index % len(NATIONALITIES)],
                    "status": StudentStatus.ACTIVE.value,
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )

        for index in range(1, teacher_count + 1):
            user = add_user(index, "teacher")
            users.append(user)
            staff_members.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": user["id"],
                    "staff_id": f"LTEACH-{index:04d}",
                    "first_name": "Load",
                    "last_name": f"Teacher {index:04d}",
                    "department": "International College",
                    "is_active": True,
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )

        for index in range(1, manager_count + 1):
            user = add_user(index, "manager")
            users.append(user)
            staff_members.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": user["id"],
                    "staff_id": f"LMGR-{index:04d}",
                    "first_name": "Load",
                    "last_name": f"Manager {index:04d}",
                    "department": "International Office",
                    "is_active": True,
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )

        # Bulk insert in bounded batches so a failure does not hold one giant
        # transaction and the seed stays fast on a laptop.
        def flush(table, rows, size: int = 500) -> None:
            for start in range(0, len(rows), size):
                db.execute(insert(table), rows[start : start + size])
                db.commit()

        flush(User.__table__, users)
        flush(Student.__table__, students)
        flush(Staff.__table__, staff_members)

        student_role = roles["STUDENT"].id
        teacher_role = roles["TEACHER"].id
        manager_role = roles["MANAGEMENT"].id
        links = [
            {"user_id": s["user_id"], "role_id": student_role} for s in students
        ]
        links += [
            {"user_id": s["user_id"], "role_id": teacher_role}
            for s in staff_members[:teacher_count]
        ]
        links += [
            {"user_id": s["user_id"], "role_id": manager_role}
            for s in staff_members[teacher_count:]
        ]
        flush(user_roles, links)

        # Enrolments: spread across the catalogue so class and timetable reads
        # return realistic volumes instead of empty collections.
        load_sections = sections[: min(5, len(sections))]
        for section in load_sections:
            section.capacity = max(section.capacity or 0, 500)
        enrol_rows = []
        for index, student in enumerate(students):
            section = load_sections[index % len(load_sections)]
            enrol_rows.append(
                {
                    "id": uuid.uuid4(),
                    "student_id": student["id"],
                    "class_section_id": section.id,
                    "status": EnrollmentStatus.ENROLLED.value,
                    "enrolled_at": created_at,
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )
        flush(Enrollment.__table__, enrol_rows)
        db.execute(
            text(
                "UPDATE class_sections cs SET enrolled_count = ("
                "  SELECT count(*) FROM enrollments e"
                "  WHERE e.class_section_id = cs.id AND e.status = 'ENROLLED')"
            )
        )
        db.commit()

        profiles = [
            {
                "id": uuid.uuid4(),
                "student_id": student["id"],
                "passport_number": f"P{index:08d}",
                "passport_issuing_country": student["nationality"],
                "passport_issue_date": date(2024, 1, 1),
                "passport_expiry_date": date(2029, 1, 1),
                "visa_type": "STUDENT",
                "visa_number": f"V{index:08d}",
                "visa_expiry_date": date(2027, 9, 1),
                "data_source": "INSTITUTIONAL",
                "verification_status": "VERIFIED",
                "created_at": created_at,
                "updated_at": created_at,
            }
            for index, student in enumerate(students, start=1)
        ]
        flush(ImmigrationProfile.__table__, profiles)

        # Attendance history for the first section: eight sessions, all its
        # enrolled students. The unique key makes a re-run a no-op.
        teacher_user = staff_members[0]["user_id"] if staff_members else users[0]["id"]
        first_section = load_sections[0]
        roster = [
            row["student_id"]
            for row in enrol_rows
            if row["class_section_id"] == first_section.id
        ][:220]
        attendance_rows = []
        for day in range(8):
            session_date = date(2026, 9, 1) + timedelta(days=day * 7)
            for position, student_id in enumerate(roster):
                attendance_rows.append(
                    {
                        "id": uuid.uuid4(),
                        "student_id": student_id,
                        "class_section_id": first_section.id,
                        "session_date": session_date,
                        "status": (
                            AttendanceStatus.PRESENT.value
                            if (position + day) % 11
                            else AttendanceStatus.ABSENT.value
                        ),
                        "recorded_by": teacher_user,
                        "created_at": created_at,
                        "updated_at": created_at,
                    }
                )
        flush(AttendanceRecord.__table__, attendance_rows)

        # Housing: 300 occupied beds plus 100 genuinely free ones.
        building = db.query(Building).filter(Building.name == "LOAD-HALL").first()
        if building is None:
            building = Building(name="LOAD-HALL", description="Synthetic load-test hall")
            db.add(building)
            db.flush()
            floor = Floor(building_id=building.id, floor_number=1)
            db.add(floor)
            db.flush()
            for room_index in range(1, 101):
                room = Room(
                    floor_id=floor.id,
                    room_number=f"L{room_index:03d}",
                    capacity=4,
                    status="AVAILABLE",
                )
                db.add(room)
                db.flush()
                for bed_index in range(1, 5):
                    db.add(Bed(room_id=room.id, bed_number=bed_index, is_active=True))
            db.commit()

        beds = (
            db.query(Bed)
            .join(Room, Room.id == Bed.room_id)
            .join(Floor, Floor.id == Room.floor_id)
            .join(Building, Building.id == Floor.building_id)
            .filter(Building.name == "LOAD-HALL")
            .order_by(Bed.created_at, Bed.bed_number)
            .all()
        )
        existing_assignments = {
            row.bed_id
            for row in db.query(HousingAssignment)
            .filter(HousingAssignment.status == HousingAssignmentStatus.ACTIVE.value)
            .all()
        }
        free_beds = [bed for bed in beds if bed.id not in existing_assignments]
        assignable = free_beds[:300]
        free_beds = free_beds[300:]
        # Housing is keyed on the *account* id (users.id), unlike academic and
        # immigration endpoints, which take the student-record id. That is the
        # existing contract and the service validates the STUDENT role.
        assignment_rows = [
            {
                "id": uuid.uuid4(),
                "student_id": students[index]["user_id"],
                "bed_id": bed.id,
                "start_date": created_at,
                "status": HousingAssignmentStatus.ACTIVE.value,
                "created_at": created_at,
                "updated_at": created_at,
            }
            for index, bed in enumerate(assignable)
        ]
        flush(HousingAssignment.__table__, assignment_rows)

        # A one-seat section for the capacity contention test.
        contention = (
            db.query(ClassSection)
            .filter(ClassSection.section_code == "LOAD-CONTENTION")
            .first()
        )
        if contention is None:
            template = load_sections[0]
            contention = ClassSection(
                course_id=template.course_id,
                academic_period_id=template.academic_period_id,
                section_code="LOAD-CONTENTION",
                capacity=1,
                enrolled_count=0,
                status=ClassStatus.ACTIVE,
            )
            db.add(contention)
            db.commit()

        # Stored documents: bytes really exist, so download load exercises
        # storage rather than a database-only path.
        storage = get_storage()
        document_rows = []
        for index in range(30):
            key = f"load/documents/{uuid.uuid4().hex}.pdf"
            payload = (
                b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
                b"trailer<</Root 1 0 R>>\n%%EOF\n"
            )
            storage.save(key, payload, "application/pdf")
            document_rows.append(
                {
                    "id": uuid.uuid4(),
                    "student_id": students[index]["id"],
                    "uploaded_by": teacher_user,
                    "document_type": "PASSPORT",
                    "title": f"Load document {index:03d}",
                    "storage_provider": storage.name,
                    "object_key": key,
                    "original_filename": f"load-{index:03d}.pdf",
                    "content_type": "application/pdf",
                    "file_size": len(payload),
                    "checksum_sha256": __import__("hashlib").sha256(payload).hexdigest(),
                    "visibility": DocumentVisibility.STAFF_ONLY.value,
                    "status": DocumentStatus.ACTIVE.value,
                    "review_status": DocumentReviewStatus.APPROVED.value,
                    "scan_status": DocumentScanStatus.CLEAN.value,
                    "is_required": False,
                    "scan_engine": "seed-fixture",
                    "scanned_at": created_at,
                    "created_at": created_at,
                    "updated_at": created_at,
                }
            )
        flush(Document.__table__, document_rows)
        db.commit()

        payload = {
            "generated_at": _now().isoformat(),
            "password": LOAD_PASSWORD,
            "admin": {"email": "admin@school.portal", "password": "password123"},
            "teacher": {
                "email": "teacher00001@load.test",
                "password": LOAD_PASSWORD,
            },
            "counts": {
                "users": len(users) + 4,
                "students": len(students),
                "teachers": teacher_count,
                "managers": manager_count,
                "sections": len(sections),
                "enrolments": len(enrol_rows),
                "attendance": len(attendance_rows),
                "documents": len(document_rows),
                "beds_free": len(free_beds),
            },
            "students": [
                {
                    "user_id": str(student["user_id"]),
                    "student_id": str(student["id"]),
                    "number": student["student_id"],
                    "email": f"student{index:05d}@load.test",
                }
                for index, student in enumerate(students[:420], start=1)
            ],
            "sections": [str(section.id) for section in load_sections],
            "contention_section": str(contention.id),
            "free_beds": [str(bed.id) for bed in free_beds[:40]],
            "documents": [
                {"id": str(row["id"]), "student_id": str(row["student_id"])}
                for row in document_rows
            ],
            "immigration_student_ids": [str(s["id"]) for s in students[400:420]],
            "housed_user_ids": [str(s["user_id"]) for s in students[:300]],
        }
        out = "/perf/load_seed.json"
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        print(json.dumps({"ok": True, "output": out, "counts": payload["counts"]}, indent=2))
        return payload
    finally:
        db.close()


def _summary(db, sections) -> dict:
    counts = {
        "students": db.query(func.count(Student.id)).scalar(),
        "users": db.query(func.count(User.id)).scalar(),
        "sections": len(sections),
    }
    print(json.dumps({"ok": True, "already_seeded": True, "counts": counts}, indent=2))
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--students", type=int, default=1450)
    parser.add_argument("--teachers", type=int, default=45)
    parser.add_argument("--managers", type=int, default=5)
    args = parser.parse_args(argv)
    _guard_database()
    seed(
        student_count=args.students,
        teacher_count=args.teachers,
        manager_count=args.managers,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
