"""Pytest configuration and shared fixtures."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set test environment before importing app
os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = os.environ.get(
    "SYCUMAIN_TEST_DATABASE_URL",
    "postgresql://portal:portal@localhost:5434/school_portal_test_v2",
)
# Pin the values that the suite asserts on. Without this, a developer's
# `.env` (which enables the dev reset channel and points CORS at port 3101)
# would silently change test semantics.
os.environ["PASSWORD_RESET_DELIVERY"] = "disabled"
os.environ["CORS_ORIGINS"] = '["http://localhost:3100"]'
# The isolated test stack uses a deterministic scanner double. Production
# cannot select this backend (see Settings._validate_production_configuration).
os.environ.setdefault("MALWARE_SCANNER", "eicar-test")

from app.database.session import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import *  # noqa: E401, F403
from app.seed import seed_roles_and_permissions, seed_test_users  # noqa: E402

# Create test database engine
test_url = os.environ["DATABASE_URL"]
# Fail closed: this suite truncates nothing but writes freely, and the fixtures
# create and drop every table. Refuse anything that is not the dedicated test
# database on loopback, so a stray DATABASE_URL cannot reach development or
# production data.
if "school_portal_test" not in test_url or "localhost" not in test_url:
    raise RuntimeError(
        "Refusing to run tests against a non-test database: "
        f"{test_url.split('@')[-1]!r} is not localhost/school_portal_test*"
    )
# The reference portal keeps its test database on 5433. Never let the clone's
# suite create or drop tables there, even if an inherited environment variable
# points at it.
if ":5433" in test_url:
    raise RuntimeError(
        "Refusing to run tests against the reference PostgreSQL port 5433; "
        "use the isolated SYCUMAIN_V2 database on port 5434."
    )
TEST_DATABASE_URL = test_url
test_engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create test database tables once for all tests."""
    # Create all tables
    Base.metadata.create_all(bind=test_engine)
    yield
    # Drop all tables after all tests
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture(scope="session", autouse=True)
def seed_test_data(setup_test_database):
    """Seed test roles, permissions, and users once for all tests."""
    db = TestSessionLocal()
    try:
        seed_roles_and_permissions(db)
        seed_test_users(db)
    finally:
        db.close()


@pytest.fixture
def db_session(setup_test_database, seed_test_data):
    """Provide an isolated database session for each test.

    The application commits inside request handlers. Binding a plain session to
    an outer transaction is therefore not enough: those commits would end the
    outer transaction, the fixture's ``rollback()`` would become a no-op, and
    rows would leak into every later test — making the suite order-dependent
    and impossible to re-run after an interrupted run.

    ``join_transaction_mode="create_savepoint"`` makes each commit inside the
    application release a SAVEPOINT nested in the outer transaction instead.
    The outer rollback still discards everything, so every test starts from the
    same database state regardless of what ran before it.
    """
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session, seed_test_data):
    """Provide a FastAPI test client with database override."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def login_as(client: TestClient, email: str, password: str = "password123"):
    """Helper to login and return the response."""
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def get_auth_headers(client: TestClient, email: str, password: str = "password123"):
    """Helper to login and return cookies for subsequent requests."""
    response = login_as(client, email, password)
    if response.status_code == 200:
        # Cookies are automatically included in subsequent requests
        # when using the same TestClient instance
        return client.cookies
    return None
