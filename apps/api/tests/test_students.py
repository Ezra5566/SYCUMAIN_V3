"""Tests for student CRUD API and authorization."""

import uuid
from datetime import UTC, date, datetime

from app.auth.service import hash_password
from app.models.academic import AcademicPeriod, ProgramOffering
from app.models.admission import AcademicAdmission, AcademicPlacement
from app.models.identity import Role, Student, StudentStatus, User

# --- Helper Functions ---


def login_as(client, email, password="password123"):
    """Login and return the response."""
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def _intake_student(db, tag: str) -> Student:
    user = User(
        email=f"{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Intake {tag}",
        is_active=True,
    )
    role = db.query(Role).filter(Role.name == "STUDENT").first()
    assert role is not None
    user.roles.append(role)
    db.add(user)
    db.flush()
    student = Student(
        user_id=user.id,
        student_id=f"INT-{tag}-{uuid.uuid4().hex[:6]}",
        first_name="Intake",
        last_name=tag,
        status=StudentStatus.ACTIVE,
    )
    db.add(student)
    db.flush()
    return student


def test_intake_filters_are_independent(client, db_session):
    """Original admission intake and current placement intake differ."""
    login_as(client, "admin@school.portal")
    admin = db_session.query(User).filter(User.email == "admin@school.portal").first()
    assert admin is not None

    p1 = AcademicPeriod(
        code=f"INT-{uuid.uuid4().hex[:6]}",
        name="Filter original intake",
        start_date=date(2030, 9, 1),
        end_date=date(2030, 12, 31),
        status="PLANNED",
    )
    p2 = AcademicPeriod(
        code=f"INT-{uuid.uuid4().hex[:6]}",
        name="Filter placement intake",
        start_date=date(2031, 2, 1),
        end_date=date(2031, 6, 30),
        status="PLANNED",
    )
    db_session.add_all([p1, p2])
    db_session.flush()
    offering1 = ProgramOffering(
        academic_period_id=p1.id,
        source_id=f"INT-{uuid.uuid4().hex[:6]}",
        source_key=f"intake-{uuid.uuid4().hex}",
        name="Filter offering 1",
    )
    offering2 = ProgramOffering(
        academic_period_id=p2.id,
        source_id=f"INT-{uuid.uuid4().hex[:6]}",
        source_key=f"intake-{uuid.uuid4().hex}",
        name="Filter offering 2",
    )
    db_session.add_all([offering1, offering2])
    db_session.flush()

    def admission(student, *, verified=True, status="ACTIVE"):
        row = AcademicAdmission(
            student_id=student.id,
            admission_intake_id=p1.id,
            admitted_program_offering_id=offering1.id,
            status=status,
                            initial_status="ADMITTED",
                record_origin="NEW_ADMISSION" if verified else "MIGRATED",
                verification_status="VERIFIED" if verified else "UNVERIFIED",
            verified_at=datetime.now(UTC) if verified else None,
            activated_at=(
                datetime.now(UTC) if status in {"ACTIVE", "COMPLETED"} else None
            ),
            ended_at=datetime.now(UTC) if status == "COMPLETED" else None,
            created_by_id=admin.id,
        )
        db_session.add(row)
        db_session.flush()
        student.original_admission_id = row.id
        return row

    def placement(student, admission_row, period, offering):
        db_session.add(
            AcademicPlacement(
                student_id=student.id,
                admission_id=admission_row.id,
                academic_period_id=period.id,
                program_offering_id=offering.id,
                effective_from=date(2030, 9, 1),
                created_by_id=admin.id,
            )
        )

    moved = _intake_student(db_session, "moved")
    moved_admission = admission(moved)
    placement(moved, moved_admission, p2, offering2)

    same = _intake_student(db_session, "same")
    same_admission = admission(same)
    placement(same, same_admission, p1, offering1)

    unverified = _intake_student(db_session, "unverified")
    admission(unverified, verified=False)

    completed = _intake_student(db_session, "completed")
    completed_admission = admission(completed, status="COMPLETED")
    placement(completed, completed_admission, p1, offering1)

    db_session.commit()

    def listed(**params):
        response = client.get(
            "/api/v1/students/", params={"page_size": 100, **params}
        )
        assert response.status_code == 200, response.text
        return {item["student_id"] for item in response.json()["items"]}

    original = listed(original_intake_id=str(p1.id))
    assert moved.student_id in original
    assert same.student_id in original
    assert completed.student_id in original
    assert unverified.student_id not in original

    current_p1 = listed(current_intake_id=str(p1.id))
    assert same.student_id in current_p1
    assert moved.student_id not in current_p1
    # A terminal admission is not a current placement, even with an open row.
    assert completed.student_id not in current_p1
    assert unverified.student_id not in current_p1

    current_p2 = listed(current_intake_id=str(p2.id))
    assert moved.student_id in current_p2
    assert same.student_id not in current_p2

    both = listed(
        original_intake_id=str(p1.id), current_intake_id=str(p2.id)
    )
    assert moved.student_id in both
    assert same.student_id not in both


