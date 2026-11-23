"""University working-day resolver and calendar administration (Phase 1).

Two rules decide every date:

* Monday–Friday is a working day; Saturday and Sunday are not.
* A live declared exception replaces that default for its date.

Nothing is generated and nothing is cached: a date with no exception resolves
from its weekday every time, so a future date costs nothing until the
institution actually declares something about it.

Vacations are ranges, not loose days. A range is the parent record; each date in
it is materialised as a ``VACATION`` exception pointing at that range, so the
whole vacation can be created, extended, shortened or cancelled atomically. A
date the institution corrects individually is detached from its range and is
thereafter immune to range cancellation. No vacation date is ever invented here:
the institution supplies both bounds.

Writes are transactional with their audit entry. ``record_audit`` only stages a
row on the caller's session; this module commits the declaration and its audit
entry together, and rolls both back if either fails.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - SQLAlchemy resolves UUID at runtime
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession  # noqa: TC002

from app.audit import record_audit
from app.models.calendar import (
    CalendarDayType,
    CalendarVacationRange,
    UniversityCalendarDay,
)

if TYPE_CHECKING:
    from app.models.identity import User
    from app.schemas.calendar import (
        CalendarExceptionCorrect,
        CalendarExceptionCreate,
        CalendarExceptionVoid,
        VacationRangeAdjust,
        VacationRangeCancel,
        VacationRangeCreate,
    )

#: Python weekday numbers: Monday=0 … Sunday=6.
DEFAULT_WORKING_WEEKDAYS: frozenset[int] = frozenset({0, 1, 2, 3, 4})

#: Values that may be declared. ``WORKING`` and ``WEEKEND`` are derived from the
#: weekday, so storing them would duplicate the rule and create two spellings
#: for one fact.
STORED_DAY_TYPES: frozenset[CalendarDayType] = frozenset(
    {
        CalendarDayType.HOLIDAY,
        CalendarDayType.CLOSURE,
        CalendarDayType.EXCEPTIONAL_WORKING,
        CalendarDayType.VACATION,
    }
)

WORKING_DAY_TYPES: frozenset[CalendarDayType] = frozenset(
    {CalendarDayType.WORKING, CalendarDayType.EXCEPTIONAL_WORKING}
)

#: A reason is an institutional justification, not a label. Ten characters is
#: the shortest length that can carry one ("Snow day" is already eight).
MIN_REASON_LENGTH = 10

#: A coverage report is a read, not a generation: this bound keeps one request
#: from materialising an unbounded list of dates. The same bound is the maximum
#: length of one vacation range: an institution that needs more than a year of
#: vacation has a policy question, not a data-entry task.
MAX_RANGE_DAYS = 366

WEEKDAY_NAMES: tuple[str, ...] = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)


class CalendarError(ValueError):
    """A calendar refusal carrying a stable, localisable error code."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class ResolvedDay:
    """One date's classification and provenance."""

    calendar_date: date
    day_type: CalendarDayType
    is_working: bool
    source: str  # DEFAULT | EXCEPTION
    exception_id: uuid.UUID | None = None
    title: str | None = None


# ── Rule ──


def default_day_type(day: date) -> CalendarDayType:
    """The classification a date has with no exception."""
    if day.weekday() in DEFAULT_WORKING_WEEKDAYS:
        return CalendarDayType.WORKING
    return CalendarDayType.WEEKEND


def resolve_day(
    day: date, exception: UniversityCalendarDay | None = None
) -> ResolvedDay:
    """Resolve one date, preferring a live declaration over the weekday rule."""
    if exception is not None and not exception.is_void:
        day_type = CalendarDayType(exception.day_type)
        return ResolvedDay(
            calendar_date=day,
            day_type=day_type,
            is_working=day_type in WORKING_DAY_TYPES,
            source="EXCEPTION",
            exception_id=exception.id,
            title=exception.title,
        )

    day_type = default_day_type(day)
    return ResolvedDay(
        calendar_date=day,
        day_type=day_type,
        is_working=day_type in WORKING_DAY_TYPES,
        source="DEFAULT",
    )


