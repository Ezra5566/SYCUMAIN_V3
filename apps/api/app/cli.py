"""Operational command line.

    python -m app.cli bootstrap-admin     # create the first administrator
    python -m app.cli retention-report    # read-only retention inventory
    python -m app.cli purge-expired       # delete expired operational rows

``bootstrap-admin`` exists because production deliberately does not seed the
demo accounts: without it a fresh production database has roles and permissions
but nobody who can sign in. It issues a *temporary* password that must be
changed on first sign-in, and it prints that password once.

Nothing here deletes student, document or audit data. Retention periods are an
institutional decision (see docs/data-lifecycle.md); this command reports what
would fall inside them and leaves the decision — and the two-person approval —
to the institution.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.auth.service import cleanup_expired_sessions
from app.config.settings import get_settings
from app.core.ratelimit import purge_expired as purge_rate_limits
from app.database.session import SessionLocal
from app.models.academic import AcademicPeriod, Program
from app.models.audit import AuditLog
from app.models.identity import Role, Student, StudentStatus, User
from app.models.platform import Document, DocumentStatus
from app.models.session import PasswordResetToken
from app.services.academic_import import (
    DEFAULT_SOURCE,
    apply_import,
    prepare_import,
    rollback_batch,
)
from app.services.account import AccountError, create_account
from app.services.mailer import email_configured, flush_outbox


def bootstrap_admin(args: argparse.Namespace) -> int:
    """Create the first administrator account."""
    settings = get_settings()
    email = (args.email or settings.BOOTSTRAP_ADMIN_EMAIL or "").strip().lower()
    if not email:
        print(
            "ERROR: no administrator email given. Pass --email or set "
            "BOOTSTRAP_ADMIN_EMAIL.",
            file=sys.stderr,
        )
        return 2

    db = SessionLocal()
    try:
        existing_admins = (
            db.query(User)
            .join(User.roles)
            .filter(Role.name == "ADMIN")
            .count()
        )
        if existing_admins and not args.force:
            print(
                f"Refusing to run: {existing_admins} administrator account(s) "
                "already exist. Use --force only if you know why this is needed.",
                file=sys.stderr,
            )
            return 1

        try:
            user, temporary_password = create_account(
                db,
                email=email,
                full_name=args.name or "Portal Administrator",
                roles=["ADMIN"],
                password=args.password,
                # A bootstrap credential is a temporary credential. Even an
                # explicitly supplied password must be replaced on first use.
                must_change_password=True,
            )
        except AccountError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

        db.commit()
        # Read the id before the session closes: a commit expires attributes,
        # and refreshing one after `close()` raises DetachedInstanceError.
        created_id = user.id
    finally:
        db.close()

    print(f"Created administrator {email} (id {created_id}).")
    if temporary_password:
        print("Temporary password (shown once, must be changed at first sign-in):")
        print(f"  {temporary_password}")
    else:
        print("A password was supplied and must be changed at first sign-in.")
    return 0


def _years_ago(years: int | None) -> datetime | None:
    if not years:
        return None
    return datetime.now(UTC) - timedelta(days=365 * years)


def retention_report(_: argparse.Namespace) -> int:
    """Print what falls inside each configured retention period."""
    settings = get_settings()

    periods = {
        "GRADUATED": settings.RETENTION_GRADUATED_YEARS,
        "WITHDRAWN": settings.RETENTION_WITHDRAWN_YEARS,
        "INACTIVE": settings.RETENTION_INACTIVE_YEARS,
    }

    db = SessionLocal()
    try:
        print("Retention report (read-only: nothing is deleted by this command)")
        print()

        any_configured = False
        for status, years in periods.items():
            if not years:
                print(f"  students/{status:<10} retention not configured (pending approval)")
                continue
            any_configured = True
            cutoff = _years_ago(years)
            count = (
                db.query(Student)
                .filter(
                    Student.status == StudentStatus[status],
                    Student.updated_at < cutoff,
                )
                .count()
            )
            print(
                f"  students/{status:<10} older than {years}y: {count}"
            )

        document_cutoff = _years_ago(settings.RETENTION_DOCUMENT_YEARS)
        if document_cutoff is None:
            print("  documents            retention not configured (pending approval)")
        else:
            any_configured = True
            count = (
                db.query(Document)
                .filter(
                    Document.status == DocumentStatus.ARCHIVED,
                    Document.updated_at < document_cutoff,
                )
                .count()
            )
            print(
                f"  documents            archived longer than "
                f"{settings.RETENTION_DOCUMENT_YEARS}y: {count}"
            )

        audit_cutoff = _years_ago(settings.RETENTION_AUDIT_YEARS)
        if audit_cutoff is None:
            print("  audit_logs           retention not configured (pending approval)")
        else:
            any_configured = True
            count = db.query(AuditLog).filter(AuditLog.created_at < audit_cutoff).count()
            print(
                f"  audit_logs           older than "
                f"{settings.RETENTION_AUDIT_YEARS}y: {count}"
            )

        print()
        print(f"  audit rows in total: {db.query(func.count(AuditLog.id)).scalar()}")
        if not any_configured:
            print()
            print(
                "No retention period is configured, so no record is a deletion "
                "candidate. Set the RETENTION_* variables once the institution "
                "has approved the policy."
            )
    finally:
        db.close()
    return 0


def purge_expired(args: argparse.Namespace) -> int:
    """Delete expired *operational* rows.

    Scope is deliberately narrow: session rows, spent or expired reset tokens,
    and closed rate-limit windows. These carry no institutional record value,
    so removing them is housekeeping rather than data destruction.
    """
    if not args.confirm:
        print(
            "Refusing to run without --confirm (this deletes rows).",
            file=sys.stderr,
        )
        return 2

    db = SessionLocal()
    try:
        sessions = cleanup_expired_sessions(db)
        tokens = (
            db.query(PasswordResetToken)
            .filter(
                (PasswordResetToken.expires_at < datetime.now(UTC))
                | (PasswordResetToken.used_at.isnot(None))
            )
            .delete(synchronize_session=False)
        )
        windows = purge_rate_limits(db, older_than_hours=args.older_than_hours)
        db.commit()
    finally:
        db.close()

    print(
        f"Removed {sessions} expired session(s), {tokens} spent/expired reset "
        f"token(s), {windows} closed rate-limit window(s)."
    )
    return 0


def _resolve_period_id(db, value: str):
    """Accept an academic-period UUID or its operational code."""
    import uuid

    try:
        return uuid.UUID(value)
    except ValueError:
        period = (
            db.query(AcademicPeriod)
            .filter(AcademicPeriod.code == value)
            .first()
        )
        if period is None:
            raise SystemExit(f"Unknown academic period: {value}") from None
        return period.id


def _resolve_program_id(db, value: str):
    """Accept a program UUID or its code for explicit source mapping."""
    import uuid

    try:
        return uuid.UUID(value)
    except ValueError:
        program = db.query(Program).filter(Program.code == value).first()
        if program is None:
            raise SystemExit(f"Unknown program: {value}") from None
        return program.id


def _pairs(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Expected SOURCE=TARGET, got: {value}")
        source, target = value.split("=", 1)
        if not source.strip() or not target.strip():
            raise SystemExit(f"Expected SOURCE=TARGET, got: {value}")
        result[source.strip()] = target.strip()
    return result


def academic_import(args: argparse.Namespace) -> int:
    """Dry-run, apply or roll back the staged academic timetable import."""
    db = SessionLocal()
    try:
        if args.import_command == "prepare":
            result = prepare_import(db, args.source or DEFAULT_SOURCE)
            print("Prepared import batch (no academic rows written):")
            for key, value in result.items():
                print(f"  {key}: {value}")
            return 0

        if args.import_command == "apply":
            period_map = {
                source: str(_resolve_period_id(db, target))
                for source, target in _pairs(args.period or []).items()
            }
            program_map = {
                source: str(_resolve_program_id(db, target))
                for source, target in _pairs(args.program or []).items()
            }
            import uuid as _uuid

            result = apply_import(
                db,
                _uuid.UUID(args.batch),
                period_map=period_map,
                parent_program_map=program_map,
            )
            print(f"Import {result['status'].lower()}:")
            for key, value in result.items():
                print(f"  {key}: {value}")
            return 0

        import uuid as _uuid

        result = rollback_batch(db, _uuid.UUID(args.batch))
        print(f"Import {result['status'].lower()}:")
        for key, value in result.items():
            print(f"  {key}: {value}")
        return 0
    finally:
        db.close()


def send_emails(args: argparse.Namespace) -> int:
    """Send queued notification email, with bounded retries.

    Designed for cron or a platform scheduler: every run is safe, and a second
    run cannot send a message that already went out.
    """
    if not email_configured():
        print(
            "Email delivery is not configured (EMAIL_ENABLED/SMTP_HOST). "
            "Nothing was sent; queued messages are kept.",
            file=sys.stderr,
        )
        return 2

    db = SessionLocal()
    try:
        result = flush_outbox(db, limit=args.limit)
    finally:
        db.close()

    print("Email delivery:")
    for key in ("due", "sent", "retrying", "failed"):
        print(f"  {key}: {result[key]}")
    # A permanent failure is an operator problem (credentials, relay policy),
    # so the command exits non-zero and a scheduler can alert on it.
    return 1 if result["failed"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser(
        "bootstrap-admin", help="create the first administrator account"
    )
    bootstrap.add_argument("--email", help="administrator email address")
    bootstrap.add_argument("--name", help="full name to display")
    bootstrap.add_argument(
        "--password",
        help="password to set (still must be changed at first sign-in)",
    )
    bootstrap.add_argument(
        "--force", action="store_true", help="create another administrator anyway"
    )
    bootstrap.set_defaults(func=bootstrap_admin)

    report = sub.add_parser(
        "retention-report", help="show records inside configured retention periods"
    )
    report.set_defaults(func=retention_report)

    mail = sub.add_parser(
        "send-emails", help="send queued notification email with bounded retries"
    )
    mail.add_argument("--limit", type=int, default=100, help="maximum messages per run")
    mail.set_defaults(func=send_emails)

    purge = sub.add_parser("purge-expired", help="delete expired operational rows")
    purge.add_argument("--confirm", action="store_true", help="required to delete")
    purge.add_argument(
        "--older-than-hours", type=int, default=24, help="rate-limit window age"
    )
    purge.set_defaults(func=purge_expired)

    academic = sub.add_parser(
        "academic-import",
        help="stage, apply or roll back the authoritative timetable source",
    )
    academic_sub = academic.add_subparsers(
        dest="import_command", required=True
    )
    prepare = academic_sub.add_parser(
        "prepare", help="stage a source file without writing academic rows"
    )
    prepare.add_argument(
        "--source",
        help=f"source JSON (default: {DEFAULT_SOURCE})",
    )
    prepare.set_defaults(func=academic_import)

    for name, help_text in (
        ("apply", "apply mapped rows from a prepared batch"),
        ("rollback", "remove rows owned by an applied batch"),
    ):
        command = academic_sub.add_parser(name, help=help_text)
        command.add_argument("--batch", required=True, help="import batch UUID")
        if name == "apply":
            command.add_argument(
                "--period",
                action="append",
                default=[],
                metavar="SOURCE=PERIOD",
                help="map source semester id to an existing period UUID or code",
            )
            command.add_argument(
                "--program",
                action="append",
                default=[],
                metavar="SOURCE_OFFERING=PROGRAM",
                help="map a source offering id to a canonical program UUID or code",
            )
        command.set_defaults(func=academic_import)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
