"""Schemas for operational reports.

Reports are computed from authoritative tables at request time — nothing is
duplicated into a reporting store, so a report can never disagree with the
underlying record.
"""

from pydantic import BaseModel, Field


class CountItem(BaseModel):
    """A generic labelled count used by breakdown tables."""

    label: str
    sublabel: str | None = None
    count: int


class StudentReport(BaseModel):
    total: int
    active: int
    inactive: int
    graduated: int
    withdrawn: int
    suspended: int
    by_nationality: list[CountItem] = Field(default_factory=list)
    by_major: list[CountItem] = Field(default_factory=list)
    by_program: list[CountItem] = Field(default_factory=list)


class ImmigrationReport(BaseModel):
    total_students: int
    with_profile: int
    missing_information: int
    valid: int
    expiring_30_days: int
    expiring_90_days: int
    expired: int
    pending_change_requests: int
    by_document_type: list[CountItem] = Field(default_factory=list)

    # Phase 6 trust/cohort context. The expiry buckets above describe named
    # cohorts only in POINTER mode; untrusted students are counted separately
    # so no figure silently mixes the two.
    in_named_cohorts: int = 0
    untrusted_students: int = 0
    untrusted_by_reason: list[CountItem] = Field(default_factory=list)
    by_original_intake: list[CountItem] = Field(default_factory=list)


class HousingReport(BaseModel):
    total_buildings: int
    total_rooms: int
    total_beds: int
    occupied_beds: int
    available_beds: int
    out_of_service_beds: int
    rooms_full: int
    rooms_partial: int
    rooms_available: int
    rooms_out_of_service: int
    occupancy_rate: float
    students_housed: int
    students_not_housed: int


class AcademicReport(BaseModel):
    total_majors: int
    total_programs: int
    total_courses: int
    total_classes: int
    active_periods: int
    total_enrollments: int
    total_teacher_assignments: int
    enrollments_by_period: list[CountItem] = Field(default_factory=list)
    classes_by_status: list[CountItem] = Field(default_factory=list)


class OperationsReport(BaseModel):
    """Cross-module operational snapshot for the dashboard."""

    students: StudentReport
    immigration: ImmigrationReport
    housing: HousingReport
    academics: AcademicReport
    announcements_published: int
    open_support_tickets: int
    documents_stored: int


__all__ = [
    "AcademicReport",
    "CountItem",
    "HousingReport",
    "ImmigrationReport",
    "OperationsReport",
    "StudentReport",
]
