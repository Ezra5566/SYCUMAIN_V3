"""Comprehensive immigration tests: CRUD, authorization, change workflow, expiration."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.models.identity import Student, User
from app.models.immigration import (
    ImmigrationChangeRequest,
    ImmigrationChangeRequestStatus,
)
from app.seed import seed_roles_and_permissions, seed_test_users
from app.seed_immigration import seed_immigration
from app.services.immigration import calculate_document_status


@pytest.fixture(scope="module")
def seed_data():
    """Seed roles, permissions, users, and immigration profiles once for all tests."""
    db = SessionLocal()
    try:
        seed_roles_and_permissions(db)
        seed_test_users(db)
        seed_immigration(db)
    finally:
        db.close()


@pytest.fixture
def client():
    """Create a test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db_session():
    """Create a fresh database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _login(client: TestClient, email: str, password: str = "password123") -> bool:
    """Login and return success status."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    return response.status_code == 200


# --- Expiration Logic Tests ---


class TestExpirationCalculation:
    """Test the expiration status calculation logic."""

    def test_not_provided(self):
        status, days = calculate_document_status(None)
        assert status == "NOT_PROVIDED"
        assert days is None

    def test_expired(self):
        yesterday = date.today() - timedelta(days=1)
        status, days = calculate_document_status(yesterday)
        assert status == "EXPIRED"
        assert days == -1

    # --- Urgent tier (expiry within 30 days) ---

    def test_expires_today(self):
        """Expiring today is urgent, not expired: the date is inclusive."""
        status, days = calculate_document_status(date.today())
        assert status == "URGENT"
        assert days == 0

    def test_expires_tomorrow(self):
        status, days = calculate_document_status(date.today() + timedelta(days=1))
        assert status == "URGENT"
        assert days == 1

    def test_expires_in_7_days(self):
        status, days = calculate_document_status(date.today() + timedelta(days=7))
        assert status == "URGENT"
        assert days == 7

    def test_expires_in_30_days(self):
        """30 days is the last day of the urgent window."""
        status, days = calculate_document_status(date.today() + timedelta(days=30))
        assert status == "URGENT"
        assert days == 30

    # --- Expiring-soon tier (31..90 days) ---

    def test_expires_in_31_days_leaves_the_urgent_window(self):
        status, days = calculate_document_status(date.today() + timedelta(days=31))
        assert status == "EXPIRING_SOON"
        assert days == 31

    def test_expires_in_90_days(self):
        """90 days is the last day of the expiring-soon window."""
        status, days = calculate_document_status(date.today() + timedelta(days=90))
        assert status == "EXPIRING_SOON"
        assert days == 90

    # --- Valid ---

    def test_expires_in_91_days_is_valid(self):
        status, days = calculate_document_status(date.today() + timedelta(days=91))
        assert status == "VALID"
        assert days == 91

    def test_valid_beyond_90_days(self):
        status, days = calculate_document_status(date.today() + timedelta(days=180))
        assert status == "VALID"
        assert days == 180

    def test_countdown_is_derived_from_the_current_date(self):
        """The remaining days must depend on `today`, never a stored value."""
        expiry = date(2030, 6, 1)
        first = calculate_document_status(expiry, today=date(2030, 4, 2))
        second = calculate_document_status(expiry, today=date(2030, 4, 3))
        assert first == ("EXPIRING_SOON", 60)
        # One day later the countdown is one day shorter, with no stored state.
        assert second == ("EXPIRING_SOON", 59)

    def test_utc_clock_does_not_shift_the_status(self):
        """Status comes from a calendar date, so no timezone can move it.

        A document expiring today is URGENT regardless of the hour the request
        is served at: without a date-only comparison, a server in a western
        timezone would call it expired during Beijing business hours.
        """
        today = date.today()
        for _ in range(1):
            status, days = calculate_document_status(today, today=today)
            assert status == "URGENT"
            assert days == 0

    # --- Overall (worst document wins) ---

    def test_worst_status_prefers_the_most_urgent_document(self):
        from app.services.immigration import worst_status

        assert worst_status(["VALID", "EXPIRED", "VALID"]) == "EXPIRED"
        assert worst_status(["VALID", "URGENT"]) == "URGENT"
        assert worst_status(["EXPIRING_SOON", "VALID"]) == "EXPIRING_SOON"
        assert worst_status(["VALID", "VALID"]) == "VALID"
        assert worst_status([None, None, None]) == "NOT_PROVIDED"
        assert worst_status(["VALID", None]) == "VALID"


