"""Read-only view of the accepted SCU source-intake map.

The operational academic tables only contain materialized intakes. The source
map is the auditable catalog of every intake in the reference timetable,
including intakes that cannot yet be configured because their official dates
or codes have not been approved.

This module deliberately performs no writes. It joins the map to persisted
periods and offerings by source key, verifies imported retirements against the
map, and returns ``None`` for any platform value that does not exist.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    ClassSection,
    ClassSectionProgramOffering,
    ProgramOffering,
    TimetableEntry,
)
from app.models.admission import AcademicPlacement
from app.schemas.academic import (
    AcademicPeriodResponse,
    SourceIntakeListResponse,
    SourceIntakeOfferingResponse,
    SourceIntakeResponse,
    SourceIntakeSectionResponse,
    SourceIntakeSubjectResponse,
)

SOURCE_MAP_RELATIVE_PATH = Path("docs") / "scu-timetable-domain-map.json"


def _resolve_source_map_path() -> Path:
    """Locate the accepted catalog in host and container layouts.

    The repository keeps the map under ``docs/`` at the repository root, while
    Docker mounts only the API at ``/app`` and exposes the map at ``/app/docs``.
    Searching the parents avoids assuming one particular directory depth and
    still permits an explicit deployment override.
    """
    configured = os.getenv("ACADEMIC_SOURCE_MAP_PATH")
    if configured:
        return Path(configured).expanduser()

    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / SOURCE_MAP_RELATIVE_PATH
        if candidate.is_file():
            return candidate

    return Path.cwd() / SOURCE_MAP_RELATIVE_PATH


SOURCE_MAP_PATH = _resolve_source_map_path()

DAY_NAMES = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def _source_key(prefix: str, source_id: str) -> str:
    return f"ref:v1:{prefix}:{source_id}"


def _load_catalog_file(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Source intake map not found at {path}. "
            "Set ACADEMIC_SOURCE_MAP_PATH or mount the catalog."
        )
    raw = path.read_bytes()
    try:
        catalog = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Source intake map is not valid JSON: {path}") from exc
    return catalog, hashlib.sha256(raw).hexdigest()


@lru_cache(maxsize=1)
def _cached_catalog() -> tuple[dict[str, Any], str]:
    return _load_catalog_file(SOURCE_MAP_PATH)


def load_source_catalog(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Load the accepted map and its local asset digest."""
    if path is None:
        return _cached_catalog()
    return _load_catalog_file(Path(path))


def _sessions_for_section(
    entries: list[TimetableEntry],
) -> set[tuple[int, str | None, str | None]]:
    return {
        (
            entry.day_of_week,
            entry.slot_label,
            entry.classroom.room_code if entry.classroom else None,
        )
        for entry in entries
    }


def _source_sessions(section: dict[str, Any]) -> set[tuple[int, str | None, str | None]]:
    sessions = set()
    for session in section.get("sessions", []):
        day = DAY_NAMES.get(session.get("day"))
        if day is None:
            continue
        sessions.add((day, str(session.get("slot")), session.get("location")))
    return sessions


