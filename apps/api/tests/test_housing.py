"""Tests for housing API and seed data."""

import uuid

from app.models.housing import (
    Bed,
    Building,
    Floor,
    Room,
)
from app.models.identity import Student
from app.seed import seed_roles_and_permissions, seed_test_users
from app.seed_housing import seed_housing

# --- Helper Functions ---


def login_as(client, email, password="password123"):
    """Login and return the response."""
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


# --- Seed Tests ---


def test_housing_seed_creates_buildings(db_session):
    """Test that housing seed creates 8 buildings."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)
    seed_housing(db_session)

    buildings = db_session.query(Building).all()
    assert len(buildings) == 8

    building_names = {b.name for b in buildings}
    for num in ["18", "19", "20", "21", "22", "23", "24", "25"]:
        assert f"Building {num}" in building_names


def test_housing_seed_creates_floors(db_session):
    """Test that each building has 5 floors."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)
    seed_housing(db_session)

    buildings = db_session.query(Building).all()
    for building in buildings:
        floors = db_session.query(Floor).filter(Floor.building_id == building.id).all()
        assert len(floors) == 5


def test_housing_seed_creates_rooms(db_session):
    """Test that each building has 38 rooms."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)
    seed_housing(db_session)

    buildings = db_session.query(Building).all()
    for building in buildings:
        floors = db_session.query(Floor).filter(Floor.building_id == building.id).all()
        total_rooms = 0
        for floor in floors:
            rooms = db_session.query(Room).filter(Room.floor_id == floor.id).all()
            if floor.floor_number <= 4:
                assert len(rooms) == 8
                total_rooms += 8
            else:
                assert len(rooms) == 6
                total_rooms += 6
        assert total_rooms == 38


def test_housing_seed_creates_correct_room_numbers(db_session):
    """Test that room numbers follow SCU convention."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)
    seed_housing(db_session)

    building = db_session.query(Building).first()
    floors = (
        db_session.query(Floor)
        .filter(Floor.building_id == building.id)
        .order_by(Floor.floor_number)
        .all()
    )

    # Floor 1: 101-108
    floor1_rooms = db_session.query(Room).filter(Room.floor_id == floors[0].id).all()
    floor1_numbers = sorted([r.room_number for r in floor1_rooms])
    assert floor1_numbers == ["101", "102", "103", "104", "105", "106", "107", "108"]

    # Floor 5: 501-506
    floor5_rooms = db_session.query(Room).filter(Room.floor_id == floors[4].id).all()
    floor5_numbers = sorted([r.room_number for r in floor5_rooms])
    assert floor5_numbers == ["501", "502", "503", "504", "505", "506"]


def test_housing_seed_creates_beds(db_session):
    """Test that each room has 4 beds."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)
    seed_housing(db_session)

    rooms = db_session.query(Room).all()
    for room in rooms:
        beds = db_session.query(Bed).filter(Bed.room_id == room.id).all()
        assert len(beds) == 4


def test_housing_seed_is_idempotent(db_session):
    """Test that running seed multiple times doesn't create duplicates."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)
    seed_housing(db_session)

    count1 = db_session.query(Building).count()

    seed_housing(db_session)
    seed_housing(db_session)

    count2 = db_session.query(Building).count()
    assert count1 == count2