def weekday_defaults() -> dict[str, str]:
    """The rule itself, so a report can state what it applied."""
    return {
        name: (
            CalendarDayType.WORKING.value
            if index in DEFAULT_WORKING_WEEKDAYS
            else CalendarDayType.WEEKEND.value
        )
        for index, name in enumerate(WEEKDAY_NAMES)
    }


def _live_exceptions(
    db: DBSession, start_date: date, end_date: date
) -> list[UniversityCalendarDay]:
    return (
        db.query(UniversityCalendarDay)
        .filter(
            UniversityCalendarDay.is_void.is_(False),
            UniversityCalendarDay.calendar_date >= start_date,
            UniversityCalendarDay.calendar_date <= end_date,
        )
        .order_by(UniversityCalendarDay.calendar_date)
        .all()
    )


def resolve_date(db: DBSession, day: date) -> ResolvedDay:
    exception = (
        db.query(UniversityCalendarDay)
        .filter(
            UniversityCalendarDay.calendar_date == day,
            UniversityCalendarDay.is_void.is_(False),
        )
        .first()
    )
    return resolve_day(day, exception)


def resolve_range(db: DBSession, start_date: date, end_date: date) -> list[ResolvedDay]:
    _check_range(start_date, end_date)
    by_date = {
        row.calendar_date: row
        for row in _live_exceptions(db, start_date, end_date)
    }
    resolved: list[ResolvedDay] = []
    current = start_date
    while current <= end_date:
        resolved.append(resolve_day(current, by_date.get(current)))
        current += timedelta(days=1)
    return resolved


# ── Validation ──


