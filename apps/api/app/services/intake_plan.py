"""Plan academic intakes as real periods, not labels on student rows.

The institution thinks in intake names ("2025 Fall", "2027 Spring"). V2 models
that as an ``AcademicPeriod`` plus one ``ProgramOffering`` per intake-specific
programme; an admission and its placement point at the offering, so a student's
intake is derived from the academic structure rather than stored as a string.

Planning is additive and idempotent:

* creating an intake twice with the same values reports ``EXISTING``;
* creating it twice with different dates reports ``CONFLICT`` and changes
  nothing — an intake that has students must not have its dates rewritten by a
  spreadsheet;
* a future intake can never be created ACTIVE, because that would start
  students' academic life before the institution does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from app.audit import record_audit
from app.models.academic import (
    AcademicPeriod,
    AcademicPeriodStatus,
    Program,
    ProgramOffering,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.orm import Session as DBSession


class IntakePlanError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class IntakeOfferingSpec:
    source_id: str
    name: str
    program_code: str | None = None


@dataclass(frozen=True)
class IntakeSpec:
    code: str
    name: str
    start_date: date
    end_date: date
    status: str = AcademicPeriodStatus.PLANNED.value
    offerings: tuple[IntakeOfferingSpec, ...] = field(default_factory=tuple)


def _offering_key(intake_code: str, source_id: str) -> str:
    return f"intake:{intake_code}:{source_id}"


def _validate(spec: IntakeSpec, *, today: date) -> None:
    if not spec.code.strip():
        raise IntakePlanError("INTAKE_CODE_REQUIRED", "An intake code is required.")
    if spec.end_date < spec.start_date:
        raise IntakePlanError(
            "INTAKE_DATES_INVALID",
            f"{spec.code}: end date is before start date.",
        )
    if spec.status not in {status.value for status in AcademicPeriodStatus}:
        raise IntakePlanError(
            "VALIDATION_ERROR", f"{spec.code}: unknown period status {spec.status}."
        )
    if spec.status == AcademicPeriodStatus.ACTIVE and spec.start_date > today:
        # A future intake is prepared, not started. Activating it would make
        # its students appear current before the institution opens it.
        raise IntakePlanError(
            "FUTURE_INTAKE_CANNOT_BE_ACTIVE",
            f"{spec.code} starts in the future and must be planned, not active.",
        )


def plan_intakes(
    db: DBSession,
    specs: list[IntakeSpec],
    *,
    actor_id: uuid.UUID | None = None,
    today: date | None = None,
    request=None,
) -> dict:
    """Create missing intakes and report what already exists.

    Returns a report with one entry per intake and per offering. Nothing that
    already exists with different data is modified.
    """
    current_day = today or date.today()
    results: list[dict] = []

    for spec in specs:
        _validate(spec, today=current_day)

        period = (
            db.query(AcademicPeriod).filter(AcademicPeriod.code == spec.code).first()
        )
        if period is not None:
            differences = []
            if period.start_date != spec.start_date:
                differences.append("start_date")
            if period.end_date != spec.end_date:
                differences.append("end_date")
            if period.name != spec.name:
                differences.append("name")
            if differences:
                results.append(
                    {
                        "intake": spec.code,
                        "status": "CONFLICT",
                        "reason": "EXISTING_PERIOD_DIFFERS",
                        "fields": differences,
                        "period_id": period.id,
                        "offerings_created": 0,
                    }
                )
                continue
            results.append(
                {
                    "intake": spec.code,
                    "status": "EXISTING",
                    "period_id": period.id,
                    "period_status": period.status,
                    "offerings_created": 0,
                }
            )
        else:
            period = AcademicPeriod(
                code=spec.code,
                name=spec.name,
                start_date=spec.start_date,
                end_date=spec.end_date,
                status=spec.status,
            )
            db.add(period)
            db.flush()
            record_audit(
                db,
                action="academic.intake.planned",
                actor_id=actor_id,
                entity_type="academic_period",
                entity_id=period.id,
                context={
                    "intake": spec.code,
                    "status": spec.status,
                    "start_date": spec.start_date.isoformat(),
                    "end_date": spec.end_date.isoformat(),
                },
                request=request,
            )
            results.append(
                {
                    "intake": spec.code,
                    "status": "CREATED",
                    "period_id": period.id,
                    "period_status": period.status,
                    "offerings_created": 0,
                }
            )

        created = 0
        offering_results: list[dict] = []
        for offering_spec in spec.offerings:
            key = _offering_key(spec.code, offering_spec.source_id)
            existing = (
                db.query(ProgramOffering)
                .filter(ProgramOffering.source_key == key)
                .first()
            )
            if existing is not None:
                offering_results.append(
                    {
                        "source_id": offering_spec.source_id,
                        "status": "EXISTING",
                        "program_offering_id": existing.id,
                    }
                )
                continue

            program = None
            if offering_spec.program_code:
                program = (
                    db.query(Program)
                    .filter(Program.code == offering_spec.program_code)
                    .first()
                )
                if program is None:
                    offering_results.append(
                        {
                            "source_id": offering_spec.source_id,
                            "status": "UNRESOLVED_PROGRAM",
                            "program_code": offering_spec.program_code,
                        }
                    )
                    continue

            offering = ProgramOffering(
                academic_period_id=period.id,
                program_id=program.id if program else None,
                source_id=offering_spec.source_id,
                source_key=key,
                name=offering_spec.name,
            )
            db.add(offering)
            db.flush()
            created += 1
            offering_results.append(
                {
                    "source_id": offering_spec.source_id,
                    "status": "CREATED",
                    "program_offering_id": offering.id,
                }
            )

        results[-1]["offerings_created"] = created
        results[-1]["offerings"] = offering_results

    db.commit()

    return {
        "intakes": results,
        "created": sum(1 for item in results if item["status"] == "CREATED"),
        "existing": sum(1 for item in results if item["status"] == "EXISTING"),
        "conflicts": sum(1 for item in results if item["status"] == "CONFLICT"),
    }


def intake_summary(db: DBSession) -> list[dict]:
    """Per-intake counts, so an operator can see what a period actually holds."""
    from sqlalchemy import func

    from app.models.academic import ClassSection
    from app.models.admission import AcademicPlacement

    periods = db.query(AcademicPeriod).order_by(AcademicPeriod.start_date).all()
    summary: list[dict] = []
    for period in periods:
        offerings = (
            db.query(ProgramOffering)
            .filter(ProgramOffering.academic_period_id == period.id)
            .count()
        )
        sections = (
            db.query(ClassSection)
            .filter(ClassSection.academic_period_id == period.id)
            .count()
        )
        offering_ids = [
            row.id
            for row in db.query(ProgramOffering.id)
            .filter(ProgramOffering.academic_period_id == period.id)
            .all()
        ]
        students = 0
        if offering_ids:
            students = (
                db.query(func.count(func.distinct(AcademicPlacement.student_id)))
                .filter(
                    AcademicPlacement.program_offering_id.in_(offering_ids),
                    AcademicPlacement.ended_at.is_(None),
                )
                .scalar()
                or 0
            )
        summary.append(
            {
                "period_id": period.id,
                "code": period.code,
                "name": period.name,
                "status": period.status,
                "start_date": period.start_date,
                "end_date": period.end_date,
                "offerings": offerings,
                "sections": sections,
                "placed_students": students,
            }
        )
    return summary


__all__ = [
    "IntakeOfferingSpec",
    "IntakePlanError",
    "IntakeSpec",
    "intake_summary",
    "plan_intakes",
]
