"""Staged importer for the accepted SCU timetable reference.

The importer never creates an academic period. A caller must explicitly map a
source semester to an existing, dated period. Missing dates, parent-program
relationships and the N103 conflict remain held in staging.

The public flow is intentionally three operations:

    prepare_import(...)  -> DRY_RUN/READY batch, no academic rows
    apply_import(...)    -> apply explicitly mapped rows and record target ids
    rollback_batch(...)  -> remove only rows owned by that batch

The HTTP surface (``/academics/imports``) is a thin, permission-gated wrapper
around these three operations; it adds nothing that could become a second
mapping mechanism. The batch table is the provenance record, so an applied
source can be inspected and rolled back later.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.models.academic import (
    AcademicImportBatch,
    AcademicImportRow,
    AcademicPeriod,
    Classroom,
    ClassSection,
    ClassSectionProgramOffering,
    ClassStatus,
    Course,
    ProgramOffering,
    TimetableEntry,
)
from app.services.academic import _validate_timetable_slot, lock_timetable_writes


def _default_source() -> Path:
    """Locate the read-only source catalog in both host and container layouts.

    The repository checkout has ``docs/`` beside ``apps/``; the development
    container mounts it at ``/app/docs``. Searching upward avoids a brittle
    fixed parent index that differs between those two layouts.
    """
    override = os.environ.get("SCU_TIMETABLE_SOURCE")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "scu-timetable-reference.json"
        if candidate.exists():
            return candidate
    return here.parents[1] / "docs" / "scu-timetable-reference.json"


DEFAULT_SOURCE = _default_source()
DAY_NAMES = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}
HELD_COURSES = {
    "AI Ethics (International)",
    "AI Thinking and Ethics (International)",
}
HELD_PERIOD = "2025-autumn"
HELD_LOCATION = "N103"
HELD_TIMES = {(time(10, 20), time(12, 0))}
RESOLVED_BLOCK4_PERIODS = {"2026-autumn"}


class ImportError(RuntimeError):  # noqa: A001 - kept for existing service API
    """An import precondition or source consistency failure."""


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _hash(value: str, length: int) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def course_key(name: str) -> str:
    return f"ref:v1:course:{_slug(name)}"


def room_key(code: str) -> str:
    return f"ref:v1:room:{_slug(code)}"


def offering_key(source_id: str) -> str:
    return f"ref:v1:offering:{source_id}"


def period_key(source_id: str) -> str:
    return f"ref:v1:period:{source_id}"


def section_key(semester: str, course: str, program_ids: list[str]) -> str:
    return (
        "ref:v1:section:"
        + _hash(
            "|".join([semester, course, ",".join(sorted(program_ids))]),
            20,
        )
    )


def session_key(
    semester: str,
    course: str,
    day: str,
    start: str,
    end: str,
    location: str,
    program_ids: list[str],
) -> str:
    return (
        "ref:v1:session:"
        + _hash(
            "|".join(
                [
                    semester,
                    course,
                    day,
                    start,
                    end,
                    location,
                    ",".join(sorted(program_ids)),
                ]
            ),
            24,
        )
    )


def raw_key(semester: str, offering_id: str, ordinal: int) -> str:
    return f"ref:v1:raw:{_hash(f'{semester}|{offering_id}|{ordinal}', 20)}"


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", 1)
    return time(int(hour), int(minute))


def _slot_times(source: dict[str, Any], semester_id: str) -> dict[str, tuple[time, time]]:
    """Resolve every source label used by a semester's rows.

    ``standard8`` declares individual periods; source rows also use ranges such
    as 1-4 and 5-8. ``block4`` declares four two-period blocks, but rows also
    use the unions 1-4 and 5-8. Resolve from the declared definition rather than
    guessing from any one row.
    """
    formats = source["timeSlotFormats"]
    format_code = "block4" if semester_id in RESOLVED_BLOCK4_PERIODS else "standard8"
    slots = formats[format_code]["slots"]
    if format_code == "block4":
        direct = {
            str(slot["session"]): (
                _parse_time(slot["time"].split("-")[0]),
                _parse_time(slot["time"].split("-")[1]),
            )
            for slot in slots
        }
        result = dict(direct)
        # A union may span the first block's start through a later block's end.
        for first, second in (("1-4", "1-2"), ("1-4", "3-4"), ("5-8", "5-6"), ("5-8", "7-8")):
            if first not in result and second in direct:
                if first == "1-4":
                    result[first] = (direct["1-2"][0], direct["3-4"][1])
                elif first == "5-8":
                    result[first] = (direct["5-6"][0], direct["7-8"][1])
        return result

    period_times = {
        int(slot["session"]): (
            _parse_time(slot["time"].split("-")[0]),
            _parse_time(slot["time"].split("-")[1]),
        )
        for slot in slots
    }
    result: dict[str, tuple[time, time]] = {}
    for label in {
        "1-2",
        "1-4",
        "3-4",
        "5-6",
        "5-8",
        "7",
        "7-8",
    }:
        if "-" in label:
            first, last = (int(part) for part in label.split("-", 1))
            result[label] = (period_times[first][0], period_times[last][1])
        else:
            result[label] = period_times[int(label)]
    return result


def _semester_resolution(source: dict[str, Any]) -> dict[str, str]:
    return {
        semester["id"]: (
            "block4" if semester["id"] in RESOLVED_BLOCK4_PERIODS else "standard8"
        )
        for semester in source["semesters"]
    }


def _source_objects(source: dict[str, Any]) -> dict[str, Any]:
    """Build the complete in-memory source map before touching the database."""
    formats = _semester_resolution(source)
    session_identity: dict[tuple[str, str, str, str, str, str], dict[str, Any]] = {}
    sections: dict[str, dict[str, Any]] = {}
    raw_rows: list[dict[str, Any]] = []
    offerings: list[dict[str, Any]] = []
    rooms = source.get("locations", {})
    courses: dict[str, dict[str, Any]] = {}
    periods: list[dict[str, Any]] = []

    for semester in source["semesters"]:
        semester_id = semester["id"]
        slot_times = _slot_times(source, semester_id)
        periods.append(
            {
                "source_id": semester_id,
                "source_key": period_key(semester_id),
                "name": semester["name"],
                "name_zh": semester.get("nameCN"),
                "declared_format": semester.get("timeSlotFormat"),
                "resolved_format": formats[semester_id],
            }
        )
        for offering in semester.get("programs", []):
            offerings.append(
                {
                    "source_id": offering["id"],
                    "source_key": offering_key(offering["id"]),
                    "source_timetable_format": semester.get("timeSlotFormat"),
                    "semester": semester_id,
                    "name": offering["name"],
                    "name_zh": offering.get("nameCN"),
                }
            )
            for ordinal, row in enumerate(offering.get("schedule", [])):
                label = row["session"]
                if label not in slot_times:
                    raise ImportError(
                        f"Unresolved slot label {label!r} in {semester_id}/{offering['id']}"
                    )
                start, end = slot_times[label]
                start_text = start.strftime("%H:%M")
                end_text = end.strftime("%H:%M")
                identity = (
                    semester_id,
                    row["course"],
                    row["day"],
                    start_text,
                    end_text,
                    row["location"],
                )
                session = session_identity.get(identity)
                if session is None:
                    session = {
                        "semester": semester_id,
                        "course": row["course"],
                        "day": row["day"],
                        "slot": label,
                        "start": start,
                        "end": end,
                        "location": row["location"],
                        "program_ids": [],
                    }
                    session_identity[identity] = session
                if offering["id"] not in session["program_ids"]:
                    session["program_ids"].append(offering["id"])

                course = courses.setdefault(
                    row["course"],
                    {
                        "name": row["course"],
                        "source_key": course_key(row["course"]),
                        "semesters": set(),
                    },
                )
                course["semesters"].add(semester_id)
                raw_rows.append(
                    {
                        "source_key": raw_key(semester_id, offering["id"], ordinal),
                        "source_locator": {
                            "semester": semester_id,
                            "offering": offering["id"],
                            "row": ordinal,
                        },
                        "payload": {
                            "course": row["course"],
                            "day": row["day"],
                            "slot": label,
                            "location": row["location"],
                            "start": start_text,
                            "end": end_text,
                        },
                    }
                )

    # A session is shared when the exact course/time/room appears under more
    # than one offering. Re-key it after the complete offering set is known.
    sessions: dict[str, dict[str, Any]] = {}
    for session in session_identity.values():
        key = session_key(
            session["semester"],
            session["course"],
            session["day"],
            session["start"].strftime("%H:%M"),
            session["end"].strftime("%H:%M"),
            session["location"],
            session["program_ids"],
        )
        session["source_key"] = key
        sessions[key] = session

    for session in sessions.values():
        skey = section_key(
            session["semester"], session["course"], session["program_ids"]
        )
        section = sections.get(skey)
        if section is None:
            section = {
                "source_key": skey,
                "semester": session["semester"],
                "course": session["course"],
                "program_ids": sorted(session["program_ids"]),
                "session_keys": [],
                "held": False,
            }
            sections[skey] = section
        section["session_keys"].append(session["source_key"])
        if (
            session["semester"] == HELD_PERIOD
            and session["course"] in HELD_COURSES
            and session["location"] == HELD_LOCATION
            and (session["start"], session["end"]) in HELD_TIMES
        ):
            section["held"] = True

    return {
        "formats": formats,
        "periods": periods,
        "offerings": offerings,
        "courses": list(courses.values()),
        "rooms": [
            {
                "room_code": code,
                "building": details.get("building"),
                "campus": details.get("campus"),
                "source_key": room_key(code),
            }
            for code, details in rooms.items()
        ],
        "sections": list(sections.values()),
        "sessions": list(sessions.values()),
        "raw_rows": raw_rows,
    }


def _stage(
    db: DBSession,
    batch: AcademicImportBatch,
    *,
    entity_type: str,
    source_key: str,
    payload: dict[str, Any],
    action: str = "CREATE",
    error_code: str | None = None,
    source_locator: dict[str, Any] | None = None,
) -> None:
    def safe(value: Any) -> Any:
        if isinstance(value, (time, datetime)):
            return value.isoformat()
        if isinstance(value, uuid.UUID):
            return str(value)
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [safe(item) for item in value]
        return value

    db.add(
        AcademicImportRow(
            batch_id=batch.id,
            entity_type=entity_type,
            source_key=source_key,
            source_locator=safe(source_locator or {}),
            payload=safe(payload),
            previous_data=None,
            action=action,
            error_code=error_code,
        )
    )


def prepare_import(
    db: DBSession,
    source_path: str | Path = DEFAULT_SOURCE,
    *,
    actor_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Stage every source object without writing academic rows."""
    path = Path(source_path)
    raw = path.read_bytes()
    source = json.loads(raw)
    sha = hashlib.sha256(raw).hexdigest()
    objects = _source_objects(source)

    batch = AcademicImportBatch(
        source_name=str(source.get("metadata", {}).get("source", path.name)),
        source_sha256=sha,
        status="READY",
        dry_run=True,
        created_by_id=actor_id,
        counts_json={},
    )
    db.add(batch)
    db.flush()

    for period in objects["periods"]:
        _stage(db, batch, entity_type="period", source_key=period["source_key"], payload=period)
    for offering in objects["offerings"]:
        _stage(
            db,
            batch,
            entity_type="offering",
            source_key=offering["source_key"],
            payload=offering,
        )
    for course in objects["courses"]:
        _stage(
            db,
            batch,
            entity_type="course",
            source_key=course["source_key"],
            payload={**course, "semesters": sorted(course["semesters"])},
        )
    for room in objects["rooms"]:
        _stage(db, batch, entity_type="room", source_key=room["source_key"], payload=room)
    for section in objects["sections"]:
        _stage(
            db,
            batch,
            entity_type="section",
            source_key=section["source_key"],
            payload=section,
            action="HELD" if section["held"] else "CREATE",
            error_code="N103_CONFLICT_UNRESOLVED" if section["held"] else None,
        )
        for offering_id in section["program_ids"]:
            link_key = f"{section['source_key']}|{offering_key(offering_id)}"
            _stage(
                db,
                batch,
                entity_type="section_offering",
                source_key=link_key,
                payload={
                    "section_key": section["source_key"],
                    "offering_key": offering_key(offering_id),
                },
                action="HELD" if section["held"] else "CREATE",
                error_code="N103_CONFLICT_UNRESOLVED" if section["held"] else None,
            )
    for session in objects["sessions"]:
        skey = section_key(session["semester"], session["course"], session["program_ids"])
        held = any(
            section["source_key"] == skey and section["held"]
            for section in objects["sections"]
        )
        _stage(
            db,
            batch,
            entity_type="session",
            source_key=session["source_key"],
            payload={**session, "section_key": skey},
            action="HELD" if held else "CREATE",
            error_code="N103_CONFLICT_UNRESOLVED" if held else None,
        )
    for row in objects["raw_rows"]:
        _stage(
            db,
            batch,
            entity_type="raw_schedule_row",
            source_key=row["source_key"],
            payload=row["payload"],
            action="STAGE",
            source_locator=row["source_locator"],
        )

    held_sections = sum(1 for section in objects["sections"] if section["held"])
    shared_session_groups = sum(
        1 for session in objects["sessions"] if len(session["program_ids"]) > 1
    )
    shared_sections = sum(
        1 for section in objects["sections"] if len(section["program_ids"]) > 1
    )
    held_sessions = sum(
        1
        for session in objects["sessions"]
        if any(
            section["held"]
            and section["source_key"]
            == section_key(session["semester"], session["course"], session["program_ids"])
            for section in objects["sections"]
        )
    )
    counts = {
        "periods": len(objects["periods"]),
        "offerings": len(objects["offerings"]),
        "courses": len(objects["courses"]),
        "rooms": len(objects["rooms"]),
        "sections": len(objects["sections"]),
        "section_offerings": sum(len(section["program_ids"]) for section in objects["sections"]),
        "sessions": len(objects["sessions"]),
        "raw_schedule_rows": len(objects["raw_rows"]),
        "merged_schedule_rows": len(objects["raw_rows"]) - len(objects["sessions"]),
        # Nine shared session identities collapse into seven canonical
        # sections. Keep the older key as the session count for compatibility.
        "shared_groups": shared_session_groups,
        "shared_session_groups": shared_session_groups,
        "shared_sections": shared_sections,
        "held_sections": held_sections,
        "held_sessions": held_sessions,
    }
    batch.counts_json = counts
    db.commit()
    db.refresh(batch)
    return {"batch_id": str(batch.id), "source_sha256": sha, **counts}


