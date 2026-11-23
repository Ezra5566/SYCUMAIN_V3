"""Reporting API.

Reports are read-only aggregations over authoritative tables. Access is
gated by the `reports.view` permission; students never receive operational
reporting data.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from sqlalchemy.orm import Session as DBSession

from app.auth.dependencies import CurrentUser
from app.database.session import get_db
from app.permissions.checks import has_permission
from app.schemas.reports import (
    AcademicReport,
    HousingReport,
    ImmigrationReport,
    OperationsReport,
    StudentReport,
)
from app.services.reports import (
    academic_report,
    housing_report,
    immigration_report,
    operations_report,
    student_report,
)

router = APIRouter(prefix="/reports", tags=["reports"])


def _require(user) -> None:
    if not has_permission(user, "reports.view"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "You do not have permission to view reports.",
                }
            },
        )


@router.get("/overview", response_model=OperationsReport)
def report_overview(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Cross-module operational snapshot."""
    _require(current_user)
    return operations_report(db)


@router.get("/students", response_model=StudentReport)
def report_students(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Student population report."""
    _require(current_user)
    return student_report(db)


@router.get("/immigration", response_model=ImmigrationReport)
def report_immigration(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Immigration compliance report (expiry buckets)."""
    _require(current_user)
    return immigration_report(db)


@router.get("/housing", response_model=HousingReport)
def report_housing(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Dormitory capacity and occupancy report."""
    _require(current_user)
    return housing_report(db)


@router.get("/academics", response_model=AcademicReport)
def report_academics(
    current_user: CurrentUser,
    db: Annotated[DBSession, Depends(get_db)],
):
    """Academic structure and enrollment report."""
    _require(current_user)
    return academic_report(db)
