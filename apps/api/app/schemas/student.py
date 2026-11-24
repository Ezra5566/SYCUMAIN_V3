"""Student Pydantic schemas for API request/response validation."""

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.identity import StudentStatus

# Same deliberately permissive rule as account creation: the local part allows
# the characters the campus actually uses, the domain must contain a dot.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def is_valid_email(value: str) -> bool:
    """Shared email check so student and account validation cannot drift."""
    return bool(EMAIL_PATTERN.match(value))

# --- Request Schemas ---


class StudentCreate(BaseModel):
    """Schema for creating a new student."""

    user_id: uuid.UUID
    student_id: str = Field(..., min_length=1, max_length=50)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    preferred_name: str | None = Field(None, max_length=100)
    date_of_birth: datetime | None = None
    gender: str | None = Field(None, max_length=20)
    nationality: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)
    emergency_contact_name: str | None = Field(None, max_length=255)
    emergency_contact_phone: str | None = Field(None, max_length=50)


class StudentUpdate(BaseModel):
    """Schema for updating a student (partial update).

    Management-only. Phase 8b retires all three direct-placement fields here;
    they remain in the contract only so a legacy caller receives the stable
    ``PLACEMENT_DIRECT_WRITE_RETIRED`` refusal instead of a silent no-op. The
    institutional identifier remains editable because a typo discovered after
    onboarding has to be fixable without recreating the record.
    """

    student_id: str | None = Field(None, min_length=1, max_length=50)
    first_name: str | None = Field(None, min_length=1, max_length=100)
    last_name: str | None = Field(None, min_length=1, max_length=100)
    preferred_name: str | None = Field(None, max_length=100)
    date_of_birth: datetime | None = None
    gender: str | None = Field(None, max_length=20)
    nationality: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)
    emergency_contact_name: str | None = Field(None, max_length=255)
    emergency_contact_phone: str | None = Field(None, max_length=50)
    status: StudentStatus | None = None
    major_id: uuid.UUID | None = Field(
        None,
        description="Retired: use the admission/placement workflow.",
    )
    program_id: uuid.UUID | None = Field(
        None,
        description="Retired: use the admission/placement workflow.",
    )
    program_offering_id: uuid.UUID | None = Field(
        None,
        description="Retired: use the admission/placement workflow.",
    )

    @field_validator("student_id")
    @classmethod
    def _clean_student_number(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Student number cannot be blank.")
        return cleaned


class StudentProgramOfferingUpdate(BaseModel):
    """Retired direct period-specific program assignment.

    The contract remains only so a legacy caller receives the stable
    ``PLACEMENT_DIRECT_WRITE_RETIRED`` refusal. There is no direct-write
    fallback: placement and programme changes use their workflows.
    """

    program_offering_id: uuid.UUID | None
    reason: str | None = Field(None, max_length=200)


class StudentSelfUpdate(BaseModel):
    """Fields a student may maintain on their own record.

    This allowlist is the authorization boundary for self-service: anything
    absent here (student number, status, official name, programme) cannot be
    changed by a student, no matter what the request body contains.
    """

    preferred_name: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)
    emergency_contact_name: str | None = Field(None, max_length=255)
    emergency_contact_phone: str | None = Field(None, max_length=50)


class StudentAcademicUpdate(BaseModel):
    """A retired self-service direct-placement selection.

    All three fields remain in the contract only so a populated legacy body is
    detected and refused. Programme changes use the dedicated Phase 4
    admission-change endpoint instead.
    """

    major_id: uuid.UUID | None = None
    program_id: uuid.UUID | None = None
    program_offering_id: uuid.UUID | None = None


class StudentStatusUpdate(BaseModel):
    """Schema for updating student status (archive/deactivate)."""

    status: StudentStatus


class StudentPlacementStatus(BaseModel):
    """Whether a student may still choose their own academic placement.

    Exposed so the UI can show either a selection form or a read-only value
    with "contact the office to change this". ``can_select`` is always false;
    the academic fields are derived from the effective admission and current
    placement, not from Student columns.
    """

    can_select: bool
    major_id: uuid.UUID | None = None
    major_name: str | None = None
    program_id: uuid.UUID | None = None
    program_name: str | None = None
    program_offering_id: uuid.UUID | None = None
    program_offering_name: str | None = None
    program_offering_period_id: uuid.UUID | None = None
    program_offering_period_name: str | None = None