def _empty_period_response(
    source_period: dict[str, Any],
    sections_by_key: dict[str, dict[str, Any]],
) -> SourceIntakeResponse:
    source_id = source_period["source_id"]
    offerings: list[SourceIntakeOfferingResponse] = []

    for source_offering in source_period.get("offerings", []):
        subjects = []
        for subject in source_offering.get("subjects", []):
            section = sections_by_key.get(subject["section_key"], {})
            held = bool(section.get("held"))
            subjects.append(
                SourceIntakeSubjectResponse(
                    name=subject["name"],
                    rows=subject.get("rows", 0),
                    section_key=subject["section_key"],
                    delivery=subject.get("delivery", "exclusive"),
                    shared_with=subject.get("shared_with", []),
                    held=held,
                )
            )
        offerings.append(
            SourceIntakeOfferingResponse(
                source_id=source_offering["source_id"],
                name=source_offering["name"],
                name_zh=source_offering.get("name_zh"),
                schedule_rows=source_offering.get("schedule_rows", 0),
                mapping_state="SOURCE_ONLY",
                subject_count=len(subjects),
                shared_section_count=len(
                    {s.section_key for s in subjects if s.delivery == "shared"}
                ),
                held_section_count=len({s.section_key for s in subjects if s.held}),
                held=any(s.held for s in subjects),
                subjects=subjects,
            )
        )

    sections = [
        SourceIntakeSectionResponse(
            source_key=section["source_key"],
            course=section.get("course", ""),
            offerings=section.get("offerings", []),
            session_count=len(section.get("sessions", [])),
            shared=bool(section.get("shared")),
            held=bool(section.get("held")),
            mapping_state="HELD" if section.get("held") else "SOURCE_ONLY",
        )
        for section in source_period.get("sections", [])
    ]

    return SourceIntakeResponse(
        source_id=source_id,
        name=source_period.get("name", source_id),
        name_zh=source_period.get("name_zh"),
        source_identified=True,
        period_configured=False,
        timetable_imported=False,
        ready=False,
        active=False,
        readiness_state="PENDING",
        readiness_reason_codes=["PERIOD_NOT_CONFIGURED"],
        offering_count=len(source_period.get("offerings", [])),
        subject_count=sum(
            len(offering.get("subjects", []))
            for offering in source_period.get("offerings", [])
        ),
        section_count=len(source_period.get("sections", [])),
        shared_section_count=sum(
            1 for section in source_period.get("sections", []) if section.get("shared")
        ),
        held_section_count=sum(
            1 for section in source_period.get("sections", []) if section.get("held")
        ),
        source_session_count=sum(
            len(section.get("sessions", [])) for section in source_period.get("sections", [])
        ),
        offerings=offerings,
        sections=sections,
    )