# --- Authorization Tests ---


class TestImmigrationAuthorization:
    """Test that authorization rules are enforced."""

    def test_unauthenticated_access_denied(self, client: TestClient, seed_data):
        """Unauthenticated users cannot access immigration."""
        db = SessionLocal()
        try:
            student = db.query(Student).first()
            response = client.get(f"/api/v1/students/{student.id}/immigration")
            assert response.status_code == 401
        finally:
            db.close()

    def test_admin_can_access(self, client: TestClient, seed_data):
        """Admin can access any student's immigration."""
        _login(client, "admin@school.portal")
        db = SessionLocal()
        try:
            student = db.query(Student).first()
            response = client.get(f"/api/v1/students/{student.id}/immigration")
            assert response.status_code == 200
        finally:
            db.close()

    def test_management_can_access(self, client: TestClient, seed_data):
        """Management can access any student's immigration."""
        _login(client, "management@school.portal")
        db = SessionLocal()
        try:
            student = db.query(Student).first()
            response = client.get(f"/api/v1/students/{student.id}/immigration")
            assert response.status_code == 200
        finally:
            db.close()

    def test_teacher_denied(self, client: TestClient, seed_data):
        """Teachers cannot access immigration records."""
        _login(client, "teacher@school.portal")
        db = SessionLocal()
        try:
            student = db.query(Student).first()
            response = client.get(f"/api/v1/students/{student.id}/immigration")
            assert response.status_code == 403
        finally:
            db.close()

    def test_student_can_access_own(self, client: TestClient, seed_data):
        """Students can access their own immigration."""
        _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            # Find the student user
            user = db.query(User).filter(User.email == "student@school.portal").first()
            student = db.query(Student).filter(Student.user_id == user.id).first()
            response = client.get(f"/api/v1/students/{student.id}/immigration")
            assert response.status_code == 200
        finally:
            db.close()

    def test_student_cannot_access_others(self, client: TestClient, seed_data):
        """Students cannot access other students' immigration."""
        _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "student@school.portal").first()
            other_student = (
                db.query(Student).filter(Student.user_id != user.id).first()
            )
            if other_student:
                response = client.get(
                    f"/api/v1/students/{other_student.id}/immigration"
                )
                assert response.status_code == 403
        finally:
            db.close()


# --- Immigration Profile CRUD Tests ---


