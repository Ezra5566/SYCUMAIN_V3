"""Dormitory attendance: absences recorded against an institutional housing stay.

Revision ID: e5b2c8d4f7a1
Revises: c7d9e1f3a5b7

This table is the whole dormitory domain: an absence, the stay that made the
student eligible, the points Management entered, and the correction chain. There
is no presence row, no daily sheet and no derived percentage, so the module
cannot drift out of step with a job that failed to run.

Two integrity rules are enforced by the database rather than only by the service:

* ``uq_dormitory_absence_current`` makes a duplicate *current* absence for the
  same student, stay and date impossible even under concurrency. Superseded rows
  are outside the index, which is what lets a correction sit beside the record it
  replaced.
* ``dormitory_absence_guard`` proves the row is internally consistent: the stay
  belongs to the student, the stay is not cancelled, and the absence date falls
  inside the stay's effective period (inclusive, in UTC). A service check alone
  would leave the rule open to any other writer.

Nothing is backfilled. No existing housing, admission, attendance or audit row is
read or rewritten by this migration.

Downgrade refuses while any dormitory absence exists: these are institutional
records, and the documented rollback is to revert the release rather than discard
them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "e5b2c8d4f7a1"
down_revision: str | Sequence[str] | None = "c7d9e1f3a5b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "dormitory_absences"
GUARD = "dormitory_absence_guard"

GUARD_SQL = f"""
CREATE OR REPLACE FUNCTION {GUARD}() RETURNS trigger AS $$
DECLARE
    stay housing_assignments%ROWTYPE;
    owner_id uuid;
BEGIN
    SELECT user_id INTO owner_id FROM students WHERE id = NEW.student_id;
    IF owner_id IS NULL THEN
        RAISE EXCEPTION 'dormitory absence refers to an unknown student'
            USING ERRCODE = '23514';
    END IF;

    SELECT * INTO stay FROM housing_assignments WHERE id = NEW.housing_assignment_id;
    IF stay.id IS NULL THEN
        RAISE EXCEPTION 'dormitory absence refers to an unknown housing assignment'
            USING ERRCODE = '23514';
    END IF;
    IF stay.student_id <> owner_id THEN
        RAISE EXCEPTION 'housing assignment does not belong to the student'
            USING ERRCODE = '23514';
    END IF;
    IF stay.status = 'CANCELLED' THEN
        RAISE EXCEPTION 'housing assignment is cancelled'
            USING ERRCODE = '23514';
    END IF;
    IF NEW.absence_date < (stay.start_date AT TIME ZONE 'UTC')::date THEN
        RAISE EXCEPTION 'absence precedes the housing assignment'
            USING ERRCODE = '23514';
    END IF;
    IF stay.end_date IS NOT NULL
       AND NEW.absence_date > (stay.end_date AT TIME ZONE 'UTC')::date THEN
        RAISE EXCEPTION 'absence follows the housing assignment'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("student_id", _uuid(), nullable=False),
        sa.Column("housing_assignment_id", _uuid(), nullable=False),
        sa.Column("absence_date", sa.Date(), nullable=False),
        sa.Column("points", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recorded_by_id", _uuid(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("supersedes_id", _uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_dormitory_absence_student",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["housing_assignment_id"],
            ["housing_assignments.id"],
            name="fk_dormitory_absence_assignment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["users.id"],
            name="fk_dormitory_absence_recorded_by",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            [f"{TABLE}.id"],
            name="fk_dormitory_absence_supersedes",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "length(btrim(reason)) > 0", name="ck_dormitory_absence_reason"
        ),
        sa.CheckConstraint("points >= 0", name="ck_dormitory_absence_points"),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_dormitory_absence_supersedes",
        ),
    )

    op.create_index(f"ix_{TABLE}_student_id", TABLE, ["student_id"])
    op.create_index(f"ix_{TABLE}_assignment_id", TABLE, ["housing_assignment_id"])
    op.create_index(f"ix_{TABLE}_date", TABLE, ["absence_date"])
    op.create_index(
        "uq_dormitory_absence_current",
        TABLE,
        ["student_id", "housing_assignment_id", "absence_date"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.execute(GUARD_SQL)
    op.execute(
        f"CREATE TRIGGER trg_{TABLE}_guard "
        f"BEFORE INSERT OR UPDATE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION {GUARD}()"
    )


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
    if rows:
        raise RuntimeError(
            "Refusing to downgrade while dormitory attendance records exist "
            f"({rows} absence row(s)): these are institutional records. "
            "Revert the application release instead."
        )

    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_guard ON {TABLE}")
    op.execute(f"DROP FUNCTION IF EXISTS {GUARD}()")

    op.drop_index("uq_dormitory_absence_current", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_date", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_assignment_id", table_name=TABLE)
    op.drop_index(f"ix_{TABLE}_student_id", table_name=TABLE)
    op.drop_table(TABLE)