def test_total_rooms_across_all_buildings(db_session):
    """Test that there are 304 rooms total across 8 buildings."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)
    seed_housing(db_session)

    total_rooms = db_session.query(Room).count()
    assert total_rooms == 304  # 8 buildings × 38 rooms


# --- API Tests ---


def test_list_buildings(client):
    """Test listing buildings."""
    login_as(client, "admin@school.portal")
    response = client.get("/api/v1/housing/buildings")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 8


def test_get_building(client):
    """Test getting building details."""
    login_as(client, "admin@school.portal")

    # Get building ID
    buildings_response = client.get("/api/v1/housing/buildings")
    building_id = buildings_response.json()[0]["id"]

    response = client.get(f"/api/v1/housing/buildings/{building_id}")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "floor_count" in data
    assert data["floor_count"] == 5


def test_get_building_floors(client):
    """Test getting floors for a building via building detail."""
    login_as(client, "admin@school.portal")

    buildings_response = client.get("/api/v1/housing/buildings")
    building_id = buildings_response.json()[0]["id"]

    response = client.get(f"/api/v1/housing/buildings/{building_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data["floors"]) == 5


def test_get_floor_rooms(client):
    """Test getting rooms for a floor."""
    login_as(client, "admin@school.portal")

    # Get a floor ID from building detail
    buildings_response = client.get("/api/v1/housing/buildings")
    building_id = buildings_response.json()[0]["id"]
    building_response = client.get(f"/api/v1/housing/buildings/{building_id}")
    floor_id = building_response.json()["floors"][0]["id"]

    response = client.get(f"/api/v1/housing/floors/{floor_id}/rooms")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert "room_number" in data[0]
    assert "capacity" in data[0]
    assert "occupancy_status" in data[0]


def test_get_room(client):
    """Test getting room details with beds."""
    login_as(client, "admin@school.portal")

    # Get a room ID from building detail
    buildings_response = client.get("/api/v1/housing/buildings")
    building_id = buildings_response.json()[0]["id"]
    building_response = client.get(f"/api/v1/housing/buildings/{building_id}")
    floor_id = building_response.json()["floors"][0]["id"]
    rooms_response = client.get(f"/api/v1/housing/floors/{floor_id}/rooms")
    room_id = rooms_response.json()[0]["id"]

    response = client.get(f"/api/v1/housing/rooms/{room_id}")
    assert response.status_code == 200
    data = response.json()
    assert "beds" in data
    assert len(data["beds"]) == 4
    assert "building_name" in data
    assert "floor_number" in data


def test_housing_overview(client):
    """Test housing overview endpoint."""
    login_as(client, "admin@school.portal")
    response = client.get("/api/v1/housing/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["total_buildings"] == 8
    assert data["total_rooms"] == 304
    assert data["total_beds"] == 1216  # 304 rooms × 4 beds


def test_student_housing_no_assignment(client):
    """Test student housing when no assignment exists."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        student = db.query(StudentModel).first()
        if student:
            response = client.get(f"/api/v1/housing/students/{student.id}/housing")
            assert response.status_code == 200
            data = response.json()
            assert data["has_assignment"] is False
    finally:
        db.close()