def _uuid(value: str | uuid.UUID) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _find_row(
    db: DBSession, batch_id: uuid.UUID, entity_type: str, key: str
) -> AcademicImportRow | None:
    return (
        db.query(AcademicImportRow)
        .filter(
            AcademicImportRow.batch_id == batch_id,
            AcademicImportRow.entity_type == entity_type,
            AcademicImportRow.source_key == key,
        )
        .first()
    )


def _set_target(
    db: DBSession, row: AcademicImportRow, target_table: str, target_id: uuid.UUID
) -> None:
    row.target_table = target_table
    row.target_id = target_id
    row.action = "CREATE" if row.action == "CREATE" else row.action


def apply_import(
    db: DBSession,
    batch_id: uuid.UUID,
    *,
    period_map: dict[str, str | uuid.UUID] | None = None,
    parent_program_map: dict[str, str | uuid.UUID] | None = None,
) -> dict[str, Any]:
    """Apply a prepared batch.

    ``period_map`` keys are source semester ids and values are existing period
    ids. An unmapped period stays held; dates are never inferred. Parent program
    links are optional and keyed by source offering id.
    """
    period_map = period_map or {}
    parent_program_map = parent_program_map or {}
    batch = db.query(AcademicImportBatch).filter(AcademicImportBatch.id == batch_id).first()
    if not batch:
        raise ImportError("Import batch not found")
    if batch.status == "APPLIED":
        return {"batch_id": str(batch.id), "status": "APPLIED", **batch.counts_json}

    # The same source file must not be applied twice from two batches. Applying
    # the same rows again would be a no-op at source-key level but would write a
    # second provenance batch claiming the same records, which makes rollback
    # ambiguous. One applied batch per source checksum is the invariant.
    duplicate = (
        db.query(AcademicImportBatch)
        .filter(
            AcademicImportBatch.source_sha256 == batch.source_sha256,
            AcademicImportBatch.status == "APPLIED",
            AcademicImportBatch.id != batch.id,
        )
        .first()
    )
    if duplicate is not None:
        raise ImportError(
            "This source catalogue has already been applied in batch "
            f"{duplicate.id}; roll that batch back before applying it again"
        )
    if batch.status not in {"READY", "DRY_RUN"}:
        raise ImportError(f"Batch cannot be applied from status {batch.status}")

    try:
        period_ids: dict[str, uuid.UUID] = {}
        for period_row in (
            db.query(AcademicImportRow)
            .filter(
                AcademicImportRow.batch_id == batch.id,
                AcademicImportRow.entity_type == "period",
            )
            .all()
        ):
            source_id = period_row.payload["source_id"]
            mapped = period_map.get(source_id)
            if not mapped:
                period_row.action = "HELD"
                period_row.error_code = "PERIOD_NOT_MAPPED"
                continue
            period = (
                db.query(AcademicPeriod)
                .filter(AcademicPeriod.id == _uuid(mapped))
                .first()
            )
            if not period:
                raise ImportError(f"Mapped period {mapped} for {source_id} does not exist")
            previous = {
                "source_key": period.source_key,
                "name_zh": period.name_zh,
                "source_timetable_format": period.source_timetable_format,
                "timetable_format_code": period.timetable_format_code,
                "timetable_format_note": period.timetable_format_note,
            }
            period.source_key = period_row.payload["source_key"]
            period.name_zh = period_row.payload.get("name_zh")
            period.source_timetable_format = period_row.payload.get("declared_format")
            period.timetable_format_code = period_row.payload.get("resolved_format")
            period.timetable_format_note = (
                "Resolved block4 for 2026 Autumn; source per-semester value was "
                f"{period_row.payload.get('declared_format')}. The source's "
                "top-level block4 description and every Autumn row corroborate this."
                if source_id in RESOLVED_BLOCK4_PERIODS
                else None
            )
            period_ids[source_id] = period.id
            period_row.previous_data = previous
            period_row.action = "UPDATE"
            period_row.target_table = "academic_periods"
            period_row.target_id = period.id

        offering_ids: dict[str, uuid.UUID] = {}
        for row in (
            db.query(AcademicImportRow)
            .filter(
                AcademicImportRow.batch_id == batch.id,
                AcademicImportRow.entity_type == "offering",
            )
            .all()
        ):
            payload = row.payload
            mapped_period = period_ids.get(payload["semester"])
            if not mapped_period:
                row.action = "HELD"
                row.error_code = "PERIOD_NOT_MAPPED"
                continue
            offering = (
                db.query(ProgramOffering)
                .filter(ProgramOffering.source_key == row.source_key)
                .first()
            )
            if offering is None:
                offering = ProgramOffering(
                    academic_period_id=mapped_period,
                    program_id=(
                        _uuid(parent_program_map[payload["source_id"]])
                        if payload["source_id"] in parent_program_map
                        else None
                    ),
                    source_id=payload["source_id"],
                    source_key=row.source_key,
                    name=payload["name"],
                    name_zh=payload.get("name_zh"),
                    import_batch_id=batch.id,
                )
                db.add(offering)
                db.flush()
            offering_ids[payload["source_id"]] = offering.id
            _set_target(db, row, "program_offerings", offering.id)

        for row in (
            db.query(AcademicImportRow)
            .filter(
                AcademicImportRow.batch_id == batch.id,
                AcademicImportRow.entity_type == "course",
            )
            .all()
        ):
            course = db.query(Course).filter(Course.source_key == row.source_key).first()
            if course is None:
                course = Course(
                    code=None,
                    name=row.payload["name"],
                    name_zh=None,
                    credits=None,
                    source_key=row.source_key,
                    import_batch_id=batch.id,
                )
                db.add(course)
                db.flush()
            _set_target(db, row, "courses", course.id)

        for row in (
            db.query(AcademicImportRow)
            .filter(
                AcademicImportRow.batch_id == batch.id,
                AcademicImportRow.entity_type == "room",
            )
            .all()
        ):
            room = (
                db.query(Classroom)
                .filter(Classroom.source_key == row.source_key)
                .first()
            )
            if room is None:
                room = Classroom(
                    room_code=row.payload["room_code"],
                    building=row.payload.get("building"),
                    campus=row.payload.get("campus"),
                    capacity=None,
                    source_key=row.source_key,
                    import_batch_id=batch.id,
                )
                db.add(room)
                db.flush()
            _set_target(db, row, "classrooms", room.id)

        section_ids: dict[str, uuid.UUID] = {}
        for row in (
            db.query(AcademicImportRow)
            .filter(
                AcademicImportRow.batch_id == batch.id,
                AcademicImportRow.entity_type == "section",
            )
            .all()
        ):
            payload = row.payload
            mapped_period = period_ids.get(payload["semester"])
            if not mapped_period or payload.get("held"):
                if not mapped_period:
                    row.error_code = "PERIOD_NOT_MAPPED"
                continue
            course_key_value = course_key(payload["course"])
            course = db.query(Course).filter(Course.source_key == course_key_value).first()
            if not course:
                raise ImportError(f"Course row not found for {payload['course']}")
            section = (
                db.query(ClassSection)
                .filter(ClassSection.source_key == row.source_key)
                .first()
            )
            if section is None:
                section = ClassSection(
                    course_id=course.id,
                    academic_period_id=mapped_period,
                    section_code=None,
                    source_label=(
                        payload["course"] + " [" + ", ".join(payload["program_ids"]) + "]"
                    ),
                    source_key=row.source_key,
                    capacity=None,
                    enrolled_count=0,
                    status=ClassStatus.ACTIVE,
                    import_batch_id=batch.id,
                )
                db.add(section)
                db.flush()
            section_ids[row.source_key] = section.id
            _set_target(db, row, "class_sections", section.id)

        for row in (
            db.query(AcademicImportRow)
            .filter(
                AcademicImportRow.batch_id == batch.id,
                AcademicImportRow.entity_type == "section_offering",
            )
            .all()
        ):
            section_id = section_ids.get(row.payload["section_key"])
            offering_key_value = row.payload["offering_key"]
            offering_id = next(
                (
                    value
                    for key, value in offering_ids.items()
                    if offering_key(key) == offering_key_value
                ),
                None,
            )
            if not section_id or not offering_id:
                row.action = "HELD"
                row.error_code = row.error_code or "SECTION_OR_OFFERING_NOT_MAPPED"
                continue
            existing = (
                db.query(ClassSectionProgramOffering)
                .filter(
                    ClassSectionProgramOffering.class_section_id == section_id,
                    ClassSectionProgramOffering.program_offering_id == offering_id,
                )
                .first()
            )
            if existing is None:
                db.add(
                    ClassSectionProgramOffering(
                        class_section_id=section_id,
                        program_offering_id=offering_id,
                    )
                )
            _set_target(db, row, "class_section_program_offerings", section_id)

        # The importer is another writer of the timetable domain. Hold the
        # same transaction-scoped lock as the API while it validates and
        # inserts sessions, so an import cannot race a teacher assignment or
        # a manual timetable edit.
        lock_timetable_writes(db)

        for row in (
            db.query(AcademicImportRow)
            .filter(
                AcademicImportRow.batch_id == batch.id,
                AcademicImportRow.entity_type == "session",
            )
            .all()
        ):
            payload = row.payload
            section_id = section_ids.get(payload["section_key"])
            if not section_id or payload.get("held"):
                if not section_id:
                    row.error_code = "SECTION_HELD_OR_UNMAPPED"
                continue
            existing = (
                db.query(TimetableEntry)
                .filter(TimetableEntry.source_key == row.source_key)
                .first()
            )
            if existing is None:
                classroom = (
                    db.query(Classroom)
                    .filter(Classroom.source_key == room_key(payload["location"]))
                    .first()
                )
                day_of_week = DAY_NAMES[payload["day"]]
                start_time = time.fromisoformat(payload["start"])
                end_time = time.fromisoformat(payload["end"])
                _validate_timetable_slot(
                    db,
                    class_section_id=section_id,
                    classroom_id=classroom.id if classroom else None,
                    day_of_week=day_of_week,
                    start_time=start_time,
                    end_time=end_time,
                )
                entry = TimetableEntry(
                    class_section_id=section_id,
                    classroom_id=classroom.id if classroom else None,
                    day_of_week=day_of_week,
                    start_time=start_time,
                    end_time=end_time,
                    slot_label=payload["slot"],
                    source_key=row.source_key,
                    import_batch_id=batch.id,
                )
                db.add(entry)
                db.flush()
            else:
                entry = existing
            _set_target(db, row, "timetable_entries", entry.id)

        # A second apply of the same source is a no-op at the source-key level.
        for row in (
            db.query(AcademicImportRow)
            .filter(AcademicImportRow.batch_id == batch.id)
            .all()
        ):
            if row.action == "CREATE" and row.target_id is not None:
                row.action = "APPLIED"

        batch.status = "APPLIED"
        batch.dry_run = False
        batch.finished_at = datetime.now(UTC)
        batch.counts_json = {
            **(batch.counts_json or {}),
            "applied_periods": len(period_ids),
            "applied_offerings": len(offering_ids),
            "applied_sections": len(section_ids),
            "held_sections": (batch.counts_json or {}).get("held_sections", 0),
            "held_sessions": (batch.counts_json or {}).get("held_sessions", 0),
        }
        db.commit()
        db.refresh(batch)
        return {"batch_id": str(batch.id), "status": batch.status, **batch.counts_json}
    except Exception:
        db.rollback()
        failed = db.query(AcademicImportBatch).filter(AcademicImportBatch.id == batch_id).first()
        if failed:
            failed.status = "FAILED"
            failed.finished_at = datetime.now(UTC)
            db.commit()
        raise


