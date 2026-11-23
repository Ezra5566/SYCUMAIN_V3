"""Controlled housing import from the registrar's spreadsheet.

The housing office already holds bed allocations in a spreadsheet. This module
turns that file into assignments **without ever guessing**:

* **Structure is resolved, never invented.** A row must name a building, floor,
  room and bed that already exist. An import cannot silently create a building
  called "Block 18 " because the source spelled it differently; the row is
  reported as an unresolved reference instead.
* **Nothing is written until every row has been checked.** A file with any
  invalid row is refused as a whole, so a bad reference cannot leave a partially
  imported cohort behind.
* **Existing occupants are never overwritten.** A bed that is already taken, or
  a student who is already housed, is reported as a conflict and skipped. The
  import never performs a silent transfer; that is a deliberate operational
  decision made through the transfer workflow, which records who moved whom.
* **Re-running is safe.** Once a row has been applied, importing the same file
  again reports the same rows as skipped conflicts instead of duplicating them.
* **One transaction.** All assignments in a batch commit together; a failure
  rolls the whole batch back.

Dates must be ISO (``YYYY-MM-DD``). An ambiguous ``01/02/2024`` is rejected
rather than read as either January or February.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING, Any

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.models.housing import (
    Bed,
    Building,
    Floor,
    HousingAssignment,
    HousingAssignmentStatus,
    Room,
    RoomStatus,
)
from app.models.identity import Student
from app.schemas.housing import HousingImportReport, HousingImportRow

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from sqlalchemy.orm import Session as DBSession

#: Columns that must exist in the uploaded file.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "student_id",
    "building",
    "floor",
    "room",
    "bed",
    "start_date",
)

#: The template the housing office downloads. `end_date` is accepted on import
#: but is not something the office knows when it sends the file.
TEMPLATE_COLUMNS: tuple[str, ...] = (
    "student_id",
    "building",
    "floor",
    "room",
    "bed",
    "start_date",
    "end_date",
    "notes",
)

#: Header spellings the campus actually uses.
COLUMN_ALIASES: dict[str, str] = {
    "student number": "student_id",
    "student id": "student_id",
    "student no": "student_id",
    "studentno": "student_id",
    "number": "student_id",
    "matriculation": "student_id",
    "building name": "building",
    "block": "building",
    "dorm": "building",
    "dormitory": "building",
    "floor number": "floor",
    "level": "floor",
    "room number": "room",
    "room no": "room",
    "bed number": "bed",
    "bed no": "bed",
    "bed label": "bed",
    "check in": "start_date",
    "checkin": "start_date",
    "start": "start_date",
    "check out": "end_date",
    "checkout": "end_date",
    "end": "end_date",
    "note": "notes",
}

#: Row outcomes the report can carry.
STATUS_VALID = "VALID"
STATUS_CREATED = "CREATED"
STATUS_SKIPPED = "SKIPPED"
STATUS_ERROR = "ERROR"


class ImportFileError(Exception):
    """The uploaded file cannot be read at all.

    Separate from a row error: no row can be reported because there is no
    readable table, so the UI shows this as a file-level failure.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _ParsedRow:
    """One row of the file, still unvalidated against the database."""

    row_number: int
    values: dict[str, str] = field(default_factory=dict)


def _normalize_header(name: str) -> str:
    cleaned = " ".join(name.replace("_", " ").replace("-", " ").split()).lower()
    if cleaned in COLUMN_ALIASES:
        return COLUMN_ALIASES[cleaned]
    return cleaned.replace(" ", "_")


def _detect_dialect(sample: str) -> csv.Dialect:
    """Sniff the delimiter, falling back to comma.

    A spreadsheet saved in a comma-decimal locale writes semicolons; without
    this the whole file would parse as one column and every row would fail for
    a missing student number.
    """
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def parse_rows(raw: bytes, *, max_rows: int) -> list[_ParsedRow]:
    """Decode and parse the upload, or raise :class:`ImportFileError`."""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFileError(
            "IMPORT_ENCODING", "The file must be UTF-8 encoded CSV."
        ) from exc

    if not text.strip():
        raise ImportFileError("IMPORT_EMPTY", "The file is empty.")

    reader = csv.DictReader(io.StringIO(text), dialect=_detect_dialect(text[:4096]))
    if not reader.fieldnames:
        raise ImportFileError("IMPORT_MISSING_COLUMNS", "The file has no header row.")

    mapping = {name: _normalize_header(name) for name in reader.fieldnames if name}
    present = set(mapping.values())
    missing = [column for column in REQUIRED_COLUMNS if column not in present]
    if missing:
        raise ImportFileError(
            "IMPORT_MISSING_COLUMNS",
            "The file is missing required column(s): " + ", ".join(missing) + ".",
        )

    rows: list[_ParsedRow] = []
    # `start=2` because line 1 is the header: the number the operator sees in
    # their spreadsheet is the one that must appear in the report.
    for line_number, raw_row in enumerate(reader, start=2):
        values = {
            mapping[key]: (value or "").strip()
            for key, value in raw_row.items()
            if key in mapping and (value or "").strip()
        }
        if not values:
            # Trailing blank lines are an artefact of spreadsheet exports.
            continue
        if len(rows) >= max_rows:
            raise ImportFileError(
                "IMPORT_TOO_LARGE",
                f"The file has more than {max_rows} rows; split it into batches.",
            )
        rows.append(_ParsedRow(row_number=line_number, values=values))

    if not rows:
        raise ImportFileError("IMPORT_EMPTY", "The file has no data rows.")
    return rows