def get_student_id(client, email="student@school.portal"):
    """Get the student_id for the test student."""
    # Login as management to access student list
    login_as(client, "management@school.portal")
    response = client.get("/api/v1/students/")
    if response.status_code == 200:
        data = response.json()
        if data["items"]:
            return data["items"][0]["id"]
    return None


# --- List Students Tests ---


def test_list_students_admin(client):
    """Test admin can list all students."""
    login_as(client, "admin@school.portal")
    response = client.get("/api/v1/students/")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "meta" in data
    assert isinstance(data["items"], list)
    assert data["meta"]["page"] == 1


def test_list_students_management(client):
    """Test management can list students."""
    login_as(client, "management@school.portal")
    response = client.get("/api/v1/students/")
    assert response.status_code == 200


def test_list_students_student_denied(client):
    """Test students cannot list all students."""
    login_as(client, "student@school.portal")
    response = client.get("/api/v1/students/")
    assert response.status_code == 403
    data = response.json()
    assert data["error"]["code"] == "FORBIDDEN"


def test_list_students_unauthenticated(client):
    """Test unauthenticated users cannot list students."""
    response = client.get("/api/v1/students/")
    assert response.status_code == 401


def test_list_students_pagination(client):
    """Test pagination works."""
    login_as(client, "admin@school.portal")
    response = client.get("/api/v1/students/?page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert data["meta"]["page"] == 1
    assert data["meta"]["page_size"] == 10


def test_list_students_search(client):
    """Test search works."""
    login_as(client, "admin@school.portal")
    response = client.get("/api/v1/students/?search=Student")
    assert response.status_code == 200


def test_list_students_status_filter(client):
    """Test status filtering works."""
    login_as(client, "admin@school.portal")
    response = client.get("/api/v1/students/?status=ACTIVE")
    assert response.status_code == 200


# --- Create Student Tests ---


def test_create_student_admin(client):
    """Test admin can create a student."""
    login_as(client, "admin@school.portal")

    # First create a user to link
    from app.auth.service import hash_password
    unique_id = str(uuid.uuid4())[:8]

    # Create user via direct DB access (in real app this would be an API)
    from app.database.session import SessionLocal
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        user = UserModel(
            email=f"newstudent-{unique_id}@test.com",
            username=f"newstudent{unique_id}",
            hashed_password=hash_password("password123"),
            full_name=f"New Student {unique_id}",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = str(user.id)
    finally:
        db.close()

    response = client.post(
        "/api/v1/students/",
        json={
            "user_id": user_id,
            "student_id": f"STU-{unique_id}",
            "first_name": "New",
            "last_name": "Student",
            "nationality": "Japan",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["first_name"] == "New"
    assert data["last_name"] == "Student"
    assert data["status"] == "ACTIVE"


def test_create_student_management(client):
    """Test management can create a student."""
    login_as(client, "management@school.portal")

    from app.auth.service import hash_password
    unique_id = str(uuid.uuid4())[:8]

    from app.database.session import SessionLocal
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        user = UserModel(
            email=f"mgmtstudent-{unique_id}@test.com",
            username=f"mgmtstudent{unique_id}",
            hashed_password=hash_password("password123"),
            full_name=f"Mgmt Student {unique_id}",
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = str(user.id)
    finally:
        db.close()

    response = client.post(
        "/api/v1/students/",
        json={
            "user_id": user_id,
            "student_id": f"STU-MGMT-{unique_id}",
            "first_name": "Mgmt",
            "last_name": "Student",
        },
    )
    assert response.status_code == 201


def test_create_student_student_denied(client):
    """Test students cannot create students."""
    login_as(client, "student@school.portal")
    response = client.post(
        "/api/v1/students/",
        json={
            "user_id": str(uuid.uuid4()),
            "student_id": "STU-FAKE",
            "first_name": "Fake",
            "last_name": "Student",
        },
    )
    assert response.status_code == 403


def test_create_student_duplicate_id(client):
    """Test creating student with duplicate student_id fails."""
    login_as(client, "admin@school.portal")

    # Get existing student_id
    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        existing = db.query(StudentModel).first()
        existing_student_id = existing.student_id if existing else None
    finally:
        db.close()

    if existing_student_id:
        from app.auth.service import hash_password
        unique_id = str(uuid.uuid4())[:8]

        from app.models.identity import User as UserModel
        db = SessionLocal()
        try:
            user = UserModel(
                email=f"dup-{unique_id}@test.com",
                username=f"dup{unique_id}",
                hashed_password=hash_password("password123"),
                full_name=f"Dup User {unique_id}",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            user_id = str(user.id)
        finally:
            db.close()

        response = client.post(
            "/api/v1/students/",
            json={
                "user_id": user_id,
                "student_id": existing_student_id,  # Duplicate
                "first_name": "Dup",
                "last_name": "Student",
            },
        )
        assert response.status_code == 409


# --- Get Student Tests ---


def test_get_student_admin(client):
    """Test admin can get any student."""
    login_as(client, "admin@school.portal")

    # Get a student ID
    response = client.get("/api/v1/students/")
    if response.json()["items"]:
        student_id = response.json()["items"][0]["id"]
        response = client.get(f"/api/v1/students/{student_id}")
        assert response.status_code == 200
        data = response.json()
        assert "first_name" in data
        assert "last_name" in data
        assert "status" in data


def test_get_student_own(client):
    """Test student can get their own record."""
    login_as(client, "student@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        user = db.query(UserModel).filter(UserModel.email == "student@school.portal").first()
        student = user.student if user else None
        if student:
            response = client.get(f"/api/v1/students/{student.id}")
            assert response.status_code == 200
    finally:
        db.close()


def test_get_student_other_denied(client):
    """Test student cannot get another student's record."""
    login_as(client, "student@school.portal")

    # Get a different student's ID
    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        other_student = db.query(StudentModel).filter(
            StudentModel.student_id != "STU-001"
        ).first()
        if other_student:
            response = client.get(f"/api/v1/students/{other_student.id}")
            assert response.status_code == 403
    finally:
        db.close()


def test_get_student_not_found(client):
    """Test getting non-existent student returns 404."""
    login_as(client, "admin@school.portal")
    response = client.get(f"/api/v1/students/{uuid.uuid4()}")
    assert response.status_code == 404


# --- Update Student Tests ---


def test_update_student_admin(client):
    """Test admin can update a student."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        student = db.query(StudentModel).first()
        if student:
            response = client.patch(
                f"/api/v1/students/{student.id}",
                json={"phone": "+1234567890"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["phone"] == "+1234567890"
    finally:
        db.close()


def test_update_student_student_denied(client):
    """Test students cannot update student records via admin endpoint."""
    login_as(client, "student@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        student = db.query(StudentModel).first()
        if student:
            response = client.patch(
                f"/api/v1/students/{student.id}",
                json={"phone": "+1234567890"},
            )
            assert response.status_code == 403
    finally:
        db.close()


# --- Student Self-Update Tests ---


def test_student_self_update(client):
    """Test student can update their own limited fields."""
    login_as(client, "student@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        user = db.query(UserModel).filter(UserModel.email == "student@school.portal").first()
        if user and user.student:
            response = client.patch(
                f"/api/v1/students/{user.student.id}/self",
                json={"phone": "+9876543210"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["phone"] == "+9876543210"
    finally:
        db.close()


def test_student_self_update_limited_fields(client):
    """Test student self-update only allows limited fields."""
    login_as(client, "student@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import User as UserModel
    db = SessionLocal()
    try:
        user = db.query(UserModel).filter(UserModel.email == "student@school.portal").first()
        if user and user.student:
            # Try to update status (should be ignored)
            response = client.patch(
                f"/api/v1/students/{user.student.id}/self",
                json={"status": "GRADUATED"},
            )
            assert response.status_code == 200
            # Status should not have changed
            db.refresh(user.student)
            assert user.student.status != StudentStatus.GRADUATED
    finally:
        db.close()


# --- Archive Student Tests ---


def test_archive_student_admin(client):
    """Test admin can archive a student."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        student = db.query(StudentModel).filter(
            StudentModel.status == StudentStatus.ACTIVE
        ).first()
        if student:
            response = client.post(f"/api/v1/students/{student.id}/archive")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "INACTIVE"
    finally:
        db.close()


def test_archive_student_student_denied(client):
    """Test students cannot archive students."""
    login_as(client, "student@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        student = db.query(StudentModel).first()
        if student:
            response = client.post(f"/api/v1/students/{student.id}/archive")
            assert response.status_code == 403
    finally:
        db.close()


# --- Status Update Tests ---


def test_update_status_admin(client):
    """Test admin can update student status."""
    login_as(client, "admin@school.portal")

    from app.database.session import SessionLocal
    from app.models.identity import Student as StudentModel
    db = SessionLocal()
    try:
        student = db.query(StudentModel).first()
        if student:
            response = client.patch(
                f"/api/v1/students/{student.id}/status",
                json={"status": "SUSPENDED"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "SUSPENDED"
    finally:
        db.close()


# --- Validation Tests ---


def test_create_student_missing_required_fields(client):
    """Test create student with missing required fields fails."""
    login_as(client, "admin@school.portal")
    response = client.post(
        "/api/v1/students/",
        json={
            "user_id": str(uuid.uuid4()),
            # Missing student_id, first_name, last_name
        },
    )
    assert response.status_code == 422  # Validation error


def test_create_student_invalid_status(client):
    """Test creating student with invalid status fails."""
    login_as(client, "admin@school.portal")
    response = client.patch(
        f"/api/v1/students/{uuid.uuid4()}/status",
        json={"status": "INVALID_STATUS"},
    )
    assert response.status_code in [404, 422]  # Not found or validation error
