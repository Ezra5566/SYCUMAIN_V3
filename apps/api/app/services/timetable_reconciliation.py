"""Reconcile an existing timetable against the academic structure.

The imported timetable is treated as evidence, not truth. This module reads it
and reports where it does not fit the academic model:

* a slot whose section belongs to a different intake than its offering;
* a slot pointing at a room that is missing or out of service;
* overlapping sessions for one room or one teacher within one intake;
* a section with no teacher, no offering link, or no slot at all;
* a student enrolled in a section from another intake.

It performs **no writes**. A reconciliation report is the input to a repair
decision, and the repair itself goes through the normal audited endpoints one
row at a time. Deleting or rewriting imported timetable rows automatically
would destroy the only evidence of what the source actually said.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import func

from app.models.academic import (
    AcademicPeriod,
    ClassroomStatus,
    ClassSection,
    ClassSectionProgramOffering,
    Enrollment,
    ProgramOffering,
    TeacherAssignment,
    TimetableEntry,
)
from app.models.admission import AcademicPlacement
from app.models.identity import Staff

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session as DBSession

#: Severity drives what the office may ignore. BLOCKING findings mean the
#: schedule cannot be trusted for the affected section; WARNING findings are
#: incomplete data that a person must fill in; INFO is context.
BLOCKING = "BLOCKING"
WARNING = "WARNING"
INFO = "INFO"

_ACTION_BY_CODE = {
    "TIMETABLE_INVALID_INTERVAL": ("FIX_TIMES", BLOCKING),
    "TIMETABLE_INVALID_WEEKDAY": ("FIX_TIMES", BLOCKING),
    "TIMETABLE_DUPLICATE_SLOT": ("REMOVE_DUPLICATE", BLOCKING),
    "TIMETABLE_ROOM_DOUBLE_BOOKED": ("MOVE_SESSION", BLOCKING),
    "TIMETABLE_TEACHER_DOUBLE_BOOKED": ("REASSIGN_OR_MOVE", BLOCKING),
    "CLASSROOM_NOT_AVAILABLE": ("MOVE_SESSION", BLOCKING),
    "SECTION_OFFERING_PERIOD_MISMATCH": ("RELINK_SECTION", BLOCKING),
    "CROSS_INTAKE_ENROLLMENT": ("REVIEW_ENROLLMENT", BLOCKING),
    "SECTION_WITHOUT_OFFERING": ("LINK_SECTION", WARNING),
    "SECTION_WITHOUT_TEACHER": ("ASSIGN_TEACHER", WARNING),
    "SECTION_WITHOUT_TIMETABLE": ("SCHEDULE_SECTION", WARNING),
    "TIMETABLE_MISSING_CLASSROOM": ("ASSIGN_CLASSROOM", WARNING),
    "TIMETABLE_ORPHANED_SECTION": ("REVIEW_SECTION", BLOCKING),
}

MAX_ITEMS_PER_CODE = 200


def _overlaps(left_start: time, left_end: time, right_start: time, right_end: time) -> bool:
    return left_start < right_end and right_start < left_end


def reconcile_timetable(
    db: DBSession, *, period_id: uuid.UUID | None = None
) -> dict:
    """Return findings for one intake, or for every intake when omitted."""
    periods = db.query(AcademicPeriod).order_by(AcademicPeriod.start_date).all()
    if period_id is not None:
        periods = [period for period in periods if period.id == period_id]

    entry_query = (
        db.query(TimetableEntry)
        .join(ClassSection, ClassSection.id == TimetableEntry.class_section_id)
        .join(AcademicPeriod, AcademicPeriod.id == ClassSection.academic_period_id)
        .filter(TimetableEntry.is_deleted.is_(False))
    )
    if period_id is not None:
        entry_query = entry_query.filter(AcademicPeriod.id == period_id)
    entries = entry_query.all()

    section_query = db.query(ClassSection)
    if period_id is not None:
        section_query = section_query.filter(ClassSection.academic_period_id == period_id)
    sections = section_query.all()

    offered_by_section: dict = defaultdict(list)
    links = (
        db.query(ClassSectionProgramOffering, ProgramOffering)
        .join(
            ProgramOffering,
            ProgramOffering.id == ClassSectionProgramOffering.program_offering_id,
        )
        .all()
    )
    for link, offering in links:
        offered_by_section[link.class_section_id].append(offering)

    teachers_by_section: dict = defaultdict(list)
    for assignment in (
        db.query(TeacherAssignment)
        .filter(TeacherAssignment.is_active.is_(True))
        .all()
    ):
        teachers_by_section[assignment.class_section_id].append(assignment)

    staff_by_id = {
        staff.id: staff
        for staff in db.query(Staff).all()
    }

    entries_by_section: dict = defaultdict(list)
    for entry in entries:
        entries_by_section[entry.class_section_id].append(entry)

    findings: list[dict] = []

    def add(code: str, *, entity_type: str, entity_id, detail: dict) -> None:
        action, severity = _ACTION_BY_CODE.get(code, ("REVIEW", WARNING))
        findings.append(
            {
                "code": code,
                "severity": severity,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "suggested_action": action,
                "detail": detail,
            }
        )

    for entry in entries:
        section = entry.class_section
        period = section.academic_period if section else None

        if entry.day_of_week is None or not 0 <= entry.day_of_week <= 6:
            add(
                "TIMETABLE_INVALID_WEEKDAY",
                entity_type="timetable_entry",
                entity_id=entry.id,
                detail={"day_of_week": entry.day_of_week},
            )

        if entry.start_time is None or entry.end_time is None or entry.start_time >= entry.end_time:
            add(
                "TIMETABLE_INVALID_INTERVAL",
                entity_type="timetable_entry",
                entity_id=entry.id,
                detail={
                    "start_time": str(entry.start_time),
                    "end_time": str(entry.end_time),
                },
            )

        if entry.classroom_id is None:
            add(
                "TIMETABLE_MISSING_CLASSROOM",
                entity_type="timetable_entry",
                entity_id=entry.id,
                detail={"class_section_id": entry.class_section_id},
            )
        elif entry.classroom is not None and entry.classroom.status != ClassroomStatus.AVAILABLE:
            add(
                "CLASSROOM_NOT_AVAILABLE",
                entity_type="timetable_entry",
                entity_id=entry.id,
                detail={
                    "room_code": entry.classroom.room_code,
                    "status": entry.classroom.status,
                },
            )

        if period is None:
            add(
                "TIMETABLE_ORPHANED_SECTION",
                entity_type="timetable_entry",
                entity_id=entry.id,
                detail={"class_section_id": entry.class_section_id},
            )

    # Duplicate slots: same section, day and interval, different row.
    seen_slots: dict = defaultdict(list)
    for entry in entries:
        if entry.start_time is None or entry.end_time is None:
            continue
        seen_slots[
            (entry.class_section_id, entry.day_of_week, entry.start_time, entry.end_time)
        ].append(entry)
    for (_section_id, _day, _start, _end), rows in seen_slots.items():
        if len(rows) > 1:
            add(
                "TIMETABLE_DUPLICATE_SLOT",
                entity_type="class_section",
                entity_id=rows[0].class_section_id,
                detail={
                    "entry_ids": [str(row.id) for row in rows],
                    "day_of_week": _day,
                    "start_time": str(_start),
                    "end_time": str(_end),
                },
            )

    # Room and teacher double-booking, compared only within one intake.
    by_room: dict = defaultdict(list)
    by_teacher: dict = defaultdict(list)
    for entry in entries:
        if entry.start_time is None or entry.end_time is None:
            continue
        period = entry.class_section.academic_period if entry.class_section else None
        if entry.classroom_id is not None:
            room_key = (period.id if period else None, entry.day_of_week, entry.classroom_id)
            by_room[room_key].append(entry)
        for assignment in teachers_by_section.get(entry.class_section_id, []):
            teacher_key = (
                period.id if period else None,
                entry.day_of_week,
                assignment.staff_id,
            )
            by_teacher[teacher_key].append(entry)

    checked: set = set()
    for (period_key, day, room_id), rows in by_room.items():
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                if left.class_section_id == right.class_section_id:
                    continue
                if _overlaps(left.start_time, left.end_time, right.start_time, right.end_time):
                    key = tuple(sorted([left.id, right.id], key=str))
                    if key in checked:
                        continue
                    checked.add(key)
                    add(
                        "TIMETABLE_ROOM_DOUBLE_BOOKED",
                        entity_type="classroom",
                        entity_id=room_id,
                        detail={
                            "period_id": period_key,
                            "day_of_week": day,
                            "entry_ids": [str(left.id), str(right.id)],
                            "section_ids": [
                                str(left.class_section_id),
                                str(right.class_section_id),
                            ],
                        },
                    )

    checked.clear()
    for (period_key, day, staff_id), rows in by_teacher.items():
        for index, left in enumerate(rows):
            for right in rows[index + 1:]:
                if left.class_section_id == right.class_section_id:
                    continue
                if _overlaps(left.start_time, left.end_time, right.start_time, right.end_time):
                    key = tuple(sorted([left.id, right.id], key=str))
                    if key in checked:
                        continue
                    checked.add(key)
                    staff = staff_by_id.get(staff_id)
                    add(
                        "TIMETABLE_TEACHER_DOUBLE_BOOKED",
                        entity_type="staff",
                        entity_id=staff_id,
                        detail={
                            "period_id": period_key,
                            "day_of_week": day,
                            "teacher": (
                                f"{staff.first_name} {staff.last_name}" if staff else None
                            ),
                            "entry_ids": [str(left.id), str(right.id)],
                        },
                    )

    # Structure checks per section.
    for section in sections:
        offerings = offered_by_section.get(section.id, [])
        if not offerings:
            add(
                "SECTION_WITHOUT_OFFERING",
                entity_type="class_section",
                entity_id=section.id,
                detail={
                    "section_code": section.section_code,
                    "period": section.academic_period.code,
                },
            )
        for offering in offerings:
            if offering.academic_period_id != section.academic_period_id:
                add(
                    "SECTION_OFFERING_PERIOD_MISMATCH",
                    entity_type="class_section",
                    entity_id=section.id,
                    detail={
                        "section_period": section.academic_period.code,
                        "offering_period_id": str(offering.academic_period_id),
                        "offering": offering.name,
                    },
                )
        if not teachers_by_section.get(section.id):
            add(
                "SECTION_WITHOUT_TEACHER",
                entity_type="class_section",
                entity_id=section.id,
                detail={
                    "section_code": section.section_code,
                    "course": section.course.code if section.course else None,
                },
            )
        if not entries_by_section.get(section.id):
            add(
                "SECTION_WITHOUT_TIMETABLE",
                entity_type="class_section",
                entity_id=section.id,
                detail={
                    "section_code": section.section_code,
                    "course": section.course.code if section.course else None,
                },
            )

    # Students enrolled in a section that belongs to another intake than their
    # current placement's intake.
    current_offerings = (
        db.query(AcademicPlacement.student_id, ProgramOffering.academic_period_id)
        .join(ProgramOffering, ProgramOffering.id == AcademicPlacement.program_offering_id)
        .filter(AcademicPlacement.ended_at.is_(None))
        .all()
    )
    student_period = dict(current_offerings)

    enrollments = (
        db.query(Enrollment, ClassSection)
        .join(ClassSection, ClassSection.id == Enrollment.class_section_id)
        .filter(Enrollment.status == "ENROLLED")
        .all()
    )
    for enrollment, section in enrollments:
        if period_id is not None and section.academic_period_id != period_id:
            continue
        expected = student_period.get(enrollment.student_id)
        if expected is not None and expected != section.academic_period_id:
            add(
                "CROSS_INTAKE_ENROLLMENT",
                entity_type="enrollment",
                entity_id=enrollment.id,
                detail={
                    "student_id": str(enrollment.student_id),
                    "section_period": section.academic_period.code,
                },
            )

    counts = Counter(finding["code"] for finding in findings)
    severity_counts = Counter(finding["severity"] for finding in findings)

    grouped: list[dict] = []
    for code, count in sorted(counts.items()):
        sample = [finding for finding in findings if finding["code"] == code][
            :MAX_ITEMS_PER_CODE
        ]
        grouped.append(
            {
                "code": code,
                "count": count,
                "items_truncated": count > MAX_ITEMS_PER_CODE,
                "items": sample,
            }
        )

    deleted = (
        db.query(func.count(TimetableEntry.id))
        .filter(TimetableEntry.is_deleted.is_(True))
        .scalar()
        or 0
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": {
            "period_ids": [str(period.id) for period in periods],
            "period_codes": [period.code for period in periods],
        },
        "totals": {
            "periods": len(periods),
            "sections": len(sections),
            "live_entries": len(entries),
            "retired_entries": deleted,
            "findings": len(findings),
            "blocking": severity_counts[BLOCKING],
            "warnings": severity_counts[WARNING],
        },
        "status": "CLEAN" if not findings else (
            "BLOCKING" if severity_counts[BLOCKING] else "REVIEW"
        ),
        "findings": grouped,
        "destructive_actions": False,
    }


__all__ = ["reconcile_timetable", "BLOCKING", "WARNING", "INFO"]