def build_template_csv() -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(TEMPLATE_COLUMNS)
    return buffer.getvalue()


def _parse_date(value: str) -> date | None:
    """ISO only. A date we cannot read with certainty is not a date."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _resolve_bed(
    db: DBSession, *, building_name: str, floor_number: str, room_number: str, bed_ref: str
) -> tuple[Bed | None, str | None]:
    """Resolve a bed from its human coordinates.

    Returns ``(bed, error)``. The error names the first coordinate that does not
    resolve, so the operator knows which sheet to correct.
    """
    building = (
        db.query(Building)
        .filter(
            func.lower(Building.name) == building_name.lower(),
            Building.is_active.is_(True),
        )
        .first()
    )
    if building is None:
        return None, f"Unknown building: {building_name}."

    try:
        floor_no = int(floor_number)
    except ValueError:
        return None, f"Floor must be a number, got {floor_number!r}."

    floor = (
        db.query(Floor)
        .filter(Floor.building_id == building.id, Floor.floor_number == floor_no)
        .first()
    )
    if floor is None:
        return None, f"{building.name} has no floor {floor_no}."

    room = (
        db.query(Room)
        .filter(Room.floor_id == floor.id, Room.room_number == room_number)
        .first()
    )
    if room is None:
        return None, f"{building.name} floor {floor_no} has no room {room_number}."
    if room.status == RoomStatus.OUT_OF_SERVICE:
        return None, f"Room {room_number} is out of service."

    # A bed is addressed by number ("3") or by its printed label ("3A").
    query = db.query(Bed).filter(Bed.room_id == room.id, Bed.is_active.is_(True))
    if bed_ref.isdigit():
        bed = query.filter(Bed.bed_number == int(bed_ref)).first()
        if bed is None:
            bed = query.filter(func.lower(Bed.label) == bed_ref.lower()).first()
    else:
        bed = query.filter(func.lower(Bed.label) == bed_ref.lower()).first()
    if bed is None:
        return None, f"Room {room_number} has no bed {bed_ref}."
    return bed, None


def _evaluate(
    db: DBSession,
    row: _ParsedRow,
    *,
    seen_students: set[str],
    seen_beds: set[uuid.UUID],
) -> tuple[dict[str, Any] | None, HousingImportRow]:
    """Check one row against the database without changing anything."""

    values = row.values
    student_number = values.get("student_id")
    report = HousingImportRow(
        row_number=row.row_number,
        student_number=student_number,
        building=values.get("building"),
        room=values.get("room"),
        bed=values.get("bed"),
        status=STATUS_VALID,
    )

    missing = [column for column in REQUIRED_COLUMNS if not values.get(column)]
    if missing:
        report.status = STATUS_ERROR
        report.code = "IMPORT_MISSING_FIELDS"
        report.message = "Missing: " + ", ".join(missing) + "."
        return None, report

    student = (
        db.query(Student)
        .filter(Student.student_id == values["student_id"])
        .first()
    )
    if student is None:
        report.status = STATUS_ERROR
        report.code = "STUDENT_NOT_FOUND"
        report.message = f"No student with number {values['student_id']}."
        return None, report
    report.student_name = f"{student.first_name} {student.last_name}"

    start = _parse_date(values["start_date"])
    if start is None:
        report.status = STATUS_ERROR
        report.code = "IMPORT_INVALID_DATE"
        report.message = f"Start date must be YYYY-MM-DD, got {values['start_date']!r}."
        return None, report

    end: date | None = None
    if values.get("end_date"):
        end = _parse_date(values["end_date"])
        if end is None:
            report.status = STATUS_ERROR
            report.code = "IMPORT_INVALID_DATE"
            report.message = f"End date must be YYYY-MM-DD, got {values['end_date']!r}."
            return None, report
        if end < start:
            report.status = STATUS_ERROR
            report.code = "IMPORT_INVALID_DATE"
            report.message = "End date is before the start date."
            return None, report

    bed, error = _resolve_bed(
        db,
        building_name=values["building"],
        floor_number=values["floor"],
        room_number=values["room"],
        bed_ref=values["bed"],
    )
    if bed is None:
        report.status = STATUS_ERROR
        report.code = "IMPORT_UNRESOLVED_REFERENCE"
        report.message = error
        return None, report

    # A row repeated inside the same file would fail on the unique index; catch
    # it here so the report names both rows instead of one opaque conflict.
    if values["student_id"] in seen_students:
        report.status = STATUS_SKIPPED
        report.code = "DUPLICATE_IN_FILE"
        report.message = "This student appears more than once in the file."
        return None, report
    if bed.id in seen_beds:
        report.status = STATUS_SKIPPED
        report.code = "DUPLICATE_IN_FILE"
        report.message = f"Bed {values['bed']} is assigned twice in this file."
        return None, report

    already_housed = (
        db.query(HousingAssignment.id)
        .filter(
            HousingAssignment.student_id == student.user_id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
        .first()
    )
    if already_housed:
        report.status = STATUS_SKIPPED
        report.code = "STUDENT_ALREADY_ASSIGNED"
        report.message = "Student already has an active housing assignment."
        return None, report

    occupied = (
        db.query(HousingAssignment.id)
        .filter(
            HousingAssignment.bed_id == bed.id,
            HousingAssignment.status == HousingAssignmentStatus.ACTIVE,
        )
        .first()
    )
    if occupied:
        report.status = STATUS_SKIPPED
        report.code = "BED_OCCUPIED"
        report.message = "That bed is already occupied."
        return None, report

    seen_students.add(values["student_id"])
    seen_beds.add(bed.id)
    return (
        {
            "student_id": student.user_id,
            "bed_id": bed.id,
            "start_date": _midnight(start),
            "end_date": _midnight(end) if end else None,
            # Column is String(500); a longer note would fail the insert after
            # validation had already promised the row was safe.
            "notes": (values.get("notes") or "")[:500] or None,
            "student_number": values["student_id"],
        },
        report,
    )


def _validate(
    db: DBSession, rows: Sequence[_ParsedRow]
) -> tuple[list[dict[str, Any]], list[HousingImportRow]]:
    seen_students: set[str] = set()
    seen_beds: set[uuid.UUID] = set()
    planned: list[dict[str, Any]] = []
    report_rows: list[HousingImportRow] = []
    for row in rows:
        assignment, report = _evaluate(
            db, row, seen_students=seen_students, seen_beds=seen_beds
        )
        report_rows.append(report)
        if assignment is not None:
            planned.append(assignment)
    return planned, report_rows


def _build_report(
    *, dry_run: bool, rows: list[HousingImportRow], aborted: bool = False
) -> HousingImportReport:
    return HousingImportReport(
        dry_run=dry_run,
        aborted=aborted,
        total=len(rows),
        valid=sum(1 for row in rows if row.status == STATUS_VALID),
        created=sum(1 for row in rows if row.status == STATUS_CREATED),
        skipped=sum(1 for row in rows if row.status == STATUS_SKIPPED),
        failed=sum(1 for row in rows if row.status == STATUS_ERROR),
        rows=rows,
    )


def preview_housing_import(db: DBSession, rows: Sequence[_ParsedRow]) -> HousingImportReport:
    """Check every row and report the outcome without writing anything."""
    _, report_rows = _validate(db, rows)
    return _build_report(dry_run=True, rows=report_rows)


def apply_housing_import(
    db: DBSession,
    rows: Sequence[_ParsedRow],
    *,
    actor_id: uuid.UUID,
    source_reference: str | None,
) -> HousingImportReport:
    """Write the validated batch in one transaction.

    Refused as a whole when any row is invalid: a half-imported floor is worse
    than no import, because the operator cannot tell which beds are real. Rows
    that are merely already satisfied (occupied bed, housed student) are skipped
    and reported, which is what makes a re-run harmless.
    """
    planned, report_rows = _validate(db, rows)
    failed = sum(1 for row in report_rows if row.status == STATUS_ERROR)
    if failed:
        return _build_report(dry_run=False, rows=report_rows, aborted=True)

    note = f"Imported from {source_reference}" if source_reference else "Imported from file"
    assignments = [
        HousingAssignment(
            student_id=item["student_id"],
            bed_id=item["bed_id"],
            start_date=item["start_date"],
            end_date=item["end_date"],
            status=HousingAssignmentStatus.ACTIVE,
            notes=item["notes"] or note,
            created_by_id=actor_id,
        )
        for item in planned
    ]

    try:
        for assignment in assignments:
            db.add(assignment)
        db.commit()
    except IntegrityError:
        db.rollback()
        # The partial unique indexes are authoritative. A concurrent assignment
        # that slipped between validation and commit lands here; the batch is
        # rolled back rather than silently dropping the row.
        return _build_report(dry_run=False, rows=report_rows, aborted=True)

    for row in report_rows:
        if row.status == STATUS_VALID:
            row.status = STATUS_CREATED

    return _build_report(dry_run=False, rows=report_rows)