def test_student_housing_own_only(client):
    """Test student can only view their own housing."""
    login_as(client, "student@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        # Get an admin's staff record - this student doesn't exist
        # so it should return 404
        student = db.query(StudentModel).first()
        if student:
            # Create a UUID that doesn't match any student
            import uuid
            fake_id = uuid.uuid4()
            response = client.get(f"/api/v1/housing/students/{fake_id}/housing")
            assert response.status_code == 404
    finally:
        db.close()


# --- Assignment Tests ---


def test_create_assignment(client):
    """Test creating a housing assignment."""
    login_as(client, "admin@school.portal")

    # Get a student and a bed
    from app.database.session import SessionLocal
    from app.models.housing import Bed as BedModel
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        student = db.query(UserModel).filter(
            UserModel.email == "student@school.portal"
        ).first()
        bed = db.query(BedModel).first()
        if student and bed:
            response = client.post(
                "/api/v1/housing/assignments",
                json={
                    "student_id": str(student.id),
                    "bed_id": str(bed.id),
                    "start_date": "2026-09-01T00:00:00Z",
                },
            )
            assert response.status_code == 201
            data = response.json()
            assert data["status"] == "ACTIVE"
            assert data["student_id"] == str(student.id)

            # The room response must distinguish the login account id from the
            # student-record id used by the profile route. Returning only the
            # former is what produced "Student could not be found".
            room = db.query(BedModel).filter(BedModel.id == bed.id).first()
            assert room is not None
            detail = client.get(f"/api/v1/housing/rooms/{room.room_id}")
            assert detail.status_code == 200, detail.text
            bed_row = next(
                item for item in detail.json()["beds"] if item["id"] == str(bed.id)
            )
            record = (
                db.query(Student)
                .filter(Student.user_id == student.id)
                .first()
            )
            assert record is not None
            assert bed_row["student_record_id"] == str(record.id)
            assert bed_row["student_id"] == str(student.id)
    finally:
        db.close()


def _second_student_user_id(client):
    """Create a second STUDENT account and return its user id.

    Occupant ids are validated, so a fabricated UUID can no longer stand in for
    a real second student — doing so returns 404 before the bed is even
    examined, which would make the occupied-bed assertion meaningless.
    """
    unique = uuid.uuid4().hex[:8]
    created = client.post(
        "/api/v1/users/",
        json={
            "email": f"occupancy-{unique}@example.com",
            "full_name": "Occupancy Check",
            "roles": ["STUDENT"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["account"]["id"]


def test_assign_occupied_bed_rejected(client):
    """Test that assigning an occupied bed is rejected."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.housing import Bed as BedModel
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        student = db.query(UserModel).filter(
            UserModel.email == "student@school.portal"
        ).first()
        bed = db.query(BedModel).first()
        assert student is not None and bed is not None
    finally:
        db.close()

    # First assignment
    first = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": str(student.id),
            "bed_id": str(bed.id),
            "start_date": "2026-09-01T00:00:00Z",
        },
    )
    assert first.status_code == 201, first.text

    # A different, real student must be refused that bed.
    response = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": _second_student_user_id(client),
            "bed_id": str(bed.id),
            "start_date": "2026-09-01T00:00:00Z",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BED_OCCUPIED"


def test_student_two_active_assignments_rejected(client):
    """Test that a student cannot have two active assignments."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.housing import Bed as BedModel
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        student = db.query(UserModel).filter(
            UserModel.email == "student@school.portal"
        ).first()
        beds = db.query(BedModel).limit(2).all()
        if student and len(beds) >= 2:
            # First assignment
            client.post(
                "/api/v1/housing/assignments",
                json={
                    "student_id": str(student.id),
                    "bed_id": str(beds[0].id),
                    "start_date": "2026-09-01T00:00:00Z",
                },
            )
            # Second assignment should fail
            response = client.post(
                "/api/v1/housing/assignments",
                json={
                    "student_id": str(student.id),
                    "bed_id": str(beds[1].id),
                    "start_date": "2026-09-01T00:00:00Z",
                },
            )
            assert response.status_code == 409
    finally:
        db.close()


def test_transfer_student(client):
    """Test transferring a student to a new bed."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.housing import Bed as BedModel
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        student = db.query(UserModel).filter(
            UserModel.email == "student@school.portal"
        ).first()
        beds = db.query(BedModel).limit(2).all()
        if student and len(beds) >= 2:
            # Create first assignment
            create_response = client.post(
                "/api/v1/housing/assignments",
                json={
                    "student_id": str(student.id),
                    "bed_id": str(beds[0].id),
                    "start_date": "2026-09-01T00:00:00Z",
                },
            )
            assignment_id = create_response.json()["id"]

            # Transfer
            response = client.post(
                f"/api/v1/housing/assignments/{assignment_id}/transfer",
                json={
                    "new_bed_id": str(beds[1].id),
                    "transfer_date": "2026-10-01T00:00:00Z",
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ACTIVE"
            assert data["bed_id"] == str(beds[1].id)

            # Verify student can't be assigned to old bed anymore
            # (old assignment should be ended)
            client.get(f"/api/v1/housing/rooms/{beds[0].room_id}")
            # The old bed should still show as available now
    finally:
        db.close()


def test_end_assignment(client):
    """Test ending a housing assignment."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.housing import Bed as BedModel
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        student = db.query(UserModel).filter(
            UserModel.email == "student@school.portal"
        ).first()
        bed = db.query(BedModel).first()
        if student and bed:
            # Create assignment
            create_response = client.post(
                "/api/v1/housing/assignments",
                json={
                    "student_id": str(student.id),
                    "bed_id": str(bed.id),
                    "start_date": "2026-09-01T00:00:00Z",
                },
            )
            assignment_id = create_response.json()["id"]

            # End assignment
            response = client.post(
                f"/api/v1/housing/assignments/{assignment_id}/end",
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ENDED"
    finally:
        db.close()


# --- Authorization Tests ---


def test_student_cannot_access_housing_admin(client):
    """Test that students cannot access housing administration."""
    login_as(client, "student@school.portal")
    response = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": str(uuid.uuid4()),
            "bed_id": str(uuid.uuid4()),
            "start_date": "2026-09-01T00:00:00Z",
        },
    )
    assert response.status_code == 403


def test_teacher_cannot_access_housing_admin(client):
    """Test that teachers cannot access housing administration."""
    login_as(client, "teacher@school.portal")
    response = client.post(
        "/api/v1/housing/assignments",
        json={
            "student_id": str(uuid.uuid4()),
            "bed_id": str(uuid.uuid4()),
            "start_date": "2026-09-01T00:00:00Z",
        },
    )
    assert response.status_code == 403


def test_management_can_access_housing(client):
    """Test that management can access housing."""
    login_as(client, "management@school.portal")
    response = client.get("/api/v1/housing/buildings")
    assert response.status_code == 200