def _check_range(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise CalendarError(
            "CALENDAR_RANGE_INVALID",
            "The end date cannot precede the start date.",
            status_code=422,
        )
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise CalendarError(
            "CALENDAR_RANGE_TOO_LARGE",
            f"A calendar range may cover at most {MAX_RANGE_DAYS} days.",
            status_code=422,
        )


def _clear_reason(value: str | None, *, field: str = "reason") -> str:
    reason = (value or "").strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise CalendarError(
            "CALENDAR_REASON_REQUIRED",
            f"An explanation of at least {MIN_REASON_LENGTH} characters is required.",
            status_code=422,
        )
    return reason


def _stored_day_type(value: CalendarDayType | str) -> CalendarDayType:
    day_type = CalendarDayType(value)
    if day_type not in STORED_DAY_TYPES:
        raise CalendarError(
            "CALENDAR_DAY_TYPE_NOT_DECLARABLE",
            (
                f"{day_type.value} is derived from the weekday and cannot be "
                "declared as an exception."
            ),
            status_code=422,
        )
    return day_type


def _clear_title(value: str | None) -> str:
    title = (value or "").strip()
    if not title:
        raise CalendarError(
            "CALENDAR_TITLE_REQUIRED",
            "A title is required for a calendar exception.",
            status_code=422,
        )
    return title


def _reject_single_day_vacation(day_type: CalendarDayType) -> None:
    """A vacation date belongs to a range, never to a lone declaration.

    Without this guard a single ``VACATION`` day would exist with no parent, and
    "cancel the vacation" would silently leave it behind.
    """
    if day_type is CalendarDayType.VACATION:
        raise CalendarError(
            "CALENDAR_VACATION_REQUIRES_RANGE",
            (
                "A vacation is declared as a date range; use the vacation range "
                "endpoint instead of a single calendar exception."
            ),
            status_code=422,
        )


def _audit(
    db: DBSession,
    actor: User,
    request: Any,
    *,
    action: str,
    entity_id: uuid.UUID,
    context: dict[str, Any],
    entity_type: str = "university_calendar_day",
) -> None:
    record_audit(
        db,
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        context=context,
        request=request,
    )


# ── Reads ──


def get_exception(db: DBSession, exception_id: uuid.UUID) -> UniversityCalendarDay:
    exception = (
        db.query(UniversityCalendarDay)
        .filter(UniversityCalendarDay.id == exception_id)
        .first()
    )
    if exception is None:
        raise CalendarError(
            "CALENDAR_EXCEPTION_NOT_FOUND",
            "Calendar exception not found.",
            status_code=404,
        )
    return exception


def list_exceptions(
    db: DBSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    include_voided: bool = False,
) -> list[UniversityCalendarDay]:
    if start_date is not None and end_date is not None:
        _check_range(start_date, end_date)
    elif start_date is not None or end_date is not None:
        raise CalendarError(
            "CALENDAR_RANGE_INCOMPLETE",
            "Both a start and an end date are required to filter the calendar.",
            status_code=422,
        )

    query = db.query(UniversityCalendarDay)
    if start_date is not None and end_date is not None:
        query = query.filter(
            UniversityCalendarDay.calendar_date >= start_date,
            UniversityCalendarDay.calendar_date <= end_date,
        )
    if not include_voided:
        query = query.filter(UniversityCalendarDay.is_void.is_(False))
    return query.order_by(UniversityCalendarDay.calendar_date).all()


def build_coverage(
    db: DBSession, start_date: date, end_date: date
) -> dict[str, Any]:
    """Summarise a range: the rule, the declarations and their result."""
    _check_range(start_date, end_date)

    days = resolve_range(db, start_date, end_date)
    live = _live_exceptions(db, start_date, end_date)
    voided_count = (
        db.query(UniversityCalendarDay)
        .filter(
            UniversityCalendarDay.is_void.is_(True),
            UniversityCalendarDay.calendar_date >= start_date,
            UniversityCalendarDay.calendar_date <= end_date,
        )
        .count()
    )

    working = [day for day in days if day.is_working]
    default_working = [
        day for day in days if default_day_type(day.calendar_date) in WORKING_DAY_TYPES
    ]

    def dates_of(day_type: CalendarDayType) -> list[date]:
        return [day.calendar_date for day in days if day.day_type == day_type]

    return {
        "start_date": start_date,
        "end_date": end_date,
        "weekday_defaults": weekday_defaults(),
        "total_days": len(days),
        "default_working_days": len(default_working),
        "default_non_working_days": len(days) - len(default_working),
        "working_days": len(working),
        "non_working_days": len(days) - len(working),
        "holidays": dates_of(CalendarDayType.HOLIDAY),
        "closures": dates_of(CalendarDayType.CLOSURE),
        "exceptional_working_days": dates_of(CalendarDayType.EXCEPTIONAL_WORKING),
        "vacations": dates_of(CalendarDayType.VACATION),
        "exceptions": live,
        "voided_exception_count": voided_count,
        "days": days,
    }


# ── Writes ──


def create_exception(
    db: DBSession,
    data: CalendarExceptionCreate,
    actor: User,
    *,
    request: Any = None,
) -> UniversityCalendarDay:
    reason = _clear_reason(data.reason)
    day_type = _stored_day_type(data.day_type)
    _reject_single_day_vacation(day_type)
    title = _clear_title(data.title)

    existing = (
        db.query(UniversityCalendarDay)
        .filter(
            UniversityCalendarDay.calendar_date == data.calendar_date,
            UniversityCalendarDay.is_void.is_(False),
        )
        .first()
    )
    if existing is not None:
        raise CalendarError(
            "CALENDAR_DAY_CONFLICT",
            f"{data.calendar_date.isoformat()} already has a live calendar exception.",
        )

    exception = UniversityCalendarDay(
        calendar_date=data.calendar_date,
        day_type=day_type.value,
        title=title,
        reason=reason,
        is_void=False,
        created_by_id=actor.id,
        updated_by_id=actor.id,
    )

    previous_default = default_day_type(data.calendar_date)

    try:
        db.add(exception)
        db.flush()
        _audit(
            db,
            actor,
            request,
            action="academic.calendar.exception_created",
            entity_id=exception.id,
            context={
                "calendar_date": data.calendar_date.isoformat(),
                "previous_day_type": previous_default.value,
                "new_day_type": day_type.value,
                "title": title,
                "reason": reason,
            },
        )
        db.commit()
    except IntegrityError as exc:
        # A concurrent declaration for the same date is a conflict, not a
        # server failure. Re-check inside the failed transaction before
        # deciding which it was.
        db.rollback()
        if (
            db.query(UniversityCalendarDay)
            .filter(
                UniversityCalendarDay.calendar_date == data.calendar_date,
                UniversityCalendarDay.is_void.is_(False),
            )
            .first()
            is not None
        ):
            raise CalendarError(
                "CALENDAR_DAY_CONFLICT",
                (
                    f"{data.calendar_date.isoformat()} already has a live "
                    "calendar exception."
                ),
            ) from exc
        raise
    except Exception:
        # The declaration and its audit entry share one transaction: neither
        # survives without the other.
        db.rollback()
        raise

    db.refresh(exception)
    return exception


def correct_exception(
    db: DBSession,
    data: CalendarExceptionCorrect,
    actor: User,
    *,
    exception_id: uuid.UUID,
    request: Any = None,
) -> UniversityCalendarDay:
    exception = get_exception(db, exception_id)
    if exception.is_void:
        raise CalendarError(
            "CALENDAR_EXCEPTION_VOIDED",
            "A voided exception cannot be corrected; declare the date again.",
        )

    change_reason = _clear_reason(data.change_reason)

    previous_type = CalendarDayType(exception.day_type)
    previous_title = exception.title
    previous_reason = exception.reason

    new_type = (
        _stored_day_type(data.day_type)
        if data.day_type is not None
        else previous_type
    )
    if exception.calendar_range_id is None:
        _reject_single_day_vacation(new_type)
    new_title = (
        _clear_title(data.title) if data.title is not None else previous_title
    )
    new_reason = (
        _clear_reason(data.reason) if data.reason is not None else previous_reason
    )

    if (
        new_type is previous_type
        and new_title == previous_title
        and new_reason == previous_reason
    ):
        raise CalendarError(
            "CALENDAR_EXCEPTION_UNCHANGED",
            "The correction does not change the calendar exception.",
            status_code=422,
        )

    # A date the institution corrects on its own terms stops belonging to its
    # vacation range: from here on the range cannot cancel or shorten it away.
    detaching = (
        exception.calendar_range_id is not None
        and exception.detached_from_range_at is None
    )

    try:
        exception.day_type = new_type.value
        exception.title = new_title
        exception.reason = new_reason
        exception.updated_by_id = actor.id
        if detaching:
            exception.detached_from_range_at = datetime.utcnow()
        db.flush()
        _audit(
            db,
            actor,
            request,
            action="academic.calendar.exception_corrected",
            entity_id=exception.id,
            context={
                "calendar_date": exception.calendar_date.isoformat(),
                "previous_day_type": previous_type.value,
                "new_day_type": new_type.value,
                "previous_title": previous_title,
                "new_title": new_title,
                "previous_reason": previous_reason,
                "new_reason": new_reason,
                "change_reason": change_reason,
                "calendar_range_id": (
                    str(exception.calendar_range_id)
                    if exception.calendar_range_id is not None
                    else None
                ),
                "detached_from_range": detaching,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(exception)
    return exception


def void_exception(
    db: DBSession,
    data: CalendarExceptionVoid,
    actor: User,
    *,
    exception_id: uuid.UUID,
    request: Any = None,
) -> UniversityCalendarDay:
    exception = get_exception(db, exception_id)
    if exception.is_void:
        raise CalendarError(
            "CALENDAR_EXCEPTION_ALREADY_VOID",
            "That calendar exception is already void.",
        )

    reason = _clear_reason(data.reason)
    previous_type = CalendarDayType(exception.day_type)
    restored = default_day_type(exception.calendar_date)
    # Read the actor before mutating the row: an expired actor instance would
    # otherwise refresh here, and that refresh's autoflush would write a
    # half-voided row that violates ``ck_calendar_day_void_fields``.
    actor_id = actor.id

    try:
        exception.is_void = True
        exception.voided_at = datetime.utcnow()
        exception.voided_by_id = actor_id
        exception.void_reason = reason
        exception.updated_by_id = actor_id
        db.flush()
        _audit(
            db,
            actor,
            request,
            action="academic.calendar.exception_voided",
            entity_id=exception.id,
            context={
                "calendar_date": exception.calendar_date.isoformat(),
                "previous_day_type": previous_type.value,
                "new_day_type": restored.value,
                "previous_title": exception.title,
                "void_reason": reason,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(exception)
    return exception


# ── Vacation ranges ──


def _dates_between(start_date: date, end_date: date) -> list[date]:
    """Every date in a closed range. Bounded by ``MAX_RANGE_DAYS``."""
    return [
        start_date + timedelta(days=offset)
        for offset in range((end_date - start_date).days + 1)
    ]


def _range_days(db: DBSession, range_id: uuid.UUID) -> list[UniversityCalendarDay]:
    """The dates a vacation range materialised, live and voided alike."""
    return (
        db.query(UniversityCalendarDay)
        .filter(UniversityCalendarDay.calendar_range_id == range_id)
        .order_by(UniversityCalendarDay.calendar_date)
        .all()
    )


def _vacation_conflicts(db: DBSession, dates: list[date]) -> list[date]:
    """Live declarations already occupying any of ``dates``.

    A range never merges with, overrides or absorbs an existing exception: every
    conflict is reported so the institution resolves it deliberately.
    """
    if not dates:
        return []
    rows = (
        db.query(UniversityCalendarDay.calendar_date)
        .filter(
            UniversityCalendarDay.is_void.is_(False),
            UniversityCalendarDay.calendar_date.in_(dates),
        )
        .order_by(UniversityCalendarDay.calendar_date)
        .all()
    )
    return [row[0] for row in rows]


def _overlapping_range(
    db: DBSession, start_date: date, end_date: date, *, exclude_id: uuid.UUID | None = None
) -> CalendarVacationRange | None:
    query = db.query(CalendarVacationRange).filter(
        CalendarVacationRange.is_cancelled.is_(False),
        CalendarVacationRange.start_date <= end_date,
        CalendarVacationRange.end_date >= start_date,
    )
    if exclude_id is not None:
        query = query.filter(CalendarVacationRange.id != exclude_id)
    return query.first()


def _raise_conflicts(conflicts: list[date]) -> None:
    preview = ", ".join(day.isoformat() for day in conflicts[:5])
    suffix = " (and later dates)" if len(conflicts) > 5 else ""
    raise CalendarError(
        "CALENDAR_VACATION_RANGE_CONFLICT",
        (
            "The vacation range overlaps existing live calendar declarations "
            f"on {preview}{suffix}. Resolve or void them first; a vacation never "
            "overrides a holiday, closure, exceptional working day or another "
            "vacation."
        ),
    )


def _validate_vacation_span(
    db: DBSession,
    start_date: date,
    end_date: date,
    *,
    exclude_range_id: uuid.UUID | None = None,
) -> None:
    _check_range(start_date, end_date)
    overlap = _overlapping_range(
        db, start_date, end_date, exclude_id=exclude_range_id
    )
    if overlap is not None:
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_OVERLAP",
            (
                "That range overlaps the active vacation "
                f"\"{overlap.title}\" ({overlap.start_date.isoformat()} to "
                f"{overlap.end_date.isoformat()}). Adjust or cancel it first."
            ),
        )
    conflicts = _vacation_conflicts(db, _dates_between(start_date, end_date))
    if conflicts:
        _raise_conflicts(conflicts)


def _materialise_vacation(
    db: DBSession,
    range_: CalendarVacationRange,
    dates: list[date],
    actor: User,
) -> int:
    """Stage one ``VACATION`` row per date, owned by ``range_``."""
    actor_id = actor.id
    for day in dates:
        db.add(
            UniversityCalendarDay(
                calendar_date=day,
                day_type=CalendarDayType.VACATION.value,
                title=range_.title,
                reason=range_.reason,
                is_void=False,
                calendar_range_id=range_.id,
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
        )
    return len(dates)


def get_vacation_range(
    db: DBSession, range_id: uuid.UUID
) -> CalendarVacationRange:
    range_ = (
        db.query(CalendarVacationRange)
        .filter(CalendarVacationRange.id == range_id)
        .first()
    )
    if range_ is None:
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_NOT_FOUND",
            "Vacation range not found.",
            status_code=404,
        )
    return range_


def list_vacation_ranges(
    db: DBSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    include_cancelled: bool = False,
) -> list[CalendarVacationRange]:
    if start_date is not None and end_date is not None:
        _check_range(start_date, end_date)
    elif start_date is not None or end_date is not None:
        raise CalendarError(
            "CALENDAR_RANGE_INCOMPLETE",
            "Both a start and an end date are required to filter vacation ranges.",
            status_code=422,
        )

    query = db.query(CalendarVacationRange)
    if start_date is not None and end_date is not None:
        # Overlap, not containment: a vacation that starts before the window
        # still covers the dates the caller is asking about.
        query = query.filter(
            CalendarVacationRange.start_date <= end_date,
            CalendarVacationRange.end_date >= start_date,
        )
    if not include_cancelled:
        query = query.filter(CalendarVacationRange.is_cancelled.is_(False))
    return query.order_by(CalendarVacationRange.start_date).all()


def vacation_range_to_read(
    db: DBSession, range_: CalendarVacationRange
) -> dict[str, Any]:
    """A range plus the dates it currently owns.

    ``dates`` are the live dates still governed by the range; ``detached_dates``
    were corrected individually and are no longer cancelled with it;
    ``voided_date_count`` is the history a shortening or cancellation left
    behind.
    """
    rows = _range_days(db, range_.id)
    live = [row for row in rows if not row.is_void]
    return {
        "id": range_.id,
        "start_date": range_.start_date,
        "end_date": range_.end_date,
        "title": range_.title,
        "reason": range_.reason,
        "is_cancelled": range_.is_cancelled,
        "cancelled_at": range_.cancelled_at,
        "cancelled_by_id": range_.cancelled_by_id,
        "cancel_reason": range_.cancel_reason,
        "created_by_id": range_.created_by_id,
        "updated_by_id": range_.updated_by_id,
        "created_at": range_.created_at,
        "updated_at": range_.updated_at,
        "dates": [
            row.calendar_date
            for row in live
            if row.detached_from_range_at is None
        ],
        "detached_dates": [
            row.calendar_date
            for row in live
            if row.detached_from_range_at is not None
        ],
        "voided_date_count": len(rows) - len(live),
    }


def create_vacation_range(
    db: DBSession,
    data: VacationRangeCreate,
    actor: User,
    *,
    request: Any = None,
) -> CalendarVacationRange:
    """Materialise an institution-entered vacation range atomically.

    The range row, every date it owns and the audit entry commit together. A
    conflict on any date aborts the whole request: no half range can exist.
    """
    start_date, end_date = data.start_date, data.end_date
    _validate_vacation_span(db, start_date, end_date)
    title = _clear_title(data.title)
    reason = _clear_reason(data.reason)

    range_ = CalendarVacationRange(
        start_date=start_date,
        end_date=end_date,
        title=title,
        reason=reason,
        is_cancelled=False,
        created_by_id=actor.id,
        updated_by_id=actor.id,
    )

    try:
        db.add(range_)
        db.flush()
        count = _materialise_vacation(
            db, range_, _dates_between(start_date, end_date), actor
        )
        db.flush()
        _audit(
            db,
            actor,
            request,
            action="academic.calendar.vacation_range_created",
            entity_type="calendar_vacation_range",
            entity_id=range_.id,
            context={
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "day_count": count,
                "title": title,
                "reason": reason,
            },
        )
        db.commit()
    except IntegrityError as exc:
        # A concurrent vacation or declaration claimed one of these dates.
        db.rollback()
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_CONFLICT",
            (
                "A calendar declaration was created for one of these dates "
                "while the vacation was being entered. Nothing was saved; "
                "review the calendar and try again."
            ),
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(range_)
    return range_


def adjust_vacation_range(
    db: DBSession,
    data: VacationRangeAdjust,
    actor: User,
    *,
    range_id: uuid.UUID,
    request: Any = None,
) -> CalendarVacationRange:
    """Extend or shorten a vacation range without deleting its history.

    Added dates are materialised as new ``VACATION`` rows. Removed dates are
    voided, not deleted, so the declaration stays readable; a date the
    institution corrected individually is *preserved* and left live, because it
    is no longer the range's to withdraw.
    """
    range_ = get_vacation_range(db, range_id)
    if range_.is_cancelled:
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_CANCELLED",
            "A cancelled vacation range cannot be adjusted.",
        )

    change_reason = _clear_reason(data.change_reason, field="change_reason")
    new_start = data.start_date or range_.start_date
    new_end = data.end_date or range_.end_date
    _check_range(new_start, new_end)

    if new_start == range_.start_date and new_end == range_.end_date:
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_UNCHANGED",
            "The adjustment does not change the vacation range.",
            status_code=422,
        )

    previous_start, previous_end = range_.start_date, range_.end_date
    new_dates = set(_dates_between(new_start, new_end))
    previous_dates = set(_dates_between(previous_start, previous_end))
    added = sorted(new_dates - previous_dates)
    removed = sorted(previous_dates - new_dates)

    overlap = _overlapping_range(db, new_start, new_end, exclude_id=range_.id)
    if overlap is not None:
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_OVERLAP",
            (
                "That range would overlap the active vacation "
                f"\"{overlap.title}\" ({overlap.start_date.isoformat()} to "
                f"{overlap.end_date.isoformat()}). Adjust or cancel it first."
            ),
        )
    conflicts = _vacation_conflicts(db, added)
    if conflicts:
        _raise_conflicts(conflicts)

    # Read the actor before mutating any row: an expired actor instance would
    # otherwise refresh mid-update, and that refresh's autoflush would write a
    # half-voided row that violates ``ck_calendar_day_void_fields``.
    actor_id = actor.id

    try:
        # Void first: shortening then extending in one request must not leave a
        # removed date live, and the partial unique index is checked on insert.
        voided_dates: list[date] = []
        preserved_dates: list[date] = []
        if removed:
            rows = (
                db.query(UniversityCalendarDay)
                .filter(
                    UniversityCalendarDay.calendar_range_id == range_.id,
                    UniversityCalendarDay.is_void.is_(False),
                    UniversityCalendarDay.calendar_date.in_(removed),
                )
                .order_by(UniversityCalendarDay.calendar_date)
                .all()
            )
            now = datetime.utcnow()
            for row in rows:
                if row.detached_from_range_at is not None:
                    preserved_dates.append(row.calendar_date)
                    continue
                row.is_void = True
                row.voided_at = now
                row.voided_by_id = actor_id
                row.void_reason = change_reason
                row.updated_by_id = actor_id
                voided_dates.append(row.calendar_date)
            db.flush()

        added_count = _materialise_vacation(db, range_, added, actor)
        range_.start_date = new_start
        range_.end_date = new_end
        range_.updated_by_id = actor.id
        db.flush()

        _audit(
            db,
            actor,
            request,
            action="academic.calendar.vacation_range_adjusted",
            entity_type="calendar_vacation_range",
            entity_id=range_.id,
            context={
                "previous_start_date": previous_start.isoformat(),
                "previous_end_date": previous_end.isoformat(),
                "start_date": new_start.isoformat(),
                "end_date": new_end.isoformat(),
                "added_count": added_count,
                "voided_count": len(voided_dates),
                "voided_dates": [day.isoformat() for day in voided_dates],
                "preserved_dates": [day.isoformat() for day in preserved_dates],
                "change_reason": change_reason,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_CONFLICT",
            (
                "A calendar declaration was created for one of these dates "
                "while the range was being adjusted. Nothing was saved; review "
                "the calendar and try again."
            ),
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(range_)
    return range_


def cancel_vacation_range(
    db: DBSession,
    data: VacationRangeCancel,
    actor: User,
    *,
    range_id: uuid.UUID,
    request: Any = None,
) -> CalendarVacationRange:
    """Cancel a vacation range transactionally, never by deleting its dates.

    Every live date still governed by the range is voided with the actor, the
    timestamp and the cancellation reason, and the range itself keeps the same
    three fields. Dates corrected individually since are listed as preserved and
    left exactly as the institution set them.
    """
    range_ = get_vacation_range(db, range_id)
    if range_.is_cancelled:
        raise CalendarError(
            "CALENDAR_VACATION_RANGE_ALREADY_CANCELLED",
            "That vacation range is already cancelled.",
        )

    reason = _clear_reason(data.reason)
    now = datetime.utcnow()
    # Read the actor before mutating any row: an expired actor instance would
    # otherwise refresh mid-update, and that refresh's autoflush would write a
    # half-voided row that violates ``ck_calendar_day_void_fields``.
    actor_id = actor.id

    try:
        rows = (
            db.query(UniversityCalendarDay)
            .filter(
                UniversityCalendarDay.calendar_range_id == range_.id,
                UniversityCalendarDay.is_void.is_(False),
            )
            .order_by(UniversityCalendarDay.calendar_date)
            .all()
        )
        cancelled_dates: list[date] = []
        preserved_dates: list[date] = []
        for row in rows:
            if row.detached_from_range_at is not None:
                preserved_dates.append(row.calendar_date)
                continue
            row.is_void = True
            row.voided_at = now
            row.voided_by_id = actor_id
            row.void_reason = reason
            row.updated_by_id = actor_id
            cancelled_dates.append(row.calendar_date)

        range_.is_cancelled = True
        range_.cancelled_at = now
        range_.cancelled_by_id = actor.id
        range_.cancel_reason = reason
        range_.updated_by_id = actor.id
        db.flush()

        _audit(
            db,
            actor,
            request,
            action="academic.calendar.vacation_range_cancelled",
            entity_type="calendar_vacation_range",
            entity_id=range_.id,
            context={
                "start_date": range_.start_date.isoformat(),
                "end_date": range_.end_date.isoformat(),
                "cancelled_count": len(cancelled_dates),
                "cancelled_dates": [day.isoformat() for day in cancelled_dates],
                "preserved_dates": [day.isoformat() for day in preserved_dates],
                "reason": reason,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(range_)
    return range_


__all__ = [
    "DEFAULT_WORKING_WEEKDAYS",
    "MAX_RANGE_DAYS",
    "MIN_REASON_LENGTH",
    "STORED_DAY_TYPES",
    "CalendarError",
    "ResolvedDay",
    "adjust_vacation_range",
    "build_coverage",
    "cancel_vacation_range",
    "correct_exception",
    "create_exception",
    "create_vacation_range",
    "default_day_type",
    "get_exception",
    "get_vacation_range",
    "list_exceptions",
    "list_vacation_ranges",
    "resolve_date",
    "resolve_day",
    "resolve_range",
    "vacation_range_to_read",
    "void_exception",
    "weekday_defaults",
]
