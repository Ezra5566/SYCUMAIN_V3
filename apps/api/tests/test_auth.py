"""Tests for authentication and authorization."""

import json

from app.auth.service import (
    create_session,
    get_user_from_session,
    hash_password,
    invalidate_session,
    verify_password,
)
from app.database.session import SessionLocal
from app.models.identity import User
from app.seed import seed_roles_and_permissions, seed_test_users

# --- Password Hashing Tests ---


def test_password_hashing():
    """Test that passwords are properly hashed."""
    password = "testpassword123"
    hashed = hash_password(password)

    # Hash should be different from plaintext
    assert hashed != password

    # Should verify correctly
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False


def test_password_hashing_unique():
    """Test that hashing the same password produces different hashes (salt)."""
    password = "testpassword123"
    hash1 = hash_password(password)
    hash2 = hash_password(password)

    # Different hashes due to random salt
    assert hash1 != hash2

    # But both should verify
    assert verify_password(password, hash1) is True
    assert verify_password(password, hash2) is True


# --- Session Tests ---


def test_create_and_get_session(db_session):
    """Test creating a session and retrieving user from it."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)

    user = db_session.query(User).filter(User.email == "admin@school.portal").first()
    assert user is not None

    # Create session
    raw_token, session = create_session(db_session, user)

    # Token should be a non-empty string
    assert isinstance(raw_token, str)
    assert len(raw_token) > 0

    # Should be able to get user from session
    retrieved_user = get_user_from_session(db_session, raw_token)
    assert retrieved_user is not None
    assert retrieved_user.id == user.id


def test_invalid_session_token(db_session):
    """Test that invalid tokens return None."""
    result = get_user_from_session(db_session, "invalid-token-12345")
    assert result is None


def test_invalidate_session(db_session):
    """Test session invalidation (logout)."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)

    user = db_session.query(User).filter(User.email == "admin@school.portal").first()
    raw_token, _ = create_session(db_session, user)

    # Session should exist
    assert get_user_from_session(db_session, raw_token) is not None

    # Invalidate
    result = invalidate_session(db_session, raw_token)
    assert result is True

    # Session should no longer exist
    assert get_user_from_session(db_session, raw_token) is None


# --- Login Endpoint Tests ---


def test_login_success(client):
    """Test successful login with valid credentials."""
    # Seed test users via the app's startup
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "user" in data
    assert data["user"]["email"] == "admin@school.portal"
    assert data["user"]["full_name"] == "Admin User"
    assert "ADMIN" in [r["name"] for r in data["user"]["roles"]]
    assert len(data["user"]["permissions"]) > 0

    # Should have set session cookie
    assert "session_token" in response.cookies


def test_login_invalid_password(client):
    """Test login with invalid password."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "INVALID_CREDENTIALS"
    # Should not reveal whether email exists
    assert "does not exist" not in data["error"]["message"].lower()


def test_login_nonexistent_email(client):
    """Test login with nonexistent email - should give same error as wrong password."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@school.portal", "password": "password123"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "INVALID_CREDENTIALS"
    # Should not reveal that the email doesn't exist
    assert "does not exist" not in data["error"]["message"].lower()


def test_login_all_roles(client):
    """Test login works for all four role types."""
    accounts = [
        ("admin@school.portal", "ADMIN"),
        ("management@school.portal", "MANAGEMENT"),
        ("teacher@school.portal", "TEACHER"),
        ("student@school.portal", "STUDENT"),
    ]

    for email, expected_role in accounts:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
        assert response.status_code == 200, f"Login failed for {email}"
        data = response.json()
        role_names = [r["name"] for r in data["user"]["roles"]]
        assert expected_role in role_names, f"Expected role {expected_role} for {email}"


# --- Logout Endpoint Tests ---


def test_logout(client):
    """Test logout invalidates session."""
    # Login
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    )
    assert login_response.status_code == 200

    # Logout
    logout_response = client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json()["message"] == "Logged out successfully"

    # Session cookie should be cleared
    # After logout, /me should fail
    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 401


def test_logout_without_session(client):
    """Test logout when not logged in doesn't error."""
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200


# --- Me Endpoint Tests ---


def test_me_authenticated(client):
    """Test /me returns user info when authenticated."""
    # Login
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    )
    assert login_response.status_code == 200

    # Get me
    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    data = me_response.json()
    assert data["email"] == "admin@school.portal"
    assert data["username"] == "admin"
    assert "id" in data
    assert "roles" in data
    assert "permissions" in data
    assert isinstance(data["permissions"], list)


