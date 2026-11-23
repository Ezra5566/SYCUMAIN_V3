"""Housing structure administration.

The dormitory used to be seed-only: buildings, floors, rooms and beds could be
visualised but never changed, so a new building or a room that lost a bed meant
editing the database by hand. These tests cover the administrative endpoints
that made the structure configurable, and the invariants that keep the read
paths honest:

* capacity always equals the beds in service, in both directions
* capacity cannot be reduced below the number of occupied beds
* an occupied bed cannot be retired
* a capacity or bed edit is refused, not silently destructive
"""

import uuid

from app.database.session import SessionLocal
from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
    RoomStatus,
)
from app.models.identity import User

API = "/api/v1"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"
TEACHER = "teacher@school.portal"
STUDENT = "student@school.portal"


def _login(client, email=ADMIN):
    resp = client.post(f"{API}/auth/login", json={"email": email, "password": "password123"})
    assert resp.status_code == 200, resp.text
    return resp


def _error_code(response) -> str:
    return response.json()["error"]["code"]


def _new_building(client, name=None):
    """Create a building with an unused name, returning its id."""
    name = name or f"T-{uuid.uuid4().hex[:8]}"
    resp = client.post(f"{API}/housing/buildings", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _new_room(client, building_id, capacity=4, room_number=None):
    """Create a floor + room, returning (floor_id, room_id)."""
    floor = client.post(
        f"{API}/housing/buildings/{building_id}/floors",
        json={"floor_number": 1},
    )
    assert floor.status_code == 201, floor.text
    floor_id = floor.json()["floors"][0]["id"]

    room = client.post(
        f"{API}/housing/floors/{floor_id}/rooms",
        json={"room_number": room_number or uuid.uuid4().hex[:4], "capacity": capacity},
    )
    assert room.status_code == 201, room.text
    return floor_id, room.json()["id"]


def _room(client, room_id) -> dict:
    resp = client.get(f"{API}/housing/rooms/{room_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def _student_user_id(email=STUDENT) -> str:
    db = SessionLocal()
    try:
        return str(db.query(User).filter(User.email == email).first().id)
    finally:
        db.close()


def _assign(client, student_id: str, bed_id: str):
    return client.post(
        f"{API}/housing/assignments",
        json={
            "student_id": student_id,
            "bed_id": bed_id,
            "start_date": "2026-09-01T00:00:00Z",
        },
    )


def _second_student(client) -> str:
    """A second STUDENT account, returning its user id.

    A student may hold only one active assignment, so testing "capacity below
    occupancy" needs more than one occupant.
    """
    unique = uuid.uuid4().hex[:8]
    created = client.post(
        f"{API}/users",
        json={
            "email": f"structure-{unique}@example.com",
            "full_name": "Structure Check",
            "roles": ["STUDENT"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["account"]["id"]


class TestBuildingAdministration:
    def test_building_can_be_created_and_edited(self, client):
        _login(client)
        name = f"T-{uuid.uuid4().hex[:8]}"
        building_id = _new_building(client, name)

        # It is immediately part of the estate the directory reads.
        listed = client.get(f"{API}/housing/buildings").json()
        assert any(b["id"] == building_id for b in listed)

        renamed = client.patch(
            f"{API}/housing/buildings/{building_id}",
            json={"name": f"{name}-B", "description": "Added by a test"},
        )
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["name"] == f"{name}-B"
        assert renamed.json()["description"] == "Added by a test"

    def test_duplicate_building_name_is_a_clean_conflict(self, client):
        _login(client)
        name = f"T-{uuid.uuid4().hex[:8]}"
        _new_building(client, name)

        again = client.post(f"{API}/housing/buildings", json={"name": name.upper()})
        assert again.status_code == 409
        assert _error_code(again) == "BUILDING_NAME_TAKEN"

    def test_unknown_building_is_404(self, client):
        _login(client)
        resp = client.patch(
            f"{API}/housing/buildings/{uuid.uuid4()}", json={"name": "Nope"}
        )
        assert resp.status_code == 404
        assert _error_code(resp) == "BUILDING_NOT_FOUND"

    def test_archiving_a_building_uses_is_active(self, client):
        """Institutional structures are archived, never deleted."""
        _login(client)
        building_id = _new_building(client)

        archived = client.patch(
            f"{API}/housing/buildings/{building_id}", json={"is_active": False}
        )
        assert archived.status_code == 200
        assert archived.json()["is_active"] is False

        # Archived buildings drop out of the active list rather than vanishing.
        active = client.get(f"{API}/housing/buildings").json()
        assert all(b["id"] != building_id for b in active)


class TestFloorAdministration:
    def test_floor_can_be_added_and_renumbered(self, client):
        _login(client)
        building_id = _new_building(client)

        created = client.post(
            f"{API}/housing/buildings/{building_id}/floors", json={"floor_number": 7}
        )
        assert created.status_code == 201, created.text
        floors = created.json()["floors"]
        assert [f["floor_number"] for f in floors] == [7]

        floor_id = floors[0]["id"]
        moved = client.patch(
            f"{API}/housing/floors/{floor_id}", json={"floor_number": 8}
        )
        assert moved.status_code == 200
        assert [f["floor_number"] for f in moved.json()["floors"]] == [8]

    def test_duplicate_floor_number_is_refused(self, client):
        _login(client)
        building_id = _new_building(client)
        first = client.post(
            f"{API}/housing/buildings/{building_id}/floors", json={"floor_number": 3}
        )
        assert first.status_code == 201

        again = client.post(
            f"{API}/housing/buildings/{building_id}/floors", json={"floor_number": 3}
        )
        assert again.status_code == 409
        assert _error_code(again) == "FLOOR_NUMBER_TAKEN"

    def test_floor_number_is_validated(self, client):
        _login(client)
        building_id = _new_building(client)
        resp = client.post(
            f"{API}/housing/buildings/{building_id}/floors", json={"floor_number": 9999}
        )
        assert resp.status_code == 422


class TestRoomAndBedAdministration:
    def test_room_is_created_with_its_beds(self, client):
        """Capacity is not just a number: the beds exist to match it."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=6)

        room = _room(client, room_id)
        assert room["capacity"] == 6
        assert len(room["beds"]) == 6
        assert room["available"] == 6
        assert room["occupancy_status"] == "AVAILABLE"

    def test_capacity_zero_is_a_room_with_no_beds(self, client):
        """Not every room is a dormitory room; a zero-capacity room is legal."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=0)

        room = _room(client, room_id)
        assert room["capacity"] == 0
        assert room["beds"] == []

    def test_duplicate_room_number_on_one_floor_is_refused(self, client):
        _login(client)
        building_id = _new_building(client)
        floor_id, _ = _new_room(client, building_id, room_number="101")

        again = client.post(
            f"{API}/housing/floors/{floor_id}/rooms",
            json={"room_number": "101", "capacity": 2},
        )
        assert again.status_code == 409
        assert _error_code(again) == "ROOM_NUMBER_TAKEN"

    def test_raising_capacity_adds_the_missing_beds(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)

        raised = client.patch(
            f"{API}/housing/rooms/{room_id}", json={"capacity": 5}
        )
        assert raised.status_code == 200, raised.text
        assert raised.json()["capacity"] == 5
        assert len(raised.json()["beds"]) == 5

        # Numbering must stay unique and dense.
        numbers = sorted(b["bed_number"] for b in raised.json()["beds"])
        assert numbers == [1, 2, 3, 4, 5]

    def test_lowering_capacity_retires_the_highest_empty_beds(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=4)

        lowered = client.patch(f"{API}/housing/rooms/{room_id}", json={"capacity": 2})
        assert lowered.status_code == 200, lowered.text
        assert lowered.json()["capacity"] == 2
        assert [b["bed_number"] for b in lowered.json()["beds"]] == [1, 2]

    def test_capacity_cannot_drop_below_occupancy(self, client):
        """The rule that stops a capacity edit evicting a student."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=3)

        room = _room(client, room_id)
        assert _assign(client, _student_user_id(), room["beds"][0]["id"]).status_code == 201
        assert (
            _assign(client, _second_student(client), room["beds"][1]["id"]).status_code
            == 201
        )

        resp = client.patch(f"{API}/housing/rooms/{room_id}", json={"capacity": 1})
        assert resp.status_code == 409
        assert _error_code(resp) == "ROOM_CAPACITY_EXCEEDED"

        # Both students are still in their beds and the room is unchanged.
        after = _room(client, room_id)
        assert after["capacity"] == 3
        assert after["occupied"] == 2
        assert sum(1 for b in after["beds"] if b["is_occupied"]) == 2

    def test_capacity_equal_to_occupancy_does_not_evict(self, client):
        """Capacity may shrink to the occupancy count: that evicts nobody."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=4)

        room = _room(client, room_id)
        kept_bed = room["beds"][0]["id"]
        assert _assign(client, _student_user_id(), kept_bed).status_code == 201

        shrunk = client.patch(f"{API}/housing/rooms/{room_id}", json={"capacity": 1})
        assert shrunk.status_code == 200, shrunk.text
        assert shrunk.json()["capacity"] == 1
        assert shrunk.json()["occupied"] == 1
        assert [b["id"] for b in shrunk.json()["beds"]] == [kept_bed]

    def test_reducing_around_an_occupant_keeps_them_in_place(self, client):
        """Bed 1 stays even when capacity drops — beds are retired by number."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=4)

        room = _room(client, room_id)
        first_bed = room["beds"][0]["id"]
        assert _assign(client, _student_user_id(), first_bed).status_code == 201

        lowered = client.patch(f"{API}/housing/rooms/{room_id}", json={"capacity": 3})
        assert lowered.status_code == 200, lowered.text
        assert lowered.json()["capacity"] == 3
        assert sorted(b["bed_number"] for b in lowered.json()["beds"]) == [1, 2, 3]

    def test_bed_can_be_added_and_the_capacity_follows(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=1)

        added = client.post(
            f"{API}/housing/rooms/{room_id}/beds", json={"label": "Window bed"}
        )
        assert added.status_code == 201, added.text
        assert added.json()["capacity"] == 2
        assert [b["label"] for b in added.json()["beds"]].count("Window bed") == 1

    def test_retiring_an_empty_bed_lowers_capacity(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=3)

        room = _room(client, room_id)
        bed_id = room["beds"][-1]["id"]

        retired = client.patch(f"{API}/housing/beds/{bed_id}", json={"is_active": False})
        assert retired.status_code == 200, retired.text
        assert retired.json()["capacity"] == 2

    def test_retiring_an_occupied_bed_is_refused(self, client):
        """Otherwise a student would be left in a bed that no longer exists."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)

        room = _room(client, room_id)
        bed_id = room["beds"][0]["id"]
        assert _assign(client, _student_user_id(), bed_id).status_code == 201

        resp = client.patch(f"{API}/housing/beds/{bed_id}", json={"is_active": False})
        assert resp.status_code == 409
        assert _error_code(resp) == "BED_OCCUPIED"

        after = _room(client, room_id)
        assert after["capacity"] == 2
        assert sum(1 for b in after["beds"] if b["is_occupied"]) == 1

    def test_bed_label_can_be_changed(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=1)

        room = _room(client, room_id)
        bed_id = room["beds"][0]["id"]

        renamed = client.patch(f"{API}/housing/beds/{bed_id}", json={"label": "Desk bed"})
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["beds"][0]["label"] == "Desk bed"

    def test_reinstating_a_retired_bed_number_reuses_the_row(self, client):
        """Adding back bed 2 must not collide with the retired record."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)

        room = _room(client, room_id)
        retired_bed = room["beds"][1]["id"]
        assert (
            client.patch(f"{API}/housing/beds/{retired_bed}", json={"is_active": False}).status_code
            == 200
        )

        reinstated = client.post(
            f"{API}/housing/rooms/{room_id}/beds", json={"bed_number": 2}
        )
        assert reinstated.status_code == 201, reinstated.text
        assert reinstated.json()["capacity"] == 2
        assert [b["id"] for b in reinstated.json()["beds"]].count(retired_bed) == 1


class TestActiveBedDisplayNumbering:
    """Display numbers stay dense without rewriting permanent bed identity."""

    def test_retiring_the_first_bed_renumbers_the_rest(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=3)
        room = _room(client, room_id)

        retired = client.patch(
            f"{API}/housing/beds/{room['beds'][0]['id']}",
            json={"is_active": False},
        )
        assert retired.status_code == 200, retired.text
        assert [bed["display_number"] for bed in retired.json()["beds"]] == [1, 2]
        assert [bed["bed_number"] for bed in retired.json()["beds"]] == [2, 3]

    def test_retiring_a_middle_bed_renumbers_without_changing_ids(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=3)
        room = _room(client, room_id)
        middle = room["beds"][1]

        retired = client.patch(
            f"{API}/housing/beds/{middle['id']}", json={"is_active": False}
        )
        assert retired.status_code == 200, retired.text
        assert [bed["display_number"] for bed in retired.json()["beds"]] == [1, 2]
        assert [bed["bed_number"] for bed in retired.json()["beds"]] == [1, 3]
        assert [bed["id"] for bed in retired.json()["beds"]] == [
            room["beds"][0]["id"],
            room["beds"][2]["id"],
        ]

    def test_a_new_bed_appends_after_the_active_beds(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=3)
        room = _room(client, room_id)

        client.patch(
            f"{API}/housing/beds/{room['beds'][0]['id']}",
            json={"is_active": False},
        )
        added = client.post(f"{API}/housing/rooms/{room_id}/beds", json={})
        assert added.status_code == 201, added.text
        assert [bed["display_number"] for bed in added.json()["beds"]] == [1, 2, 3]
        assert [bed["bed_number"] for bed in added.json()["beds"]] == [2, 3, 4]

    def test_history_keeps_the_permanent_bed_number(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=3)
        room = _room(client, room_id)
        occupied = room["beds"][1]
        assert _assign(client, _student_user_id(), occupied["id"]).status_code == 201

        client.patch(
            f"{API}/housing/beds/{room['beds'][0]['id']}",
            json={"is_active": False},
        )
        after = _room(client, room_id)
        occupant = next(bed for bed in after["beds"] if bed["id"] == occupied["id"])
        assert occupant["display_number"] == 1
        assert occupant["bed_number"] == occupied["bed_number"]

        history = client.get(f"{API}/housing/beds/{occupied['id']}/history")
        assert history.status_code == 200, history.text
        assert any(row["bed_id"] == occupied["id"] for row in history.json())


class TestRoomOperationalStatus:
    def test_status_change_is_reported_in_occupancy(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)

        changed = client.patch(
            f"{API}/housing/rooms/{room_id}", json={"status": "OUT_OF_SERVICE"}
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["status"] == RoomStatus.OUT_OF_SERVICE
        assert changed.json()["occupancy_status"] == "OUT_OF_SERVICE"

        reserved = client.patch(f"{API}/housing/rooms/{room_id}", json={"status": "RESERVED"})
        assert reserved.json()["occupancy_status"] == "RESERVED"

    def test_an_unknown_status_is_rejected(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=1)

        resp = client.patch(f"{API}/housing/rooms/{room_id}", json={"status": "BROKEN"})
        assert resp.status_code == 422


class TestStructureAuthorization:
    def test_management_can_administer_the_structure(self, client):
        _login(client, MANAGEMENT)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)
        assert _room(client, room_id)["capacity"] == 2

    def test_teacher_cannot_create_a_building(self, client):
        _login(client, TEACHER)
        resp = client.post(
            f"{API}/housing/buildings", json={"name": f"T-{uuid.uuid4().hex[:8]}"}
        )
        assert resp.status_code == 403

    def test_teacher_cannot_edit_a_room(self, client):
        _login(client, ADMIN)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=1)

        _login(client, TEACHER)
        resp = client.patch(f"{API}/housing/rooms/{room_id}", json={"capacity": 9})
        assert resp.status_code == 403

    def test_student_cannot_create_a_building(self, client):
        _login(client, STUDENT)
        resp = client.post(
            f"{API}/housing/buildings", json={"name": f"T-{uuid.uuid4().hex[:8]}"}
        )
        assert resp.status_code == 403

    def test_student_cannot_retire_a_bed(self, client):
        _login(client, ADMIN)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)
        bed_id = _room(client, room_id)["beds"][0]["id"]

        _login(client, STUDENT)
        resp = client.patch(f"{API}/housing/beds/{bed_id}", json={"is_active": False})
        assert resp.status_code == 403

    def test_assignment_permission_does_not_grant_structure_edits(self, client, db_session):
        """The two jobs are separately permissioned; prove it with the roles.

        A role holding `housing.assign` but not `housing.edit` must be able to
        place a student and still be refused a capacity change.
        """
        _login(client, ADMIN)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)

        from app.models.identity import Permission, Role

        role = Role(name="HOUSING_OFFICER", description="assign only")
        for codename in ("housing.view", "housing.view_all", "housing.assign"):
            permission = db_session.query(Permission).filter(
                Permission.codename == codename
            ).first()
            assert permission is not None, f"{codename} should exist"
            role.permissions.append(permission)
        db_session.add(role)
        db_session.commit()

        user = db_session.query(User).filter(User.email == STUDENT).first()
        user.roles.append(role)
        db_session.commit()

        _login(client, STUDENT)
        # Assignment is allowed…
        allowed = _assign(client, _student_user_id(), _room(client, room_id)["beds"][0]["id"])
        assert allowed.status_code == 201, allowed.text
        # …and structure editing is still refused.
        denied = client.patch(f"{API}/housing/rooms/{room_id}", json={"capacity": 3})
        assert denied.status_code == 403


class TestStructureIntegrity:
    def test_structure_edits_are_audited(self, client):
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=2)
        client.patch(f"{API}/housing/rooms/{room_id}", json={"status": "RESERVED"})

        entries = client.get(f"{API}/audit?page_size=50").json()
        items = entries["items"] if isinstance(entries, dict) else entries
        actions = {entry["action"] for entry in items}
        assert "housing.building.created" in actions
        assert "housing.room.created" in actions
        assert "housing.room.status_changed" in actions

    def test_a_failed_structure_edit_writes_nothing(self, client, db_session):
        """A refused capacity reduction must not half-apply."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=3)
        beds = _room(client, room_id)["beds"]
        assert _assign(client, _student_user_id(), beds[0]["id"]).status_code == 201
        assert (
            _assign(client, _second_student(client), beds[1]["id"]).status_code == 201
        )

        assert (
            client.patch(f"{API}/housing/rooms/{room_id}", json={"capacity": 1}).status_code
            == 409
        )

        room = db_session.query(Room).filter(Room.id == uuid.UUID(room_id)).first()
        assert room.capacity == 3
        active = (
            db_session.query(Bed)
            .filter(Bed.room_id == room.id, Bed.is_active.is_(True))
            .all()
        )
        assert len(active) == 3
        still_housed = (
            db_session.query(HousingAssignment)
            .filter(
                HousingAssignment.bed_id.in_([b.id for b in active]),
                HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
            )
            .count()
        )
        assert still_housed == 2

    def test_structure_created_through_the_api_is_assignable(self, client):
        """Round trip: what the administrator builds is what staff can use."""
        _login(client)
        building_id = _new_building(client)
        _, room_id = _new_room(client, building_id, capacity=1)

        building = client.get(f"{API}/housing/buildings/{building_id}").json()
        floor_id = building["floors"][0]["id"]

        listed = client.get(f"{API}/housing/floors/{floor_id}/rooms").json()
        assert [r["id"] for r in listed] == [room_id]

        bed_id = _room(client, room_id)["beds"][0]["id"]
        assert _assign(client, _student_user_id(), bed_id).status_code == 201

        after = _room(client, room_id)
        assert after["occupied"] == 1
        assert after["occupancy_status"] == "FULL"

    def test_seeded_buildings_are_untouched_by_the_new_endpoints(self, client, db_session):
        """Regression guard: the real SCU estate must still be present."""
        _login(client)

        db = SessionLocal()
        try:
            seeded = [f"Building {n}" for n in range(18, 26)]
            real = db.query(Building).filter(Building.name.in_(seeded)).count()
            floors = db.query(Floor).filter(Floor.floor_number == 5).count()
            rooms = db.query(Room).count()
            beds = db.query(Bed).count()
        finally:
            db.close()

        assert real == 8, "the eight seeded buildings must still exist"
        assert floors == 8, "each building still has its fifth floor"
        assert rooms == 304, "the seeded estate is still 304 rooms"
        assert beds == 304 * 4, "rooms still hold their four beds"
