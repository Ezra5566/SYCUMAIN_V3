"""Alembic environment configuration."""

import os
import sys
from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import engine_from_config, pool

# Add the project root to sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config.settings import get_settings
from app.database.migration_guard import (
    check_migration_target,
    verify_runtime_identity,
)
from app.database.session import Base

# Import all models so Alembic can detect them
from app.models import *  # noqa: F401, F403

config = context.config
settings = get_settings()

# Override sqlalchemy.url from environment
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _csv(name: str) -> list[str]:
    """Read a comma-separated environment variable."""
    return [part for part in os.environ.get(name, "").split(",") if part.strip()]


# Fail closed before any connection is opened. The Phase 9 assessment found that
# a host-run `alembic` with no DATABASE_URL in the environment fell back to the
# V1 reference database on port 5433. This call makes that an immediate, explicit
# refusal instead of a schema change on the wrong installation. See
# app/database/migration_guard.py for the rules and the stated limits.
_MIGRATION_TARGET = check_migration_target(
    settings.DATABASE_URL,
    settings.ENVIRONMENT,
    confirm=os.environ.get("MIGRATION_CONFIRM"),
    allowed=_csv("MIGRATION_ALLOWED_DATABASES"),
)


def _known_revisions() -> set[str]:
    """Every revision id this repository defines."""
    script = ScriptDirectory.from_config(config)
    return {revision.revision for revision in script.walk_revisions()}


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Second, independent check: the database that actually answered must be
        # the one the URL named, and must not already carry a foreign Alembic
        # stamp (V1's head, for example). Runs before any DDL.
        verify_runtime_identity(
            connection,
            _MIGRATION_TARGET,
            known_revisions=sorted(_known_revisions()),
        )
        # SQLAlchemy 2.0 begins a transaction implicitly on the first statement.
        # If it is left open, Alembic's `begin_transaction()` sees an active
        # transaction, opens a SAVEPOINT inside it, and commits only the
        # SAVEPOINT — the outer transaction is then rolled back when the
        # connection closes. The migration would log success and change nothing
        # (this was observed while adding the Phase 10 revision). Ending the
        # read-only verification transaction first makes Alembic own the whole
        # transaction, which is what commits the DDL.
        connection.rollback()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
