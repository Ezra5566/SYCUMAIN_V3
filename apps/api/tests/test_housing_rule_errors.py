"""Housing rule violations must return specific, localizable error codes.

Each assignment rule (bed taken, room out of service, student already housed)
used to collapse into a single ``CONFLICT`` with a prose message, so the client
could not tell the user *which* rule they hit and could not translate the
reason. These tests pin the codes the UI now renders.
"""

import uuid

from app.database.session import SessionLocal
from app.models.housing import Bed, HousingAssignment, Room, RoomStatus
from app.models.identity import Student, User

API = "/api/v1"

START = "2026-09-01T00:00:00Z"


def _login(client, email="admin@school.portal"):
    resp = client.post(
        f"{API}/auth/login", json={"email": email, "password": "password123"}
    )
    assert resp.status_code == 200
    return resp


def _student_user_id(email="student@school.portal") -> str:
    """Housing is keyed on the account (users.id), so resolve it explicitly."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        return str(user.id)
    finally:
        db.close()


def _student_record_id(email="student@school.portal") -> str:
    """The student *record* id, which is what the profile-facing routes take."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        student = db.query(Student).filter(Student.user_id == user.id).first()
        return str(student.id)
    finally:
        db.close()


def _first_bed() -> dict:
    db = SessionLocal()
    try:
        bed = db.query(Bed).filter(Bed.is_active.is_(True)).first()
        room = db.query(Room).filter(Room.id == bed.room_id).first()
        return {
            "bed_id": str(bed.id),
            "room_id": str(room.id),
            "room_status": str(room.status),
        }
    finally:
        db.close()


def _assign(client, student_id: str, bed_id: str):
    return client.post(
        f"{API}/housing/assignments",
        json={"student_id": student_id, "bed_id": bed_id, "start_date": START},
    )


def _error_code(response) -> str:
    return response.json()["error"]["code"]


class TestAssignmentRuleCodes:
    def test_occupied_bed_reports_bed_occupied(self, client):
        """The second occupant must be told the bed is taken, not 'conflict'."""
        _login(client)
        bed_id = _first_bed()["bed_id"]

        first = _assign(client, _student_user_id(), bed_id)
        assert first.status_code == 201

        # A real second student: a fabricated id would be refused as an
        # unknown occupant before the bed is examined.
        second = _assign(client, _login_second_student(client), bed_id)
        assert second.status_code == 409
        assert _error_code(second) == "BED_OCCUPIED"

    def test_unknown_bed_reports_bed_not_found(self, client):
        _login(client)
        resp = _assign(client, _student_user_id(), str(uuid.uuid4()))
        assert resp.status_code == 404
        assert _error_code(resp) == "BED_NOT_FOUND"

    def test_out_of_service_room_reports_room_out_of_service(self, client):
        _login(client)
        target = _first_bed()

        db = SessionLocal()
        try:
            room = db.query(Room).filter(Room.id == target["room_id"]).first()
            original = room.status
            room.status = RoomStatus.OUT_OF_SERVICE
            db.commit()
        finally:
            db.close()

        try:
            resp = _assign(client, _student_user_id(), target["bed_id"])
            assert resp.status_code == 409
            assert _error_code(resp) == "ROOM_OUT_OF_SERVICE"
        finally:
            db = SessionLocal()
            try:
                room = db.query(Room).filter(Room.id == target["room_id"]).first()
                room.status = original
                db.commit()
            finally:
                db.close()

    def test_second_active_assignment_reports_already_assigned(self, client):
        """A student with a bed must be told to transfer, not given a 2nd bed."""
        _login(client)
        student_id = _student_user_id()

        db = SessionLocal()
        try:
            beds = db.query(Bed).filter(Bed.is_active.is_(True)).limit(2).all()
            bed_ids = [str(b.id) for b in beds]
        finally:
            db.close()

        assert _assign(client, student_id, bed_ids[0]).status_code == 201

        resp = _assign(client, student_id, bed_ids[1])
        assert resp.status_code == 409
        assert _error_code(resp) == "STUDENT_ALREADY_ASSIGNED"


class TestOccupantValidation:
    def test_unknown_occupant_is_a_clean_404(self, client):
        _login(client)
        resp = _assign(client, str(uuid.uuid4()), _first_bed()["bed_id"])
        assert resp.status_code == 404
        assert _error_code(resp) == "STUDENT_NOT_FOUND"

    def test_a_staff_account_cannot_be_housed(self, client):
        """Housing a teacher is a data-integrity fault, not just bad input."""
        _login(client)
        db = SessionLocal()
        try:
            teacher = db.query(User).filter(User.email == "teacher@school.portal").first()
            teacher_id = str(teacher.id)
        finally:
            db.close()

        resp = _assign(client, teacher_id, _first_bed()["bed_id"])
        assert resp.status_code == 404
        assert _error_code(resp) == "STUDENT_NOT_FOUND"


