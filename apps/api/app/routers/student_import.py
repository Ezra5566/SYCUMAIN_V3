"""Student intake and export endpoints.

Kept in a dedicated router that is included *before* the student CRUD router, so
the fixed paths ``/students/import``, ``/students/export`` and
``/students/import/template`` are matched as written instead of being captured
by ``/students/{student_id}``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi import status as http_status
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import joinedload

from app.audit import record_audit
from app.auth.dependencies import (
    CurrentUser,  # noqa: TC001 - FastAPI resolves this annotation at runtime
)
from app.config.settings import get_settings
from app.database.session import get_db
from app.models.identity import Student
from app.permissions.checks import has_permission
from app.schemas.student import StudentImportReport
from app.services.student_academic import student_academic_snapshot
from app.services.student_import import (
    ImportFileError,
    build_export_csv,
    build_template_csv,
    import_students,
)

logger = logging.getLogger("app.students.import")

router = APIRouter(prefix="/students", tags=["students"])

#: Exporting the whole directory is a data-protection action, not a browsing
#: convenience, so it is limited to the roles that already own those records.
_EXPORT_ROLES = {"ADMIN", "MANAGEMENT"}


def _forbidden(message: str) -> HTTPException:
    return HTTPException(
        status_code=http_status.HTTP_403_FORBIDDEN,
        detail={"error": {"code": "FORBIDDEN", "message": message}},
    )


def _attachment(payload: str, filename: str) -> Response:
    return Response(
        content=payload,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # Personal data: never cached by a proxy or the browser.
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/export")
def export_students_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request: Request,
) -> Response:
    """Export the student directory as CSV.

    The cap (``MAX_EXPORT_ROWS``) is deliberate: an unbounded export of a large
    cohort would be built in memory inside the request that serves every other
    user. A deployment that outgrows it should stream the export instead.
    """
    roles = {role.name for role in current_user.roles}
    if not _EXPORT_ROLES & roles or not has_permission(current_user, "student.view"):
        raise _forbidden("You do not have permission to export student records.")

    settings = get_settings()
    students = (
        db.query(Student)
        .options(joinedload(Student.user))
        .order_by(Student.last_name, Student.first_name)
        .limit(settings.MAX_EXPORT_ROWS)
        .all()
    )

    record_audit(
        db,
        action="student.exported",
        actor=current_user,
        entity_type="student",
        # A count, never the rows themselves: the audit trail must not become a
        # second copy of the data it is describing.
        context={"rows": len(students)},
        request=request,
    )
    db.commit()

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    academics = {
        student.id: student_academic_snapshot(db, student.id) for student in students
    }
    return _attachment(
        build_export_csv(students, academics), f"students-{stamp}.csv"
    )


@router.get("/import/template")
def import_template_endpoint(current_user: CurrentUser) -> Response:
    """Download the header row the importer expects.

    Offering the template removes the most common cause of a rejected file:
    a header the operator had to guess.
    """
    if not has_permission(current_user, "student.create"):
        raise _forbidden("You do not have permission to import students.")
    return _attachment(build_template_csv(), "student-import-template.csv")


@router.post("/import", response_model=StudentImportReport)
async def import_students_endpoint(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Query(
        False,
        description="Validate the file and report without writing anything.",
    ),
    skip_invalid: bool = Query(
        False,
        description=(
            "Import the valid rows even if some rows are invalid. "
            "Default is to refuse the whole file."
        ),
    ),
) -> StudentImportReport:
    """Import students from a CSV file.

    A validation problem is a *result*, not an error: the response describes
    every row so the operator can fix the file. Only an unreadable file is a
    4xx.
    """
    if not has_permission(current_user, "student.create"):
        raise _forbidden("You do not have permission to import students.")

    settings = get_settings()
    max_bytes = settings.MAX_IMPORT_SIZE_MB * 1024 * 1024
    raw = await file.read(max_bytes + 1)

    if len(raw) > max_bytes:
        raise HTTPException(
            status_code=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": {
                    "code": "IMPORT_FILE_TOO_LARGE",
                    "message": (
                        f"The file is larger than the {settings.MAX_IMPORT_SIZE_MB} MB limit."
                    ),
                }
            },
        )

    try:
        report = import_students(
            db,
            actor=current_user,
            raw=raw,
            dry_run=dry_run,
            skip_invalid=skip_invalid,
            request=request,
        )
    except ImportFileError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": {"code": exc.code, "message": exc.message}},
        ) from exc

    # Field names avoid LogRecord's own attributes (`created`, `name`, `module`,
    # ...) — `extra` rejects those, and the resulting KeyError would turn a
    # successful import into a 500.
    logger.info(
        "student_import_completed",
        extra={
            "dry_run": report.dry_run,
            "row_total": report.total,
            "rows_created": report.created,
            "rows_skipped": report.skipped,
            "rows_failed": report.failed,
            "aborted": report.aborted,
        },
    )
    return report


__all__: list[str] = ["router"]