def _configured_period_response(
    db: DBSession,
    source_period: dict[str, Any],
    period: AcademicPeriod,
) -> SourceIntakeResponse:
    source_id = source_period["source_id"]
    source_sections = {
        section["source_key"]: section for section in source_period.get("sections", [])
    }
    source_offerings = {
        offering["source_id"]: offering for offering in source_period.get("offerings", [])
    }

    persisted_offerings = (
        db.query(ProgramOffering)
        .filter(ProgramOffering.academic_period_id == period.id)
        .all()
    )
    offerings_by_source_key = {
        offering.source_key: offering for offering in persisted_offerings
    }

    sections = (
        db.query(ClassSection)
        .filter(ClassSection.academic_period_id == period.id)
        .all()
    )
    sections_by_source_key = {
        section.source_key: section for section in sections if section.source_key
    }

    links = (
        db.query(ClassSectionProgramOffering)
        .join(ClassSection, ClassSection.id == ClassSectionProgramOffering.class_section_id)
        .filter(ClassSection.academic_period_id == period.id)
        .all()
    )
    links_by_section: dict[Any, set[Any]] = {}
    for link in links:
        links_by_section.setdefault(link.class_section_id, set()).add(
            link.program_offering_id
        )
    offering_by_id = {offering.id: offering for offering in persisted_offerings}

    entries = (
        db.query(TimetableEntry)
        .join(ClassSection, ClassSection.id == TimetableEntry.class_section_id)
        .filter(
            ClassSection.academic_period_id == period.id,
            TimetableEntry.is_deleted.is_(False),
        )
        .all()
    )
    entries_by_section: dict[Any, list[TimetableEntry]] = {}
    for entry in entries:
        entries_by_section.setdefault(entry.class_section_id, []).append(entry)

    offered_ids = [offering.id for offering in persisted_offerings]
    assigned_counts = {}
    if offered_ids:
        assigned_counts = dict(
            db.query(AcademicPlacement.program_offering_id, func.count(AcademicPlacement.id))
            .filter(
                AcademicPlacement.ended_at.is_(None),
                AcademicPlacement.program_offering_id.in_(offered_ids),
            )
            .group_by(AcademicPlacement.program_offering_id)
            .all()
        )

    section_responses: list[SourceIntakeSectionResponse] = []
    mapped_section_count = 0
    verified_source_session_count = 0
    actual_session_count = 0
    links_complete = True
    all_sections_verified = True

    for section_key, source_section in source_sections.items():
        class_section = sections_by_source_key.get(section_key)
        if class_section:
            mapped_section_count += 1
        held = bool(source_section.get("held"))
        expected_sessions = _source_sessions(source_section)
        actual_sessions = (
            _sessions_for_section(entries_by_section.get(class_section.id, []))
            if class_section
            else set()
        )
        if class_section:
            actual_session_count += len(entries_by_section.get(class_section.id, []))
        verified = bool(class_section) and not held and expected_sessions.issubset(
            actual_sessions
        )
        if verified:
            verified_source_session_count += len(expected_sessions)

        if class_section:
            expected_offering_ids = set(source_section.get("offerings", []))
            linked_offering_ids = {
                offering_by_id[offering_id].source_id
                for offering_id in links_by_section.get(class_section.id, set())
                if offering_id in offering_by_id
            }
            if not expected_offering_ids.issubset(linked_offering_ids):
                links_complete = False
        else:
            links_complete = False
        if not verified:
            all_sections_verified = False

        mapping_state = "HELD" if held else ("MAPPED" if class_section else "MISSING")
        section_responses.append(
            SourceIntakeSectionResponse(
                source_key=section_key,
                course=source_section.get("course", ""),
                offerings=source_section.get("offerings", []),
                session_count=len(source_section.get("sessions", [])),
                shared=bool(source_section.get("shared")),
                held=held,
                mapping_state=mapping_state,
                mapped_class_section_id=class_section.id if class_section else None,
                imported_session_count=(
                    len(entries_by_section.get(class_section.id, []))
                    if class_section
                    else None
                ),
                timetable_verified=verified,
            )
        )

    offering_responses: list[SourceIntakeOfferingResponse] = []
    mapped_offering_count = 0
    for source_offering in source_period.get("offerings", []):
        source_offering_id = source_offering["source_id"]
        persisted = offerings_by_source_key.get(
            _source_key("offering", source_offering_id)
        )
        if persisted and persisted.academic_period_id == period.id:
            mapped_offering_count += 1
        linked_sections = (
            {link.class_section_id for link in links if link.program_offering_id == persisted.id}
            if persisted
            else set()
        )
        subjects = []
        for subject in source_offering.get("subjects", []):
            source_section = source_sections.get(subject["section_key"], {})
            subjects.append(
                SourceIntakeSubjectResponse(
                    name=subject["name"],
                    rows=subject.get("rows", 0),
                    section_key=subject["section_key"],
                    delivery=subject.get("delivery", "exclusive"),
                    shared_with=subject.get("shared_with", []),
                    held=bool(source_section.get("held")),
                )
            )
        subject_keys = {subject["section_key"] for subject in source_offering.get("subjects", [])}
        mapped_subject_count = (
            sum(
                1
                for key in subject_keys
                if key in sections_by_source_key
            )
            if persisted
            else None
        )
        offering_responses.append(
            SourceIntakeOfferingResponse(
                source_id=source_offering_id,
                name=source_offering["name"],
                name_zh=source_offering.get("name_zh"),
                schedule_rows=source_offering.get("schedule_rows", 0),
                mapping_state="MAPPED" if persisted else "SOURCE_ONLY",
                program_offering_id=persisted.id if persisted else None,
                subject_count=len(subjects),
                mapped_subject_count=mapped_subject_count,
                mapped_section_count=len(linked_sections) if persisted else None,
                assigned_student_count=(
                    assigned_counts.get(persisted.id, 0) if persisted else None
                ),
                shared_section_count=len(
                    {
                        subject["section_key"]
                        for subject in source_offering.get("subjects", [])
                        if source_sections.get(subject["section_key"], {}).get("shared")
                    }
                ),
                held_section_count=len(
                    {
                        subject["section_key"]
                        for subject in source_offering.get("subjects", [])
                        if source_sections.get(subject["section_key"], {}).get("held")
                    }
                ),
                held=any(
                    source_sections.get(subject["section_key"], {}).get("held")
                    for subject in source_offering.get("subjects", [])
                ),
                subjects=subjects,
            )
        )

    held_section_count = sum(1 for section in source_sections.values() if section.get("held"))
    source_session_count = sum(
        len(section.get("sessions", [])) for section in source_sections.values()
    )
    timetable_imported = bool(source_sections) and all_sections_verified and held_section_count == 0

    reasons: list[str] = []
    if mapped_offering_count != len(source_offerings):
        reasons.append("OFFERING_MAPPING_INCOMPLETE")
    if mapped_section_count != len(source_sections):
        reasons.append("SECTION_MAPPING_INCOMPLETE")
    if not links_complete:
        reasons.append("SECTION_OFFERING_LINK_INCOMPLETE")
    if held_section_count:
        reasons.append("HELD_SOURCE_SECTIONS")
    if not timetable_imported:
        reasons.append("TIMETABLE_NOT_IMPORTED")

    ready = not reasons
    if not source_sections:
        readiness_state = "UNKNOWN"
        reasons = ["SOURCE_SECTION_DATA_UNAVAILABLE"]
    elif ready:
        readiness_state = "READY"
    else:
        readiness_state = "PENDING"

    return SourceIntakeResponse(
        source_id=source_id,
        name=source_period.get("name", source_id),
        name_zh=source_period.get("name_zh"),
        source_identified=True,
        period=AcademicPeriodResponse.model_validate(period),
        period_configured=True,
        timetable_imported=timetable_imported,
        ready=ready,
        active=period.status == AcademicPeriodStatus.ACTIVE,
        readiness_state=readiness_state,
        readiness_reason_codes=reasons,
        offering_count=len(source_offerings),
        mapped_offering_count=mapped_offering_count,
        subject_count=sum(
            len(offering.get("subjects", []))
            for offering in source_period.get("offerings", [])
        ),
        section_count=len(source_sections),
        mapped_section_count=mapped_section_count,
        shared_section_count=sum(
            1 for section in source_sections.values() if section.get("shared")
        ),
        held_section_count=held_section_count,
        source_session_count=source_session_count,
        mapped_timetable_session_count=actual_session_count,
        verified_source_session_count=verified_source_session_count,
        offerings=offering_responses,
        sections=section_responses,
    )


def list_source_intakes(
    db: DBSession, *, source_path: str | Path | None = None
) -> SourceIntakeListResponse:
    catalog, catalog_sha256 = load_source_catalog(source_path)
    source_periods = catalog.get("periods", [])
    period_keys = [_source_key("period", period["source_id"]) for period in source_periods]

    periods = (
        db.query(AcademicPeriod).filter(AcademicPeriod.source_key.in_(period_keys)).all()
        if period_keys
        else []
    )
    periods_by_source_key = {
        period.source_key: period for period in periods if period.source_key
    }

    items = []
    for source_period in source_periods:
        period = periods_by_source_key.get(_source_key("period", source_period["source_id"]))
        if period:
            items.append(_configured_period_response(db, source_period, period))
        else:
            items.append(
                _empty_period_response(
                    source_period,
                    {
                        section["source_key"]: section
                        for section in source_period.get("sections", [])
                    },
                )
            )

    return SourceIntakeListResponse(
        source=catalog.get("source", str(SOURCE_MAP_PATH)),
        source_sha256=catalog.get("source_sha256", ""),
        catalog_sha256=catalog_sha256,
        counts={
            key: int(value)
            for key, value in catalog.get("counts", {}).items()
            if isinstance(value, int)
        },
        items=items,
    )
