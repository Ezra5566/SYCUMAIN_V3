"""Stage 9A: database integrity and historical-record guarantees."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.session import SessionLocal
from app.models.academic import Assessment, AssessmentType, ClassSection, Course, TimetableEntry
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
    RoomStatus,
)
from app.models.identity import Role, Student, User, user_roles
from app.schemas.academic import AssessmentUpdate, TimetableEntryUpdate
from app.seed_academic import seed_academic
from app.services import academic as academic_svc
from app.services.housing import HousingRuleError, create_housing_assignment


@pytest.fixture(scope="module", autouse=True)
def academic_seed(seed_test_data):
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()


def _login(client, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200, response.text


def _student(db) -> Student:
    user = db.query(User).filter(User.email == "student@school.portal").one()
    return db.query(Student).filter(Student.user_id == user.id).one()


def _admin(db) -> User:
    return db.query(User).filter(User.email == "admin@school.portal").one()


def _bed_pair(db):
    return db.query(Bed).order_by(Bed.created_at, Bed.id).limit(2).all()


# --- Housing: database constraints ------------------------------------------------


def _housing_fixture(db, *, suffix: str):
    """Create two student users and two beds in an isolated structure."""
    role = db.query(Role).filter(Role.name == "STUDENT").one()
    users = []
    for index in (1, 2):
        user = User(
            email=f"integrity-{suffix}-{index}@example.com",
            username=f"integrity-{suffix}-{index}",
            hashed_password="x",
            full_name=f"Integrity Student {index}",
        )
        user.roles.append(role)
        db.add(user)
        users.append(user)
    building = Building(name=f"Integrity {suffix}")
    db.add(building)
    db.flush()
    floor = Floor(building_id=building.id, floor_number=1)
    db.add(floor)
    db.flush()
    room = Room(
        floor_id=floor.id,
        room_number="T1",
        capacity=2,
        status=RoomStatus.AVAILABLE,
    )
    db.add(room)
    db.flush()
    beds = [Bed(room_id=room.id, bed_number=1), Bed(room_id=room.id, bed_number=2)]
    db.add_all(beds)
    db.flush()
    return users, beds


def test_database_rejects_two_active_assignments_to_one_bed(db_session):
    users, beds = _housing_fixture(db_session, suffix=uuid.uuid4().hex[:8])
    db_session.add(
        HousingAssignment(
            student_id=users[0].id,
            bed_id=beds[0].id,
            start_date=datetime.now(UTC),
            status=HousingAssignmentStatus.ACTIVE,
        )
    )
    db_session.flush()

    db_session.add(
        HousingAssignment(
            student_id=users[1].id,
            bed_id=beds[0].id,
            start_date=datetime.now(UTC),
            status=HousingAssignmentStatus.ACTIVE,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_database_rejects_two_active_assignments_for_one_student(db_session):
    users, beds = _housing_fixture(db_session, suffix=uuid.uuid4().hex[:8])
    db_session.add(
        HousingAssignment(
            student_id=users[0].id,
            bed_id=beds[0].id,
            start_date=datetime.now(UTC),
            status=HousingAssignmentStatus.ACTIVE,
        )
    )
    db_session.flush()

    db_session.add(
        HousingAssignment(
            student_id=users[0].id,
            bed_id=beds[1].id,
            start_date=datetime.now(UTC),
            status=HousingAssignmentStatus.ACTIVE,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_concurrent_assignments_cannot_double_book_a_bed(db_session):
    """Two real connections race; one wins and the other gets a rule error."""
    engine = db_session.get_bind().engine
    session_factory = sessionmaker(bind=engine)
    suffix = uuid.uuid4().hex[:8]

    setup = session_factory()
    try:
        users, beds = _housing_fixture(setup, suffix=suffix)
        setup.commit()
        user_ids = [user.id for user in users]
        bed_id = beds[0].id
        bed_ids = [bed.id for bed in beds]
        room_id = beds[0].room_id
        room = setup.query(Room).filter(Room.id == room_id).one()
        floor_id = room.floor_id
        building_id = setup.query(Floor).filter(Floor.id == floor_id).one().building_id
    finally:
        setup.close()

    barrier = threading.Barrier(2)
    results: list[str] = []

    def attempt(user_id):
        session = session_factory()
        try:
            barrier.wait(timeout=10)
            create_housing_assignment(
                session,
                student_id=user_id,
                bed_id=bed_id,
                start_date=datetime.now(UTC),
                actor_id=user_id,
            )
            results.append("ok")
        except HousingRuleError as exc:
            results.append(exc.code)
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, user_id) for user_id in user_ids]
            for future in futures:
                future.result(timeout=20)

        assert sorted(results) == ["BED_OCCUPIED", "ok"], results

        check = session_factory()
        try:
            active = (
                check.query(HousingAssignment)
                .filter(
                    HousingAssignment.bed_id == bed_id,
                    HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
                )
                .count()
            )
            assert active == 1
        finally:
            check.close()
    finally:
        cleanup = session_factory()
        try:
            cleanup.query(HousingAssignment).filter(
                HousingAssignment.bed_id.in_(bed_ids)
            ).delete(synchronize_session=False)
            cleanup.query(Bed).filter(Bed.id.in_(bed_ids)).delete(synchronize_session=False)
            cleanup.query(Room).filter(Room.id == room_id).delete(synchronize_session=False)
            cleanup.query(Floor).filter(Floor.id == floor_id).delete(synchronize_session=False)
            cleanup.query(Building).filter(Building.id == building_id).delete(
                synchronize_session=False
            )
            cleanup.execute(
                user_roles.delete().where(user_roles.c.user_id.in_(user_ids))
            )
            cleanup.query(User).filter(User.id.in_(user_ids)).delete(
                synchronize_session=False
            )
            cleanup.commit()
        finally:
            cleanup.close()


def test_transfer_preserves_history_and_responsibility(client, db_session):
    _login(client, "admin@school.portal")
    student = _student(db_session)
    student_user = db_session.query(User).filter(User.id == student.user_id).one()
    beds = _bed_pair(db_session)
    assert len(beds) == 2

    created = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": str(student_user.id),
            "bed_id": str(beds[0].id),
            "start_date": "2026-09-01T00:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["created_by_name"] == "Admin User"

    transferred = client.post(
        f"/api/v1/housing/assignments/{first['id']}/transfer",
        json={
            "new_bed_id": str(beds[1].id),
            "transfer_date": "2026-10-01T00:00:00Z",
        },
    )
    assert transferred.status_code == 200, transferred.text
    assert transferred.json()["created_by_name"] == "Admin User"

    room_history = client.get(
        f"/api/v1/housing/rooms/{beds[0].room_id}/history"
    )
    assert room_history.status_code == 200, room_history.text
    rows = room_history.json()
    old = next(row for row in rows if row["id"] == first["id"])
    assert old["status"] == "ENDED"
    assert old["ended_by_name"] == "Admin User"
    assert old["ended_at"] is not None

    bed_history = client.get(f"/api/v1/housing/beds/{beds[0].id}/history")
    assert bed_history.status_code == 200
    assert any(row["id"] == first["id"] for row in bed_history.json())


# --- Immigration: append-only versions -------------------------------------------


def test_direct_correction_records_previous_and_new_values(client, db_session):
    _login(client, "management@school.portal")
    student = _student(db_session)
    old_number = f"OLD-{uuid.uuid4().hex[:10]}"
    new_number = f"NEW-{uuid.uuid4().hex[:10]}"

    baseline = client.patch(
        f"/api/v1/students/{student.id}/immigration",
        json={"passport_number": old_number, "change_reason": "Initial correction"},
    )
    assert baseline.status_code == 200, baseline.text

    changed = client.patch(
        f"/api/v1/students/{student.id}/immigration",
        json={"passport_number": new_number, "change_reason": "Passport reissued"},
    )
    assert changed.status_code == 200, changed.text

    history = client.get(f"/api/v1/students/{student.id}/immigration/history")
    assert history.status_code == 200, history.text
    latest = history.json()[0]
    assert latest["previous_data"]["passport_number"] == old_number
    assert latest["new_data"]["passport_number"] == new_number
    assert "passport_number" in latest["changed_fields"]
    assert latest["change_reason"] == "Passport reissued"
    assert latest["changed_by_name"] == "Management User"


def test_approved_change_request_is_linked_to_history(client, db_session):
    student = _student(db_session)
    proposed = f"VISA-{uuid.uuid4().hex[:10]}"

    _login(client, "student@school.portal")
    submitted = client.post(
        f"/api/v1/students/{student.id}/immigration/change-requests",
        json={
            "change_type": "VISA",
            "proposed_data": {"visa_number": proposed},
        },
    )
    assert submitted.status_code == 201, submitted.text
    request_id = submitted.json()["id"]

    _login(client, "management@school.portal")
    approved = client.post(f"/api/v1/immigration/change-requests/{request_id}/approve")
    assert approved.status_code == 200, approved.text

    history = client.get(f"/api/v1/students/{student.id}/immigration/history")
    assert history.status_code == 200
    linked = next(
        row for row in history.json() if row["change_request_id"] == request_id
    )
    assert linked["new_data"]["visa_number"] == proposed
    assert linked["changed_by_name"] == "Management User"
    assert linked["change_reason"].startswith("Approved VISA")


def test_immigration_history_is_denied_to_students_and_teachers(client, db_session):
    student = _student(db_session)

    _login(client, "student@school.portal")
    assert (
        client.get(f"/api/v1/students/{student.id}/immigration/history").status_code
        == 403
    )

    _login(client, "teacher@school.portal")
    assert (
        client.get(f"/api/v1/students/{student.id}/immigration/history").status_code
        == 403
    )


# --- Academic: soft deletion and assessment history ------------------------------


def test_timetable_delete_is_soft_and_hidden_by_default(db_session):
    admin = _admin(db_session)
    cs = (
        db_session.query(ClassSection)
        .join(Course)
        .filter(Course.code == "CS101")
        .first()
    )
    assert cs is not None
    entry = TimetableEntry(
        class_section_id=cs.id,
        day_of_week=6,
        start_time=time(20, 0),
        end_time=time(21, 0),
    )
    db_session.add(entry)
    db_session.commit()

    academic_svc.delete_timetable_entry(db_session, entry.id, deleted_by_id=admin.id)

    visible = academic_svc.list_timetable_entries(
        db_session, class_section_id=cs.id
    )
    assert all(row.id != entry.id for row in visible)
    retained = academic_svc.list_timetable_entries(
        db_session, class_section_id=cs.id, include_deleted=True
    )
    assert any(row.id == entry.id and row.is_deleted for row in retained)
    assert db_session.get(TimetableEntry, entry.id) is not None


def test_timetable_edit_records_previous_slot(db_session):
    admin = _admin(db_session)
    cs = (
        db_session.query(ClassSection)
        .join(Course)
        .filter(Course.code == "CS101")
        .first()
    )
    entry = TimetableEntry(
        class_section_id=cs.id,
        day_of_week=6,
        start_time=time(22, 0),
        end_time=time(23, 0),
    )
    db_session.add(entry)
    db_session.commit()

    academic_svc.update_timetable_entry(
        db_session,
        entry,
        TimetableEntryUpdate(day_of_week=5),
        actor_id=admin.id,
    )

    history = academic_svc.list_class_record_history(
        db_session, cs.id, "TIMETABLE"
    )
    assert history
    assert history[0].previous_data["day_of_week"] == 6
    assert history[0].new_data["day_of_week"] == 5
    assert history[0].changed_by_name == "Admin User"


def test_assessment_edit_records_previous_definition(db_session):
    admin = _admin(db_session)
    cs = (
        db_session.query(ClassSection)
        .join(Course)
        .filter(Course.code == "CS101")
        .first()
    )
    assessment = Assessment(
        class_section_id=cs.id,
        name=f"Integrity {uuid.uuid4().hex[:8]}",
        assessment_type=AssessmentType.ASSIGNMENT,
        max_score=100,
        weight=1,
    )
    db_session.add(assessment)
    db_session.commit()

    academic_svc.update_assessment(
        db_session,
        assessment,
        AssessmentUpdate(max_score=80),
        actor_id=admin.id,
    )

    history = academic_svc.list_class_record_history(
        db_session, cs.id, "ASSESSMENT"
    )
    assert history
    assert history[0].previous_data["max_score"] == 100
    assert history[0].new_data["max_score"] == 80
    assert history[0].changed_by_name == "Admin User"