def rollback_batch(db: DBSession, batch_id: uuid.UUID) -> dict[str, Any]:
    """Delete only records owned by an applied batch and restore period metadata."""
    batch = db.query(AcademicImportBatch).filter(AcademicImportBatch.id == batch_id).first()
    if not batch:
        raise ImportError("Import batch not found")
    if batch.status != "APPLIED":
        return {"batch_id": str(batch.id), "status": batch.status, "rolled_back": 0}

    section_rows = (
        db.query(AcademicImportRow)
        .filter(
            AcademicImportRow.batch_id == batch.id,
            AcademicImportRow.entity_type == "section",
            AcademicImportRow.target_id.isnot(None),
        )
        .all()
    )
    section_ids = [row.target_id for row in section_rows if row.action in {"APPLIED", "CREATE"}]

    entries_deleted = (
        db.query(TimetableEntry)
        .filter(TimetableEntry.import_batch_id == batch.id)
        .delete(synchronize_session=False)
    )
    if section_ids:
        db.query(ClassSectionProgramOffering).filter(
            ClassSectionProgramOffering.class_section_id.in_(section_ids)
        ).delete(synchronize_session=False)
        db.query(ClassSection).filter(ClassSection.id.in_(section_ids)).delete(
            synchronize_session=False
        )
    offerings_deleted = (
        db.query(ProgramOffering)
        .filter(ProgramOffering.import_batch_id == batch.id)
        .delete(synchronize_session=False)
    )
    courses_deleted = (
        db.query(Course)
        .filter(Course.import_batch_id == batch.id)
        .delete(synchronize_session=False)
    )
    rooms_deleted = (
        db.query(Classroom)
        .filter(Classroom.import_batch_id == batch.id)
        .delete(synchronize_session=False)
    )

    for row in (
        db.query(AcademicImportRow)
        .filter(
            AcademicImportRow.batch_id == batch.id,
            AcademicImportRow.entity_type == "period",
            AcademicImportRow.action == "UPDATE",
        )
        .all()
    ):
        period = (
            db.query(AcademicPeriod)
            .filter(AcademicPeriod.id == row.target_id)
            .first()
        )
        if period and row.previous_data:
            for field in (
                "source_key",
                "name_zh",
                "source_timetable_format",
                "timetable_format_code",
                "timetable_format_note",
            ):
                setattr(period, field, row.previous_data.get(field))

    batch.status = "ROLLED_BACK"
    batch.finished_at = datetime.now(UTC)
    db.commit()
    return {
        "batch_id": str(batch.id),
        "status": batch.status,
        "sections_deleted": len(section_ids),
        "entries_deleted": entries_deleted,
        "offerings_deleted": offerings_deleted,
        "courses_deleted": courses_deleted,
        "rooms_deleted": rooms_deleted,
    }


