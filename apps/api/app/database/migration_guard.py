"""Fail-closed identity check before Alembic touches a database.

The Phase 9 assessment found a working configuration that could migrate the
**V1 reference database**: ``alembic`` run from the host, with no ``DATABASE_URL``
in the environment, fell back to the default ``postgresql://portal:portal@
localhost:5433/school_portal`` — the V1 stack — and would have advanced its
schema. Running the wrong migration against the reference installation is the
single most damaging mistake available in this repository, so the target is now
verified twice: statically, from the connection URL, and at runtime, from the
database that actually answered.

What is checked
---------------
1. A URL is present and is a PostgreSQL URL with a database name. A missing or
   unparseable configuration is refused rather than defaulted.
2. The name is not a known foreign target. ``school_portal`` is the V1
   reference database and is always refused; so are the PostgreSQL system
   databases.
3. The environment designates the target explicitly:
   * **development / testing / anything non-production** — the name must belong
     to the V3 family (``school_portal_*``) or be listed in
     ``MIGRATION_ALLOWED_DATABASES``. This preserves the development, pytest,
     e2e and performance workflows, whose names are fixed in Compose.
   * **production** — ``MIGRATION_CONFIRM`` must name the database exactly. A
     production database does not have to follow this project's development
     naming, so an operator states the target instead of it being inferred.
     Without that confirmation the migration refuses to run.
4. Runtime, after connecting: ``current_database()`` must be the database the
   URL named (so pooling/proxy indirection cannot silently retarget the
   session), and any recorded ``alembic_version`` must be a revision this
   application knows. The V1 revision ``c7d9e1f3a5b7`` is not in this
   repository, so a V1 database that somehow passed the name check is refused
   before a single statement is issued.

Port numbers are deliberately **not** the basis of the decision: they are
routinely remapped, and a guard that trusts ``5435`` would fail the first time
a host maps the stack somewhere else. The port is recorded in the resulting
target object only for logging.

The check raises :class:`MigrationTargetError`; the Alembic environment does not
catch it, so the migration job exits non-zero and nothing is written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.engine import make_url

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from sqlalchemy.engine import Connection


class MigrationTargetError(RuntimeError):
    """Raised when a migration target cannot be proven to be the V3 database."""


#: Databases this project must never migrate. ``school_portal`` is the V1
#: reference installation; the rest are PostgreSQL internals.
FORBIDDEN_DATABASES: frozenset[str] = frozenset(
    {"school_portal", "postgres", "template0", "template1"}
)

#: Every V3 database is named ``school_portal_<something>``: ``school_portal_v2``
#: (development), ``school_portal_test_v2`` (pytest), ``school_portal_e2e``,
#: ``school_portal_perf``, and disposable ``school_portal_restore*``/``_scratch*``
#: databases used by rehearsals. V1's database is exactly ``school_portal``,
#: which the pattern cannot match because the suffix is mandatory.
V3_DATABASE_PATTERN = re.compile(r"^school_portal_[a-z0-9_]+$")


@dataclass(frozen=True)
class MigrationTarget:
    """A verified migration target."""

    database: str
    host: str | None
    port: int | None
    environment: str

    def describe(self) -> str:
        """A log-safe description (no user, no password)."""
        return f"{self.host or '?'}:{self.port or '?'}/{self.database}"


def _normalise(names: Iterable[str] | None) -> frozenset[str]:
    if not names:
        return frozenset()
    return frozenset(name.strip().lower() for name in names if name and name.strip())


def check_migration_target(
    url: str | None,
    environment: str,
    *,
    confirm: str | None = None,
    allowed: Iterable[str] | None = None,
) -> MigrationTarget:
    """Return the verified target, or raise :class:`MigrationTargetError`.

    Args:
        url: the configured database URL (``settings.DATABASE_URL``).
        environment: ``development``, ``testing``, ``production``, ``e2e``...
        confirm: ``MIGRATION_CONFIRM``; required in production, where it must
            name the database exactly.
        allowed: ``MIGRATION_ALLOWED_DATABASES``; extra names accepted outside
            production (a disposable rehearsal database, for example).
    """
    if not url or not str(url).strip():
        raise MigrationTargetError(
            "DATABASE_URL is not set. Refusing to migrate: without it Alembic "
            "would fall back to a default that points at another installation."
        )

    try:
        parsed = make_url(url)
    except Exception as exc:  # noqa: BLE001 - any parse failure is a refusal
        raise MigrationTargetError(
            "DATABASE_URL is not a valid database URL. Refusing to migrate."
        ) from exc

    if not parsed.drivername.startswith("postgresql"):
        raise MigrationTargetError(
            f"DATABASE_URL uses driver {parsed.drivername!r}; only PostgreSQL is "
            "supported for this schema. Refusing to migrate."
        )

    database = (parsed.database or "").strip()
    if not database:
        raise MigrationTargetError(
            "DATABASE_URL does not name a database. Refusing to migrate an "
            "ambiguous target."
        )

    lowered = database.lower()
    if lowered in FORBIDDEN_DATABASES:
        if lowered == "school_portal":
            raise MigrationTargetError(
                "Refusing to migrate database 'school_portal': that is the V1 "
                "reference installation. V3 migrations must run against "
                "'school_portal_v2' (development) or the database named in "
                "MIGRATION_CONFIRM (production)."
            )
        raise MigrationTargetError(
            f"Refusing to migrate the PostgreSQL system database {database!r}."
        )

    permitted = _normalise(allowed)
    is_production = environment.strip().lower() == "production"

    if is_production:
        confirmed = (confirm or "").strip()
        if not confirmed:
            raise MigrationTargetError(
                "MIGRATION_CONFIRM is required when ENVIRONMENT=production: it "
                "must name the database to migrate, so the target is stated "
                "rather than inferred."
            )
        if confirmed != database:
            raise MigrationTargetError(
                "MIGRATION_CONFIRM does not match the database in DATABASE_URL "
                f"({confirmed!r} != {database!r}). Refusing to migrate."
            )
    elif lowered not in permitted and not V3_DATABASE_PATTERN.match(lowered):
        raise MigrationTargetError(
            f"Refusing to migrate unexpected database {database!r}. Expected a "
            "V3 database named 'school_portal_*', or the name listed in "
            "MIGRATION_ALLOWED_DATABASES."
        )

    return MigrationTarget(
        database=database,
        host=parsed.host,
        port=parsed.port,
        environment=environment,
    )


def verify_runtime_identity(
    connection: Connection,
    target: MigrationTarget,
    *,
    known_revisions: Sequence[str] | None = None,
) -> None:
    """Confirm the connected database is the one the URL named, and is a V3 one.

    Raises :class:`MigrationTargetError` on any mismatch. Must be called inside
    the same connection that will run the migration, before it runs.
    """
    actual = connection.exec_driver_sql("SELECT current_database()").scalar_one()
    if actual != target.database:
        raise MigrationTargetError(
            "Connected database does not match the configured target "
            f"({actual!r} != {target.database!r}). Refusing to migrate."
        )

    if not known_revisions:
        return

    recorded = connection.exec_driver_sql(
        "SELECT version_num FROM alembic_version"
        if _has_alembic_version(connection)
        else "SELECT NULL WHERE false"
    ).scalars().all()

    unknown = sorted(
        revision
        for revision in recorded
        if revision is not None and revision not in set(known_revisions)
    )
    if unknown:
        raise MigrationTargetError(
            "The database was migrated by a different application: its "
            f"alembic_version {unknown[0]!r} is not a revision in this "
            "repository. Refusing to migrate — this is not a V3 database."
        )


def _has_alembic_version(connection: Connection) -> bool:
    """Whether the connection's database already carries an Alembic stamp."""
    present = connection.exec_driver_sql(
        "SELECT to_regclass('alembic_version') IS NOT NULL"
    ).scalar_one()
    return bool(present)


__all__ = [
    "FORBIDDEN_DATABASES",
    "MigrationTarget",
    "MigrationTargetError",
    "V3_DATABASE_PATTERN",
    "check_migration_target",
    "verify_runtime_identity",
]