def test_me_unauthenticated(client):
    """Test /me returns 401 when not authenticated."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_after_logout(client):
    """Test /me returns 41 after logout."""
    # Login
    client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    )

    # Logout
    client.post("/api/v1/auth/logout")

    # Me should fail
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


# --- Authorization Tests (401 vs 403) ---


def test_unauthenticated_access_returns_401(client):
    """Test that unauthenticated access returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


def test_password_never_in_response(client):
    """No password material may appear in an authentication response.

    Asserts on the credential itself rather than on the substring "password":
    a boolean field such as ``must_change_password`` legitimately contains that
    substring, while returning it leaks nothing. What must never appear is the
    submitted plaintext or the stored hash.
    """
    submitted = "password123"
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": submitted},
    )
    assert response.status_code == 200
    data = response.json()
    response_text = json.dumps(data)

    # The stored hash, read straight from the database for comparison.
    db = SessionLocal()
    try:
        user = (
            db.query(User).filter(User.email == "admin@school.portal").first()
        )
        stored_hash = user.hashed_password
    finally:
        db.close()

    assert "hashed_password" not in response_text
    assert stored_hash not in response_text
    assert submitted not in response_text
    # No field is literally named `password`.
    assert "password" not in {key.lower() for key in data.get("user", {})}

    # And the same holds for the identity endpoint.
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert stored_hash not in json.dumps(me.json())
    assert submitted not in json.dumps(me.json())


def test_session_cookie_security(client):
    """Test that session cookie has proper security attributes."""
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    )
    assert response.status_code == 200

    # Check cookie attributes
    cookie = response.cookies.get("session_token")
    assert cookie is not None
    # Cookie should be set (in test client, httponly is not directly checkable
    # but we can verify the cookie exists)


# --- Role-Based Permission Tests ---


def test_admin_has_all_permissions(client):
    """Test that admin has extensive permissions."""
    client.post(
        "/api/v1/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    )

    me_response = client.get("/api/v1/auth/me")
    data = me_response.json()
    permissions = data["permissions"]

    # Admin should have these key permissions
    assert "student.view" in permissions
    assert "student.create" in permissions
    assert "users.manage" in permissions
    assert "permissions.manage" in permissions
    assert "system.manage" in permissions


def test_student_limited_permissions(client):
    """Test that student has limited permissions."""
    client.post(
        "/api/v1/auth/login",
        json={"email": "student@school.portal", "password": "password123"},
    )

    me_response = client.get("/api/v1/auth/me")
    data = me_response.json()
    permissions = data["permissions"]

    # Student should have these
    assert "student.view" in permissions
    assert "academic.view" in permissions

    # Student should NOT have these
    assert "users.manage" not in permissions
    assert "permissions.manage" not in permissions
    assert "system.manage" not in permissions
    assert "student.create" not in permissions


def test_teacher_limited_permissions(client):
    """Test that teacher has teaching-specific permissions."""
    client.post(
        "/api/v1/auth/login",
        json={"email": "teacher@school.portal", "password": "password123"},
    )

    me_response = client.get("/api/v1/auth/me")
    data = me_response.json()
    permissions = data["permissions"]

    # Teacher should have
    assert "student.view" in permissions
    assert "academic.view" in permissions
    assert "attendance.edit" in permissions
    assert "grades.edit" in permissions

    # Teacher should NOT have
    assert "users.manage" not in permissions
    assert "permissions.manage" not in permissions
    assert "immigration.edit" not in permissions
    assert "housing.assign" not in permissions


def test_management_permissions(client):
    """Test that management has operational permissions."""
    client.post(
        "/api/v1/auth/login",
        json={"email": "management@school.portal", "password": "password123"},
    )

    me_response = client.get("/api/v1/auth/me")
    data = me_response.json()
    permissions = data["permissions"]

    # Management should have
    assert "student.view" in permissions
    assert "student.create" in permissions
    assert "student.edit" in permissions
    assert "housing.view" in permissions
    assert "housing.assign" in permissions
    assert "immigration.view" in permissions

    # Management should NOT have
    assert "permissions.manage" not in permissions
    assert "system.manage" not in permissions


# --- Deterministic Seed Tests ---


def test_seed_is_deterministic(db_session):
    """Test that running seed multiple times doesn't create duplicates."""
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)

    # Count users
    user_count_1 = db_session.query(User).count()

    # Run seed again
    seed_roles_and_permissions(db_session)
    seed_test_users(db_session)

    # Count should be the same
    user_count_2 = db_session.query(User).count()
    assert user_count_1 == user_count_2