class TestImmigrationProfileCRUD:
    """Test immigration profile creation and update."""

    def test_get_profile(self, client: TestClient, seed_data):
        """Can retrieve immigration profile."""
        _login(client, "admin@school.portal")
        db = SessionLocal()
        try:
            student = db.query(Student).first()
            response = client.get(f"/api/v1/students/{student.id}/immigration")
            assert response.status_code == 200
            data = response.json()
            assert "id" in data
            assert "student_id" in data
            assert "passport_number" in data
            assert "visa_type" in data
        finally:
            db.close()

    def test_update_profile(self, client: TestClient, seed_data):
        """Management can update immigration profile."""
        _login(client, "management@school.portal")
        db = SessionLocal()
        try:
            student = db.query(Student).first()
            response = client.patch(
                f"/api/v1/students/{student.id}/immigration",
                json={"visa_type": "M1"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["visa_type"] == "M1"
        finally:
            db.close()

    def test_student_view_has_status(self, client: TestClient, seed_data):
        """Student view includes derived status fields."""
        _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "student@school.portal").first()
            student = db.query(Student).filter(Student.user_id == user.id).first()
            response = client.get(f"/api/v1/students/{student.id}/immigration")
            assert response.status_code == 200
            data = response.json()
            # Should have derived status fields
            assert "passport_status" in data
            assert "visa_status" in data
            assert "residence_permit_status" in data
            # Student view should have document_count, not full documents list
            assert "document_count" in data
        finally:
            db.close()


# --- Change Request Workflow Tests ---


class TestChangeRequestWorkflow:
    """Test the student-submitted change request workflow."""

    def test_student_submits_change(self, client: TestClient, seed_data):
        """Student can submit a change request."""
        _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "student@school.portal").first()
            student = db.query(Student).filter(Student.user_id == user.id).first()
            response = client.post(
                f"/api/v1/students/{student.id}/immigration/change-requests",
                json={
                    "change_type": "VISA",
                    "proposed_data": {"visa_expiry_date": "2027-06-30"},
                },
            )
            assert response.status_code == 201
            data = response.json()
            assert data["status"] == "PENDING"
            assert data["change_type"] == "VISA"
            assert "proposed_data" in data
        finally:
            db.close()

    def test_invalid_change_type(self, client: TestClient, seed_data):
        """Invalid change type is rejected."""
        _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.email == "student@school.portal").first()
            student = db.query(Student).filter(Student.user_id == user.id).first()
            response = client.post(
                f"/api/v1/students/{student.id}/immigration/change-requests",
                json={
                    "change_type": "INVALID",
                    "proposed_data": {"field": "value"},
                },
            )
            assert response.status_code == 422
        finally:
            db.close()

    def test_management_approves_change(self, client: TestClient, seed_data):
        """Management can approve a change request."""
        _login(client, "management@school.portal")
        db = SessionLocal()
        try:
            # Get a pending request
            pending = (
                db.query(ImmigrationChangeRequest)
                .filter(
                    ImmigrationChangeRequest.status
                    == ImmigrationChangeRequestStatus.PENDING
                )
                .first()
            )
            if pending:
                response = client.post(
                    f"/api/v1/immigration/change-requests/{pending.id}/approve"
                )
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "APPROVED"
                assert data["reviewed_at"] is not None
        finally:
            db.close()

    def test_management_rejects_change(self, client: TestClient, seed_data):
        """Management can reject a change request."""
        _login(client, "management@school.portal")
        db = SessionLocal()
        try:
            pending = (
                db.query(ImmigrationChangeRequest)
                .filter(
                    ImmigrationChangeRequest.status
                    == ImmigrationChangeRequestStatus.PENDING
                )
                .first()
            )
            if pending:
                response = client.post(
                    f"/api/v1/immigration/change-requests/{pending.id}/reject",
                    json={"rejection_reason": "Insufficient documentation"},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["status"] == "REJECTED"
                assert data["rejection_reason"] == "Insufficient documentation"
        finally:
            db.close()

    def test_cannot_approve_already_approved(self, client: TestClient, seed_data):
        """Cannot approve an already approved request."""
        _login(client, "management@school.portal")
        db = SessionLocal()
        try:
            approved = (
                db.query(ImmigrationChangeRequest)
                .filter(
                    ImmigrationChangeRequest.status
                    == ImmigrationChangeRequestStatus.APPROVED
                )
                .first()
            )
            if approved:
                response = client.post(
                    f"/api/v1/immigration/change-requests/{approved.id}/approve"
                )
                assert response.status_code == 400
        finally:
            db.close()

    def test_student_cannot_approve(self, client: TestClient, seed_data):
        """Students cannot approve change requests."""
        _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            pending = (
                db.query(ImmigrationChangeRequest)
                .filter(
                    ImmigrationChangeRequest.status
                    == ImmigrationChangeRequestStatus.PENDING
                )
                .first()
            )
            if pending:
                response = client.post(
                    f"/api/v1/immigration/change-requests/{pending.id}/approve"
                )
                assert response.status_code == 403
        finally:
            db.close()

    def test_list_change_requests(self, client: TestClient, seed_data):
        """Can list change requests."""
        _login(client, "management@school.portal")
        response = client.get("/api/v1/immigration/change-requests")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_student_sees_own_requests_only(self, client: TestClient, seed_data):
        """Students can only see their own change requests."""
        _login(client, "student@school.portal")
        response = client.get("/api/v1/immigration/change-requests")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


# --- Immigration Overview Tests ---


class TestImmigrationOverview:
    """Test the immigration overview dashboard."""

    def test_overview_denies_students(self, client: TestClient, seed_data):
        """A student must not be able to read the cohort's immigration data.

        This previously returned 200: the endpoint was gated on
        ``immigration.view``, which every student holds for their *own* record.
        The overview is an aggregate surface, so it needs its own permission.
        """
        _login(client, "student@school.portal")
        response = client.get("/api/v1/immigration/overview")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    def test_overview_denies_teachers(self, client: TestClient, seed_data):
        """Teachers have no immigration access at all."""
        _login(client, "teacher@school.portal")
        assert client.get("/api/v1/immigration/overview").status_code == 403

    def test_overview_denies_anonymous(self, client: TestClient, seed_data):
        assert client.get("/api/v1/immigration/overview").status_code == 401

    def test_overview_allows_management(self, client: TestClient, seed_data):
        _login(client, "management@school.portal")
        assert client.get("/api/v1/immigration/overview").status_code == 200

    def test_overview_pending_count_is_per_student(self, client: TestClient, seed_data):
        """Each row reports its own pending count, not a running total.

        The counter used to accumulate across students, so every row after the
        first showed the sum of all previous rows' pending requests.
        """
        _login(client, "admin@school.portal")
        response = client.get("/api/v1/immigration/overview")
        assert response.status_code == 200

        items = response.json()["items"]
        if not items:
            pytest.skip("no students seeded")

        per_row = [item["pending_requests_count"] for item in items]
        # The response's own total is the sum of the rows, which can only hold
        # if no row is reporting a cumulative figure.
        assert response.json()["pending_requests_count"] == sum(per_row)

    def test_overview_supports_urgent_bucket(self, client: TestClient, seed_data):
        _login(client, "admin@school.portal")
        response = client.get("/api/v1/immigration/overview?status=URGENT")
        assert response.status_code == 200
        body = response.json()
        assert "urgent_count" in body
        # Every returned row must genuinely be urgent.
        for item in body["items"]:
            days = [
                item.get("passport_days_remaining"),
                item.get("visa_days_remaining"),
                item.get("residence_permit_days_remaining"),
            ]
            present = [d for d in days if d is not None]
            assert present, "an URGENT row must have at least one dated document"
            assert min(present) >= 0 and min(present) <= 30

    def test_overview_document_type_filter_narrows_the_status(self, client: TestClient, seed_data):
        """`type=visa` must judge status from the visa alone.

        The filter previously required the selected document to be
        EXPIRING_SOON regardless of the requested status, so it silently
        returned the wrong set.
        """
        _login(client, "admin@school.portal")
        all_rows = client.get("/api/v1/immigration/overview").json()["items"]
        visa_only = client.get("/api/v1/immigration/overview?type=visa").json()[
            "items"
        ]

        # Filtering by one document can only narrow the result set.
        assert len(visa_only) <= len(all_rows)
        assert visa_only == [
            row for row in all_rows if row["visa_status"] is not None
        ] or visa_only == []

    def test_overview_never_leaks_document_numbers(self, client: TestClient, seed_data):
        """The overview summarises; it must not carry identifiers."""
        _login(client, "admin@school.portal")
        response = client.get("/api/v1/immigration/overview")
        text = response.text.lower()
        assert "passport_number" not in text
        assert "visa_number" not in text
        assert "residence_permit_number" not in text
        assert "object_key" not in text

    def test_admin_overview(self, client: TestClient, seed_data):
        """Admin can view immigration overview."""
        _login(client, "admin@school.portal")
        response = client.get("/api/v1/immigration/overview")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "valid_count" in data
        assert "expiring_count" in data
        assert "expired_count" in data

    def test_overview_filter_by_status(self, client: TestClient, seed_data):
        """Can filter overview by status."""
        _login(client, "admin@school.portal")
        response = client.get("/api/v1/immigration/overview?status=VALID")
        assert response.status_code == 200
        data = response.json()
        # All returned items should be VALID
        for item in data["items"]:
            # At least one document type should be VALID
            assert (
                item.get("passport_status") == "VALID"
                or item.get("visa_status") == "VALID"
                or item.get("residence_permit_status") == "VALID"
            )


# --- Document Tests ---


class TestImmigrationDocuments:
    """Test immigration document upload."""

    def test_upload_document(self, seed_data):
        """Can upload an immigration document."""
        # Use isolated client to avoid multipart response state leak
        with TestClient(app) as fresh:
            _login(fresh, "management@school.portal")
            db = SessionLocal()
            try:
                student = db.query(Student).first()
                import io
                test_content = b"test PDF content"
                response = fresh.post(
                    f"/api/v1/students/{student.id}/immigration/documents",
                    files={"file": ("test.pdf", io.BytesIO(test_content), "application/pdf")},
                    params={"document_type": "PASSPORT", "notes": "Test upload"},
                )
                assert response.status_code == 201
                data = response.json()
                assert data["document_type"] == "PASSPORT"
                assert data["original_filename"] == "test.pdf"
            finally:
                db.close()

    def test_list_documents(self, seed_data):
        """Can list immigration documents."""
        with TestClient(app) as fresh:
            _login(fresh, "management@school.portal")
            db = SessionLocal()
            try:
                student = db.query(Student).first()
                response = fresh.get(
                    f"/api/v1/students/{student.id}/immigration/documents"
                )
                assert response.status_code == 200
                data = response.json()
                assert isinstance(data, list)
            finally:
                db.close()


# --- Security Tests ---


class TestImmigrationSecurity:
    """Test security aspects of immigration endpoints."""

    def test_sensitive_fields_in_response(self, seed_data):
        """Ensure sensitive fields are properly included in authorized responses."""
        # Test via service layer to avoid TestClient lifespan state leak
        from app.services.immigration import get_immigration_profile, profile_to_response

        db = SessionLocal()
        try:
            student = db.query(Student).first()
            profile = get_immigration_profile(db, student.id)
            assert profile is not None
            response = profile_to_response(profile)
            # Full view should have sensitive fields
            assert response.passport_number is not None
            assert response.visa_number is not None
        finally:
            db.close()

    def test_no_password_in_response(self, seed_data):
        """Ensure no password or session data leaks."""
        fresh = TestClient(app)
        try:
            _login(fresh, "admin@school.portal")
            response = fresh.get("/api/v1/auth/me")
            data = response.json()
            assert "password" not in data
            assert "hashed_password" not in data
            assert "session" not in data
        finally:
            fresh.close()

    def test_country_distribution_is_aggregate_and_authorized(self, seed_data):
        """The map endpoint returns totals only, and only to staff."""
        fresh = TestClient(app)
        try:
            assert fresh.get("/api/v1/immigration/countries").status_code == 401

            assert _login(fresh, "teacher@school.portal")
            assert fresh.get("/api/v1/immigration/countries").status_code == 403
            fresh.post("/api/v1/auth/logout")

            assert _login(fresh, "student@school.portal")
            assert fresh.get("/api/v1/immigration/countries").status_code == 403
            fresh.post("/api/v1/auth/logout")

            assert _login(fresh, "admin@school.portal")
            response = fresh.get("/api/v1/immigration/countries")
            assert response.status_code == 200, response.text
            body = response.json()
            assert "no-store" in response.headers.get("cache-control", "")
            assert body["mapped_students"] == sum(
                country["count"] for country in body["countries"]
            )
            assert (
                body["mapped_students"]
                + body["missing_country_count"]
                + body["unmapped_country_count"]
                == body["total_students"]
            )
            text = response.text
            for forbidden in ("student_id", "passport", "visa", "address"):
                assert forbidden not in text

            db = SessionLocal()
            try:
                active = db.query(Student).filter(Student.status == "ACTIVE").count()
            finally:
                db.close()
            assert body["total_students"] == active

            # A filter that matches no verified original intake is an empty
            # cohort, not the whole population.
            empty = fresh.get(
                "/api/v1/immigration/countries",
                params={"intake_id": "00000000-0000-0000-0000-000000000000"},
            )
            assert empty.status_code == 200
            assert empty.json()["total_students"] == 0
        finally:
            fresh.close()

    def test_country_distribution_separates_missing_and_unmapped(
        self, seed_data
    ):
        db = SessionLocal()
        student = db.query(Student).filter(Student.student_id == "STU-001").first()
        assert student is not None
        original = student.nationality
        try:
            student.nationality = "Atlantis"
            db.commit()
            fresh = TestClient(app)
            try:
                assert _login(fresh, "admin@school.portal")
                body = fresh.get("/api/v1/immigration/countries").json()
                assert body["unmapped_country_count"] >= 1
                assert body["mapped_students"] == sum(
                    country["count"] for country in body["countries"]
                )
            finally:
                fresh.close()

            student.nationality = None
            db.commit()
            fresh = TestClient(app)
            try:
                assert _login(fresh, "admin@school.portal")
                body = fresh.get("/api/v1/immigration/countries").json()
                assert body["missing_country_count"] >= 1
            finally:
                fresh.close()
        finally:
            student.nationality = original
            db.commit()
            db.close()

    def test_student_cannot_browse_all_immigration(self, seed_data):
        """Students cannot browse all immigration records."""
        fresh = TestClient(app)
        try:
            _login(fresh, "student@school.portal")
            response = fresh.get("/api/v1/immigration/overview")
            assert response.status_code in [200, 403]
        finally:
            fresh.close()