class TestTransferRuleCodes:
    def test_transfer_to_occupied_bed_reports_bed_occupied(self, client):
        _login(client)

        db = SessionLocal()
        try:
            beds = db.query(Bed).filter(Bed.is_active.is_(True)).limit(2).all()
            bed_ids = [str(b.id) for b in beds]
        finally:
            db.close()

        first = _assign(client, _student_user_id(), bed_ids[0])
        assert first.status_code == 201

        # Occupy the destination with a different student.
        other = _login_second_student(client)
        assert _assign(client, other, bed_ids[1]).status_code == 201

        resp = client.post(
            f"{API}/housing/assignments/{first.json()['id']}/transfer",
            json={"new_bed_id": bed_ids[1], "transfer_date": START},
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "BED_OCCUPIED"

    def test_transfer_into_out_of_service_room_is_refused(self, client):
        """Creation refuses an out-of-service room; a transfer used to slip past.

        Two beds in *different* rooms, so taking the destination out of service
        cannot invalidate the source assignment under test.
        """
        _login(client)

        db = SessionLocal()
        try:
            rooms = (
                db.query(Room)
                .filter(Room.status != RoomStatus.OUT_OF_SERVICE)
                .limit(2)
                .all()
            )
            source = (
                db.query(Bed)
                .filter(Bed.room_id == rooms[0].id, Bed.is_active.is_(True))
                .first()
            )
            target = (
                db.query(Bed)
                .filter(Bed.room_id == rooms[1].id, Bed.is_active.is_(True))
                .first()
            )
            source_bed_id, target_bed_id = str(source.id), str(target.id)
            target_room_id, original = str(rooms[1].id), rooms[1].status
            rooms[1].status = RoomStatus.OUT_OF_SERVICE
            db.commit()
        finally:
            db.close()

        try:
            first = _assign(client, _student_user_id(), source_bed_id)
            assert first.status_code == 201, first.text

            resp = client.post(
                f"{API}/housing/assignments/{first.json()['id']}/transfer",
                json={"new_bed_id": target_bed_id, "transfer_date": START},
            )
            assert resp.status_code == 409
            assert _error_code(resp) == "ROOM_OUT_OF_SERVICE"

            # The rejected transfer must leave the student where they were.
            current = client.get(
                f"{API}/housing/students/{_student_record_id()}/housing"
            )
            assert current.status_code == 200
            assert current.json()["assignment"]["bed_id"] == source_bed_id
        finally:
            db = SessionLocal()
            try:
                room = db.query(Room).filter(Room.id == target_room_id).first()
                room.status = original
                db.commit()
            finally:
                db.close()

    def test_transfer_from_missing_assignment_is_404(self, client):
        _login(client)
        bed_id = _first_bed()["bed_id"]
        resp = client.post(
            f"{API}/housing/assignments/{uuid.uuid4()}/transfer",
            json={"new_bed_id": bed_id, "transfer_date": START},
        )
        assert resp.status_code == 404
        assert _error_code(resp) == "ASSIGNMENT_NOT_FOUND"


class TestUpdateRuleCodes:
    def test_reactivating_a_closed_assignment_is_reported(self, client):
        _login(client)
        created = _assign(client, _student_user_id(), _first_bed()["bed_id"])
        assert created.status_code == 201
        assignment_id = created.json()["id"]

        ended = client.post(f"{API}/housing/assignments/{assignment_id}/end")
        assert ended.status_code == 200

        resp = client.patch(
            f"{API}/housing/assignments/{assignment_id}", json={"status": "ACTIVE"}
        )
        assert resp.status_code == 409
        assert _error_code(resp) == "ASSIGNMENT_NOT_REACTIVATABLE"

    def test_updating_a_missing_assignment_is_404(self, client):
        """Previously the status was chosen by sniffing 'not found' out of the
        exception message; the typed error carries it instead."""
        _login(client)
        resp = client.patch(
            f"{API}/housing/assignments/{uuid.uuid4()}", json={"notes": "x"}
        )
        assert resp.status_code == 404
        assert _error_code(resp) == "ASSIGNMENT_NOT_FOUND"


def _login_second_student(client) -> str:
    """Create a second STUDENT account, returning its user id.

    Needed because a student may hold only one active assignment, so the
    occupied-destination case requires two distinct students.
    """
    unique = uuid.uuid4().hex[:8]
    created = client.post(
        f"{API}/users/",
        json={
            "email": f"housing-rule-{unique}@example.com",
            "full_name": "Housing Rule Check",
            "roles": ["STUDENT"],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()["account"]["id"]


def test_housing_assignment_rows_survive_the_rule_failures(client, db_session):
    """A rejected rule must not leave a half-written assignment behind.

    Read back through ``db_session`` — the same session the request used —
    because rows written during a test are deliberately not committed, so an
    independent connection could not see them either way.
    """
    _login(client)
    student_id = _student_user_id()
    bed_id = _first_bed()["bed_id"]
    assert _assign(client, student_id, bed_id).status_code == 201
    assert _assign(client, student_id, bed_id).status_code == 409

    rows = (
        db_session.query(HousingAssignment)
        .filter(HousingAssignment.student_id == uuid.UUID(student_id))
        .all()
    )
    assert len(rows) == 1, "a rejected assignment wrote a row"
    assert sum(1 for r in rows if str(r.status) == "ACTIVE") == 1


def test_student_records_are_not_the_housing_key(client):
    """Documents the current coupling: housing is keyed on users.id.

    Not an endorsement — the reverse lookup (Student -> user_id) is done in the
    router. This test exists so the assumption is visible rather than implied,
    and so a future migration to `students.id` fails here loudly and gets
    updated deliberately.
    """
    _login(client)
    db = SessionLocal()
    try:
        student = db.query(Student).first()
        user = db.query(User).filter(User.id == student.user_id).first()
        assert user is not None

        bed_id = str(db.query(Bed).filter(Bed.is_active.is_(True)).first().id)
        resp = _assign(client, str(user.id), bed_id)
        assert resp.status_code == 201
        assert resp.json()["student_id"] == str(user.id)

        # Passing the *student record* id is refused with a clear 404. Before
        # the occupant check existed this reached the foreign key and returned
        # an unhandled 500 naming the constraint.
        wrong = _assign(client, str(student.id), bed_id)
        assert wrong.status_code == 404
        assert _error_code(wrong) == "STUDENT_NOT_FOUND"
    finally:
        db.close()