class StudentOnboard(BaseModel):
    """Onboard a student: create the record and its login account together.

    This is the institutional onboarding path. The account and the student
    record are created in one transaction, so a failure never leaves an
    orphaned account or a student who cannot sign in.
    """

    student_id: str = Field(..., min_length=1, max_length=50)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., max_length=255)
    preferred_name: str | None = Field(None, max_length=100)
    date_of_birth: datetime | None = None
    gender: str | None = Field(None, max_length=20)
    nationality: str | None = Field(None, max_length=100)
    phone: str | None = Field(None, max_length=50)
    emergency_contact_name: str | None = Field(None, max_length=255)
    emergency_contact_phone: str | None = Field(None, max_length=50)
    major_id: uuid.UUID | None = Field(
        None,
        description="Retired: select an offering to create admission history.",
    )
    program_id: uuid.UUID | None = Field(
        None,
        description="Retired: select an offering to create admission history.",
    )
    program_offering_id: uuid.UUID | None = None
    # Phase 1 admission registration. An offering requires these to be valid
    # while admission writes are enabled; an offering is refused when they are
    # disabled rather than falling back to a projection write.
    admission_intake_id: uuid.UUID | None = None
    initial_admission_status: Literal["PENDING", "ADMITTED", "ACTIVE"] | None = None

    @field_validator("student_id")
    @classmethod
    def _valid_student_number(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Student number is required.")
        return cleaned

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not is_valid_email(normalized):
            raise ValueError("A valid email address is required.")
        return normalized


class StudentBulkStatusUpdate(BaseModel):
    """Apply one status change to many students at once."""

    student_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)
    status: StudentStatus


# --- Response Schemas ---


class StudentBrief(BaseModel):
    """Brief student representation for list views."""

    id: uuid.UUID
    # The account id. Student *records* are keyed differently from the modules
    # that reference a person (housing assignments use users.id), so callers
    # that pick a student from a list need this to act without a second request.
    user_id: uuid.UUID
    student_id: str
    first_name: str
    last_name: str
    preferred_name: str | None = None
    nationality: str | None = None
    status: StudentStatus
    user_email: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class StudentDetail(BaseModel):
    """Detailed student representation for profile views."""

    id: uuid.UUID
    user_id: uuid.UUID
    student_id: str
    first_name: str
    last_name: str
    preferred_name: str | None = None
    date_of_birth: datetime | None = None
    gender: str | None = None
    nationality: str | None = None

    # Profile photo is stored in private object storage; clients fetch it from
    # the authorization-checked endpoint rather than being handed a URL.
    has_photo: bool = False
    photo_updated_at: datetime | None = None

    phone: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    status: StudentStatus
    major_id: uuid.UUID | None = None
    major_name: str | None = None
    program_id: uuid.UUID | None = None
    program_name: str | None = None
    program_offering_id: uuid.UUID | None = None
    program_offering_name: str | None = None
    program_offering_period_id: uuid.UUID | None = None
    program_offering_period_name: str | None = None
    created_at: datetime
    updated_at: datetime

    # Related info
    user_email: str | None = None
    user_username: str | None = None
    user_is_active: bool | None = None

    model_config = {"from_attributes": True}


class PaginationMeta(BaseModel):
    """Pagination metadata."""

    page: int
    page_size: int
    total: int
    total_pages: int


class StudentListResponse(BaseModel):
    """Paginated student list response."""

    items: list[StudentBrief]
    meta: PaginationMeta


class StudentAccountResponse(BaseModel):
    """A student's linked login account, without credential material."""

    user_id: uuid.UUID
    email: str
    username: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None = None


class StudentOnboardedResponse(BaseModel):
    """Result of onboarding a student.

    ``temporary_password`` is returned exactly once so an administrator can
    hand it to the student. It is never stored in plaintext and cannot be
    retrieved again — a reset issues a new one instead.
    """

    student: StudentDetail
    account: StudentAccountResponse
    temporary_password: str


class BulkResultItem(BaseModel):
    """Per-student outcome of a bulk operation."""

    student_id: uuid.UUID
    student_number: str | None = None
    ok: bool
    error: str | None = None


class StudentBulkResponse(BaseModel):
    """Outcome of a bulk operation, reported per student."""

    requested: int
    succeeded: int
    failed: int
    results: list[BulkResultItem]


# --- Bulk intake (CSV) ------------------------------------------------------


class StudentImportRow(BaseModel):
    """One spreadsheet row's outcome.

    ``status`` is a machine-readable token (VALID / CREATED / SKIPPED / ERROR)
    rather than a sentence, so the UI localizes it like every other status.
    ``code`` is the reason a row was skipped or rejected; it is one of the
    codes in ``errors.codes.*`` so the message is translated client-side.

    A created row's account has no password: it is provisioned for activation
    and cannot sign in until the student completes their single-use link.
    ``account_status`` says that in one token; no credential is ever present in
    an import report.
    """

    row_number: int
    student_number: str | None = None
    name: str | None = None
    status: str
    code: str | None = None
    message: str | None = None
    account_status: str | None = None


class StudentImportReport(BaseModel):
    """Result of validating or applying an intake file."""

    dry_run: bool
    #: True when invalid rows caused every write to be refused.
    aborted: bool = False
    total: int
    valid: int
    created: int
    skipped: int
    failed: int
    #: Account outcomes for the file: created, matched, activation_required,
    #: missing_contact, ambiguous, requires_admin.
    accounts: dict[str, int] = Field(default_factory=dict)
    rows: list[StudentImportRow]