# --- Request-facing workflow ------------------------------------------------
#
# These helpers are the only additions the HTTP layer uses. ``preview_import``
# reuses ``prepare_import`` unchanged, so the dry run and the apply see exactly
# the same rows; ``batch_report`` only reads staging rows.


def applied_batch_for_source(
    db: DBSession, source_sha256: str
) -> AcademicImportBatch | None:
    """The applied batch for a source checksum, if the file is already live."""
    return (
        db.query(AcademicImportBatch)
        .filter(
            AcademicImportBatch.source_sha256 == source_sha256,
            AcademicImportBatch.status == "APPLIED",
        )
        .order_by(AcademicImportBatch.finished_at.desc())
        .first()
    )


def preview_import(
    db: DBSession,
    *,
    actor_id: uuid.UUID | None = None,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Stage the catalogue, unless this exact file is already applied.

    A second preview of an applied source does not create a batch: it reports
    the applied one. That is what keeps repeated clicks idempotent and stops a
    duplicate application before any academic row is touched.
    """
    path = Path(source_path) if source_path is not None else Path(DEFAULT_SOURCE)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    applied = applied_batch_for_source(db, sha)
    if applied is not None:
        return {
            "batch_id": str(applied.id),
            "status": "ALREADY_APPLIED",
            "source_sha256": sha,
            "already_applied": True,
            **(applied.counts_json or {}),
        }
    result = prepare_import(db, path, actor_id=actor_id)
    return {**result, "status": "READY", "already_applied": False}


def list_batches(db: DBSession, *, limit: int = 20) -> list[AcademicImportBatch]:
    return (
        db.query(AcademicImportBatch)
        .order_by(AcademicImportBatch.created_at.desc())
        .limit(limit)
        .all()
    )


def batch_report(db: DBSession, batch_id: uuid.UUID) -> dict[str, Any]:
    """Read back one batch: counts, mapping state and the held rows.

    Nothing here is derived from the live academic tables; the report describes
    the staged import so an operator can decide before applying it.
    """
    batch = (
        db.query(AcademicImportBatch)
        .filter(AcademicImportBatch.id == batch_id)
        .first()
    )
    if batch is None:
        raise ImportError("Import batch not found")

    rows = (
        db.query(AcademicImportRow)
        .filter(AcademicImportRow.batch_id == batch.id)
        .order_by(AcademicImportRow.id)
        .all()
    )
    by_entity: dict[str, int] = {}
    by_action: dict[str, int] = {}
    periods: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    for row in rows:
        by_entity[row.entity_type] = by_entity.get(row.entity_type, 0) + 1
        by_action[row.action] = by_action.get(row.action, 0) + 1
        if row.entity_type == "period":
            periods.append(
                {
                    "source_id": row.payload.get("source_id"),
                    "source_key": row.source_key,
                    "mapped_period_id": (
                        row.target_id if row.action in {"UPDATE", "APPLIED"} else None
                    ),
                    "mapped_period_code": None,
                }
            )
        if row.action == "HELD" or row.error_code:
            held.append(
                {
                    "entity_type": row.entity_type,
                    "action": row.action,
                    "source_key": row.source_key,
                    "error_code": row.error_code,
                    "target_id": row.target_id,
                }
            )

    return {
        "batch_id": batch.id,
        "status": batch.status,
        "dry_run": batch.dry_run,
        "source_name": batch.source_name,
        "source_sha256": batch.source_sha256,
        "created_at": batch.created_at,
        "finished_at": batch.finished_at,
        "counts": batch.counts_json or {},
        "periods": periods,
        "by_entity": by_entity,
        "by_action": by_action,
        "held": held,
        "already_applied": batch.status == "APPLIED",
    }
