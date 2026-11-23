"""Bulk student intake from a spreadsheet export.

The international office keeps its intake list in a spreadsheet, so CSV is the
format that actually exists on day one. This module is the boundary between
that file and the database, and it is deliberately strict:

* **Nothing is written until every row has been checked.** Unless the caller
  explicitly asks to skip bad rows, a single invalid row aborts the whole
  import, so a malformed file can never leave a half-created cohort behind.
* **Re-running is safe.** A row whose student number or email already exists is
  reported as *skipped* rather than duplicated. That is what makes a failed
  import re-runnable instead of a manual clean-up job.
* **Nothing is guessed.** Dates must be ISO (``YYYY-MM-DD``); an ambiguous
  ``01/02/2024`` is rejected rather than silently read as January or February.
* **Legacy placement columns are refused, not ignored.** A populated
  ``major_code``/``program_code``/``major_id``/``program_id``/
  ``program_offering_id`` row is rejected; admission and placement must be
  recorded through their authoritative workflows after the student exists.
* **Export is safe to open in Excel.** Values beginning with ``=``, ``+``,
  ``-`` or ``@`` are neutralised, because a student name is attacker-supplied
  text and a spreadsheet would otherwise execute it as a formula.

Every row that is created gets a one-time temporary password in the report. It
is never stored in plaintext and cannot be retrieved again.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func

from app.audit import record_audit
from app.config.settings import get_settings
from app.models.identity import Student, StudentStatus, User
from app.schemas.student import StudentImportReport, StudentImportRow, is_valid_email
from app.services.account import create_account

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session as DBSession

#: Columns that must exist in the uploaded file. Everything else is optional.
REQUIRED_COLUMNS: tuple[str, ...] = ("student_id", "first_name", "last_name", "email")

#: Header spellings the campus actually uses. Keys are normalized to lowercase
#: with single spaces; values are the canonical column names.
COLUMN_ALIASES: dict[str, str] = {
    "student number": "student_id",
    "student id": "student_id",
    "student no": "student_id",
    "studentno": "student_id",
    "number": "student_id",
    "first name": "first_name",
    "firstname": "first_name",
    "given name": "first_name",
    "last name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "family name": "last_name",
    "preferred name": "preferred_name",
    "nickname": "preferred_name",
    "email address": "email",
    "e mail": "email",
    "mail": "email",
    "date of birth": "date_of_birth",
    "dob": "date_of_birth",
    "birth date": "date_of_birth",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "nationality": "nationality",
    "country": "nationality",
    "country of origin": "nationality",
    "emergency contact": "emergency_contact_name",
    "emergency contact name": "emergency_contact_name",
    "emergency phone": "emergency_contact_phone",
    "emergency contact phone": "emergency_contact_phone",
}

EXPORT_COLUMNS: tuple[str, ...] = (
    "student_id",
    "first_name",
    "last_name",
    "preferred_name",
    "email",
    "date_of_birth",
    "gender",
    "nationality",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
    "status",
    "major_code",
    "program_code",
    "created_at",
)

#: Legacy spreadsheet columns that used to write the Student placement
#: projection directly. They are still recognised so a populated value can be
#: rejected explicitly; an empty value remains backward-compatible.
RETIRED_PLACEMENT_COLUMNS: tuple[str, ...] = (
    "major_id",
    "program_id",
    "program_offering_id",
    "major_code",
    "program_code",
)

#: Import templates deliberately omit placement columns. Phase 8a retires
#: direct projection writes, so an import creates the student/account only;
#: the first admission and placement are recorded through their own services.
TEMPLATE_COLUMNS: tuple[str, ...] = (
    "student_id",
    "first_name",
    "last_name",
    "preferred_name",
    "email",
    "date_of_birth",
    "gender",
    "nationality",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
)

#: A single example row so the template is self-explanatory.
TEMPLATE_EXAMPLE: tuple[str, ...] = (
    "STU-2026-001",
    "Wei",
    "Zhang",
    "",
    "wei.zhang@example.edu",
    "2004-05-12",
    "FEMALE",
    "China",
    "+86 138 0000 0000",
    "Li Zhang",
    "+86 139 0000 0000",
)

_ALLOWED_GENDERS = {"FEMALE", "MALE", "OTHER"}


class ImportFileError(ValueError):
    """The upload is not a usable student list.

    Carries a machine-readable code so the API can return a translatable error
    instead of an English sentence.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _Row:
    """A parsed row plus whatever validation concluded about it."""

    row_number: int
    values: dict[str, str]
    code: str | None = None
    message: str | None = None
    #: Duplicates are reported but do not block the rest of the file.
    skipped: bool = False
    #: Set by the write phase.
    created: bool = False
    temporary_password: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def invalid(self) -> bool:
        """True when this row must prevent the import (unless skipping)."""
        return self.code is not None and not self.skipped

    @property
    def number(self) -> str:
        return self.values.get("student_id", "")

    @property
    def name(self) -> str:
        return " ".join(
            part
            for part in (
                self.values.get("first_name", ""),
                self.values.get("last_name", ""),
            )
            if part
        )

    def fail(self, code: str, message: str) -> None:
        self.code = code
        self.message = message


