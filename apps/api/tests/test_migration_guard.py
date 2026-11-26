"""The migration target guard must fail closed.

The failure this prevents is concrete: ``alembic`` run from a host shell with no
``DATABASE_URL`` fell back to the default that points at the V1 reference
database, and would have advanced *its* schema. The guard therefore refuses a
target it cannot prove is the V3 database, before a single statement is issued.

These tests never connect to V1. The V1 refusal is proven from the URL, and the
runtime identity check is proven against the isolated pytest database.
"""

from __future__ import annotations

import pytest

from app.database.migration_guard import (
    MigrationTargetError,
    check_migration_target,
    verify_runtime_identity,
)

DEV_URL = "postgresql://portal:portal@localhost:5435/school_portal_v2"
V1_URL = "postgresql://portal:portal@localhost:5433/school_portal"


def test_v3_development_database_is_accepted() -> None:
    target = check_migration_target(DEV_URL, "development")
    assert target.database == "school_portal_v2"
    assert target.port == 5435


@pytest.mark.parametrize(
    "url",
    [
        V1_URL,
        # Same name, different host/port: the name is the identity, not the port.
        "postgresql://portal:portal@db.internal:5432/school_portal",
    ],
)
def test_v1_reference_database_is_rejected(url: str) -> None:
    with pytest.raises(MigrationTargetError) as excinfo:
        check_migration_target(url, "development")
    assert "V1 reference" in str(excinfo.value)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://portal:portal@localhost:5435/other_portal",
        "postgresql://portal:portal@localhost:5435/",
        "postgresql://portal:portal@localhost:5435/postgres",
        "postgresql://portal:portal@localhost:5435/template1",
    ],
)
def test_unexpected_database_identity_is_rejected(url: str) -> None:
    with pytest.raises(MigrationTargetError):
        check_migration_target(url, "development")


@pytest.mark.parametrize("url", ["", "   ", None])
def test_missing_configuration_is_rejected(url: str | None) -> None:
    with pytest.raises(MigrationTargetError) as excinfo:
        check_migration_target(url, "development")
    assert "DATABASE_URL is not set" in str(excinfo.value)


def test_non_postgresql_url_is_rejected() -> None:
    with pytest.raises(MigrationTargetError):
        check_migration_target("sqlite:///./local.db", "development")


def test_production_requires_an_explicit_confirmation() -> None:
    with pytest.raises(MigrationTargetError) as excinfo:
        check_migration_target(
            "postgresql://portal:secret@db.internal:5432/sycumain_prod",
            "production",
        )
    assert "MIGRATION_CONFIRM is required" in str(excinfo.value)


def test_production_rejects_a_mismatched_confirmation() -> None:
    with pytest.raises(MigrationTargetError) as excinfo:
        check_migration_target(
            "postgresql://portal:secret@db.internal:5432/sycumain_prod",
            "production",
            confirm="school_portal_v2",
        )
    assert "does not match" in str(excinfo.value)


def test_approved_production_configuration_is_accepted() -> None:
    """A production database does not have to follow the development naming."""
    target = check_migration_target(
        "postgresql://portal:secret@db.internal:5432/sycumain_prod",
        "production",
        confirm="sycumain_prod",
    )
    assert target.database == "sycumain_prod"


def test_production_still_refuses_v1_even_when_confirmed() -> None:
    with pytest.raises(MigrationTargetError):
        check_migration_target(V1_URL, "production", confirm="school_portal")


def test_allowed_databases_escape_hatch() -> None:
    target = check_migration_target(
        "postgresql://portal:portal@localhost:5440/school_portal_perf",
        "development",
    )
    assert target.database == "school_portal_perf"

    with pytest.raises(MigrationTargetError):
        check_migration_target(
            "postgresql://portal:portal@localhost:5439/rehearsal_db",
            "development",
        )

    target = check_migration_target(
        "postgresql://portal:portal@localhost:5439/rehearsal_db",
        "development",
        allowed=["rehearsal_db"],
    )
    assert target.database == "rehearsal_db"


def test_runtime_identity_matches_the_configured_target() -> None:
    from tests.conftest import TEST_DATABASE_URL

    target = check_migration_target(
        TEST_DATABASE_URL, "testing", allowed=["school_portal_test_v2"]
    )
    from sqlalchemy import create_engine

    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            # No revision set supplied: only the name check is exercised here.
            verify_runtime_identity(connection, target)
    finally:
        engine.dispose()


def test_foreign_alembic_revision_is_rejected() -> None:
    """A database stamped by another application is not a V3 database."""
    from sqlalchemy import create_engine

    from tests.conftest import TEST_DATABASE_URL

    target = check_migration_target(
        TEST_DATABASE_URL, "testing", allowed=["school_portal_test_v2"]
    )
    engine = create_engine(TEST_DATABASE_URL)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.exec_driver_sql(
                "CREATE TABLE alembic_version ("
                "version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "INSERT INTO alembic_version (version_num) VALUES ('c7d9e1f3a5b7')"
            )
            with pytest.raises(MigrationTargetError) as excinfo:
                verify_runtime_identity(
                    connection, target, known_revisions=["d1e4a7b9c2f5"]
                )
            assert "different application" in str(excinfo.value)
            transaction.rollback()
    finally:
        engine.dispose()