def _normalize_header(name: str) -> str:
    """Map a spreadsheet header onto a canonical column name."""
    cleaned = " ".join(name.replace("_", " ").replace("-", " ").split()).lower()
    if cleaned in COLUMN_ALIASES:
        return COLUMN_ALIASES[cleaned]
    return cleaned.replace(" ", "_")


def _detect_dialect(sample: str) -> csv.Dialect:
    """Sniff the delimiter, falling back to comma.

    Excel in a comma-decimal locale writes semicolons; a file exported from a
    localised spreadsheet would otherwise parse as a single column and every
    row would be rejected for a missing student number.
    """
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def parse_rows(raw: bytes, *, max_rows: int) -> list[_Row]:
    """Decode and parse the upload, or raise :class:`ImportFileError`."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFileError(
            "IMPORT_ENCODING",
            "The file must be UTF-8 encoded CSV.",
        ) from exc

    if not text.strip():
        raise ImportFileError("IMPORT_EMPTY", "The file is empty.")

    dialect = _detect_dialect(text[:4096])
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    if not reader.fieldnames:
        raise ImportFileError(
            "IMPORT_MISSING_COLUMNS",
            "The file has no header row.",
        )

    mapping = {name: _normalize_header(name) for name in reader.fieldnames if name}
    present = set(mapping.values())
    missing = [column for column in REQUIRED_COLUMNS if column not in present]
    if missing:
        raise ImportFileError(
            "IMPORT_MISSING_COLUMNS",
            "The file is missing required column(s): " + ", ".join(missing) + ".",
        )

    rows: list[_Row] = []
    # `start=2` because line 1 is the header — the number a person sees in
    # their spreadsheet is the one that must appear in the error report.
    for line_number, raw_row in enumerate(reader, start=2):
        values = {
            mapping[key]: (value or "").strip()
            for key, value in raw_row.items()
            if key in mapping
        }
        if not any(values.values()):
            continue  # trailing blank line
        rows.append(_Row(row_number=line_number, values=values))
        if len(rows) > max_rows:
            raise ImportFileError(
                "IMPORT_TOO_MANY_ROWS",
                f"The file contains more than {max_rows} rows. Split it and import again.",
            )

    if not rows:
        raise ImportFileError("IMPORT_EMPTY", "The file contains no student rows.")

    return rows


def _validate_row(
    row: _Row,
    *,
    existing_numbers: set[str],
    existing_emails: set[str],
    seen_numbers: set[str],
    seen_emails: set[str],
) -> None:
    """Validate one row in place, recording the first blocking problem."""
    values = row.values

    for column in REQUIRED_COLUMNS:
        if not values.get(column):
            row.fail("MISSING_REQUIRED_FIELD", f"'{column}' is empty.")
            return

    retired_columns = [
        column
        for column in RETIRED_PLACEMENT_COLUMNS
        if values.get(column, "").strip()
    ]
    if retired_columns:
        row.fail(
            "IMPORT_PLACEMENT_COLUMNS_RETIRED",
            "Placement column(s) "
            + ", ".join(retired_columns)
            + " cannot be imported. Import the student without placement values, "
            "then record admission and placement through the admission/placement "
            "workflow.",
        )
        return

    number = values["student_id"]
    email = values["email"].strip().lower()

    if not is_valid_email(email):
        row.fail("INVALID_EMAIL", "That email address is not valid.")
        return

    if number in seen_numbers or email in seen_emails:
        row.fail("DUPLICATE_IN_FILE", "This row appears more than once in the file.")
        row.skipped = True
        return

    seen_numbers.add(number)
    seen_emails.add(email)

    # A duplicate is not a failure: the record is already there, which is the
    # intended end state of an import. It is reported so the operator can see
    # the file was applied rather than ignore a silent no-op.
    if number in existing_numbers:
        row.fail("DUPLICATE_STUDENT_NUMBER", "This student number already exists.")
        row.skipped = True
        return
    if email in existing_emails:
        row.fail("DUPLICATE_EMAIL", "An account with this email already exists.")
        row.skipped = True
        return

    birth = values.get("date_of_birth")
    if birth:
        try:
            # ISO only. 01/02/2024 is January in one country and February in
            # another, and a birth date is not a value worth guessing.
            row.extra["date_of_birth"] = datetime.strptime(birth, "%Y-%m-%d")
        except ValueError:
            row.fail(
                "INVALID_DATE_OF_BIRTH",
                "Use the format YYYY-MM-DD for the date of birth.",
            )
            return

    gender = values.get("gender", "").strip().upper()
    if gender and gender not in _ALLOWED_GENDERS:
        row.fail("INVALID_GENDER", "Gender must be FEMALE, MALE or OTHER.")
        return
    row.extra["gender"] = gender or None

    row.extra["email"] = email
    row.values["email"] = email


def import_students(
    db: DBSession,
    *,
    actor: User,
    raw: bytes,
    dry_run: bool = False,
    skip_invalid: bool = False,
    request: Any | None = None,
) -> StudentImportReport:
    """Validate (and optionally apply) a student intake file.

    Raises:
        ImportFileError: the upload is not a readable student list at all.
    """
    settings = get_settings()
    rows = parse_rows(raw, max_rows=settings.MAX_IMPORT_ROWS)

    numbers = {row.values["student_id"] for row in rows if row.values.get("student_id")}
    emails = {
        row.values["email"].strip().lower()
        for row in rows
        if row.values.get("email")
    }

    # Both lookups are single queries: a 500-row file must not become 1000
    # round trips, and a slow import is the one operators retry blindly.
    existing_numbers = (
        {
            value
            for (value,) in db.query(Student.student_id)
            .filter(Student.student_id.in_(numbers))
            .all()
        }
        if numbers
        else set()
    )
    existing_emails = (
        {
            value.lower()
            for (value,) in db.query(User.email)
            .filter(func.lower(User.email).in_(emails))
            .all()
        }
        if emails
        else set()
    )

    seen_numbers: set[str] = set()
    seen_emails: set[str] = set()
    for row in rows:
        _validate_row(
            row,
            existing_numbers=existing_numbers,
            existing_emails=existing_emails,
            seen_numbers=seen_numbers,
            seen_emails=seen_emails,
        )

    failed = [row for row in rows if row.invalid]
    # Fail closed: if anything is wrong, write nothing. The caller must opt in
    # to "import what is valid", because that decision is theirs, not ours.
    aborted = bool(failed) and not skip_invalid and not dry_run

    if not dry_run and not aborted:
        try:
            for row in rows:
                if row.invalid or row.skipped:
                    continue
                user, temporary_password = create_account(
                    db,
                    email=row.values["email"],
                    full_name=row.name,
                    roles=["STUDENT"],
                    must_change_password=True,
                )
                student = Student(
                    user_id=user.id,
                    student_id=row.values["student_id"],
                    first_name=row.values["first_name"],
                    last_name=row.values["last_name"],
                    preferred_name=row.values.get("preferred_name") or None,
                    date_of_birth=row.extra.get("date_of_birth"),
                    gender=row.extra.get("gender"),
                    nationality=row.values.get("nationality") or None,
                    phone=row.values.get("phone") or None,
                    emergency_contact_name=row.values.get("emergency_contact_name")
                    or None,
                    emergency_contact_phone=row.values.get("emergency_contact_phone")
                    or None,
                    # Placement columns never write this projection. Populated
                    # values were rejected during validation; only the
                    # admission/placement services may set placement.
                    status=StudentStatus.ACTIVE,
                )
                db.add(student)
                db.flush()
                row.created = True
                row.temporary_password = temporary_password

            created = sum(1 for row in rows if row.created)
            record_audit(
                db,
                action="student.imported",
                actor=actor,
                entity_type="student",
                context={
                    "created": created,
                    "skipped": sum(1 for row in rows if row.skipped),
                    "failed": len(failed),
                    "dry_run": False,
                },
                request=request,
            )
            # One commit for the whole file: either the cohort exists or none
            # of it does, which is what makes the result explainable.
            db.commit()
        except Exception:
            db.rollback()
            raise

    return StudentImportReport(
        dry_run=dry_run,
        aborted=aborted,
        total=len(rows),
        valid=sum(1 for row in rows if not row.invalid and not row.skipped),
        created=sum(1 for row in rows if row.created),
        skipped=sum(1 for row in rows if row.skipped),
        failed=len(failed),
        rows=[
            StudentImportRow(
                row_number=row.row_number,
                student_number=row.number or None,
                name=row.name or None,
                status=(
                    "ERROR"
                    if row.invalid
                    else "CREATED"
                    if row.created
                    else "SKIPPED"
                    if row.skipped
                    else "VALID"
                ),
                code=row.code,
                message=row.message,
                temporary_password=row.temporary_password,
            )
            for row in rows
        ],
    )


def _csv_safe(value: object) -> str:
    """Neutralise spreadsheet formula injection.

    A student's name is free text supplied by whoever filled in the form. Excel
    executes a cell beginning with ``=``, ``+``, ``-`` or ``@``, so an exported
    file must not carry such a value verbatim.
    """
    if value is None:
        return ""
    text = str(value)
    if text[:1] in {"=", "+", "-", "@", "\t", "\r"}:
        return "'" + text
    return text


def build_export_csv(
    students: Sequence[Student],
    academic_by_student: dict[uuid.UUID, Any],
) -> str:
    """Render students as a spreadsheet-safe CSV document."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)

    for student in students:
        writer.writerow(
            [
                _csv_safe(student.student_id),
                _csv_safe(student.first_name),
                _csv_safe(student.last_name),
                _csv_safe(student.preferred_name),
                _csv_safe(student.user.email if student.user else None),
                _csv_safe(
                    student.date_of_birth.date().isoformat()
                    if student.date_of_birth
                    else None
                ),
                _csv_safe(student.gender),
                _csv_safe(student.nationality),
                _csv_safe(student.phone),
                _csv_safe(student.emergency_contact_name),
                _csv_safe(student.emergency_contact_phone),
                # `status` reads back as a plain string from the column, so it
                # may not have `.value`; `getattr` covers both shapes.
                _csv_safe(getattr(student.status, "value", student.status)),
                _csv_safe(
                    academic_by_student[student.id].major.code
                    if academic_by_student.get(student.id)
                    and academic_by_student[student.id].major
                    else None
                ),
                _csv_safe(
                    academic_by_student[student.id].program.code
                    if academic_by_student.get(student.id)
                    and academic_by_student[student.id].program
                    else None
                ),
                _csv_safe(
                    student.created_at.isoformat(timespec="seconds")
                    if student.created_at
                    else None
                ),
            ]
        )

    return buffer.getvalue()


def build_template_csv() -> str:
    """Return the exact header the importer expects, plus one example row."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerow(TEMPLATE_EXAMPLE)
    return buffer.getvalue()


__all__ = [
    "ImportFileError",
    "build_export_csv",
    "build_template_csv",
    "import_students",
    "parse_rows",
]
