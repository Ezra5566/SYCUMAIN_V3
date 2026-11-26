"""FastAPI application entry point."""

import logging
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth import auth_router
from app.config.settings import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.origin import OriginGuardMiddleware
from app.database.session import SessionLocal
from app.routers import (
    absence,
    academic,
    admission_changes,
    admission_verification,
    announcements,
    audit,
    calendar,
    commencement,
    documents,
    dormitory_attendance,
    examination,
    health,
    housing,
    immigration,
    notifications,
    placements,
    reports,
    student_import,
    students,
    support,
    users,
)
from app.seed import seed_roles_and_permissions, seed_test_users
from app.seed_academic import seed_academic
from app.seed_demo_full import ensure_program_offering_links, seed_demo_dataset
from app.seed_housing import seed_housing
from app.seed_immigration import seed_immigration
from app.seed_platform import seed_platform

settings = get_settings()
# Configured before the app object exists so import-time failures and the
# startup banner both go through the same formatter.
configure_logging()
logger = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle.

    Roles and permissions are reconciled on every start: they are part of the
    application's contract, and a deployment whose permission table is out of
    date denies legitimate requests. The demonstration dataset is different —
    it must never be created in production, where it would install the
    documented `password123` accounts. `SEED_DEMO_DATA` controls it and
    defaults to "on everywhere except production".
    """
    settings = get_settings()
    app.state.started_at = time.monotonic()

    db = SessionLocal()
    try:
        seed_roles_and_permissions(db)

        # The base catalogue and test accounts are part of the inherited test
        # contract, so the suite gets them too. The larger demonstration cohort
        # is local-development material only: seeding it under assertions that
        # count academic rows makes the suite order-dependent.
        if settings.should_seed_demo_data or settings.ENVIRONMENT == "testing":
            # Demonstration seeding uses the configured demo password, which the
            # login page's development chips also read. The test suite supplies
            # its own fixture credential (tests/conftest.py), so a change made
            # for a presentation cannot silently rewrite what the suite signs
            # in with.
            if settings.should_seed_demo_data:
                seed_test_users(db, password=settings.DEMO_PASSWORD)
            else:
                seed_test_users(db)
            seed_housing(db)
            seed_immigration(db)
            seed_academic(db)
            seed_platform(db)
            if settings.should_seed_demo_data:
                # The reference seed left the operational screens empty. This
                # adds the demonstration cohort on top of it, in one idempotent
                # transaction, so every module can be exercised locally.
                seed_demo_dataset(db)
                # Repairs an older clone whose sections predate the offering
                # links.
                ensure_program_offering_links(db)
                logger.info(
                    "startup_demo_data_seeded",
                    extra={"environment": settings.ENVIRONMENT},
                )
            else:
                logger.info(
                    "startup_base_data_seeded",
                    extra={"environment": settings.ENVIRONMENT},
                )
        else:
            logger.info(
                "startup_demo_data_skipped",
                extra={"environment": settings.ENVIRONMENT},
            )

        # Expiry reminders are reconciled on every start. The job is idempotent
        # — an alert is unique on (profile, document, tier, expiry) — so running
        # it here means an installation with no external scheduler still issues
        # its warnings, and running it twice issues none twice. A failure is
        # logged and swallowed: a reminder problem must not stop the API from
        # serving requests, and the manual endpoint remains available.
        try:
            from app.services.immigration_reminders import (  # noqa: PLC0415
                run_expiry_reminders,
            )

            reminder_result = run_expiry_reminders(db)
            # LogRecord already owns `created`, so the counts are named for
            # what they are: overwriting a reserved attribute raises.
            logger.info(
                "immigration_reminders_reconciled",
                extra={
                    "profiles_evaluated": reminder_result["evaluated"],
                    "alerts_created": reminder_result["created"],
                    "alerts_resolved": reminder_result["resolved"],
                },
            )
        except Exception:
            db.rollback()
            logger.exception("immigration_reminders_failed")
    except Exception:
        # A failed bootstrap is fatal on purpose: starting anyway would leave
        # every permission check unable to succeed, which looks like an
        # authorization bug rather than a seeding failure.
        logger.exception("startup_seed_failed")
        raise
    finally:
        db.close()

    yield
    # Shutdown: nothing to clean up yet


# The interactive documentation and the OpenAPI document expose every route,
# parameter and schema — a map of the attack surface. They stay available while
# the API is being developed, and are switched off in production rather than
# left for a deployment checklist to remember.
_docs_enabled = not settings.is_production

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="International Student School Portal API",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Cross-site request protection for unsafe methods. Sits inside the request
# context (so a rejection is still logged and correlated) and wraps CORS, so a
# hostile write is refused before routing, authentication or any database work.
app.add_middleware(
    OriginGuardMiddleware,
    trusted_origins=settings.trusted_origins,
)

# Added last so it wraps every other middleware: a request rejected by CORS or
# by the origin guard is still logged, and still carries an X-Request-ID for the
# caller to report.
app.add_middleware(RequestContextMiddleware)


# Global exception handler for consistent error responses
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with consistent error format."""
    # If detail is already a dict with error structure, use it directly
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        content = exc.detail
    else:
        content = {
            "error": {
                "code": "HTTP_ERROR",
                "message": str(exc.detail),
            }
        }
    if exc.status_code >= 500:
        logger.error(
            "http_error",
            extra={"status_code": exc.status_code, "path": request.url.path},
        )
    # Headers carry protocol-level information the client needs: `Retry-After`
    # on a 429, `WWW-Authenticate` on a 401. Dropping them here would make a
    # rate limit look like a permanent failure.
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions.

    The response deliberately carries no internal detail, so this log line is
    the *only* record of the real cause. It is written with the traceback and
    the request id, which is what turns a user's "it failed at 10:41" into a
    specific failing statement.

    A ``500`` handler is installed on Starlette's ``ServerErrorMiddleware``,
    which wraps every application middleware — including ``CORSMiddleware``.
    Without the headers below, a server error would reach the browser as an
    opaque CORS/network failure, so the UI would report "check your connection"
    for a request the server actually answered. They are attached explicitly so
    the caller sees the real status and the error envelope.
    """
    logger.exception(
        "unhandled_exception",
        extra={"method": request.method, "path": request.url.path},
    )
    response = JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred.",
            }
        },
    )
    origin = request.headers.get("origin")
    if origin and origin in settings.CORS_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


# Include routers under /api/v1
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
# Intake/export is registered before the CRUD router so its fixed paths
# (`/students/import`, `/students/export`) are not captured by
# `/students/{student_id}`.
app.include_router(student_import.router, prefix=settings.API_V1_PREFIX)
app.include_router(students.router, prefix=settings.API_V1_PREFIX)
app.include_router(admission_changes.router, prefix=settings.API_V1_PREFIX)
app.include_router(placements.router, prefix=settings.API_V1_PREFIX)
app.include_router(admission_verification.router, prefix=settings.API_V1_PREFIX)
app.include_router(housing.router, prefix=settings.API_V1_PREFIX)
app.include_router(immigration.router, prefix=settings.API_V1_PREFIX)
app.include_router(academic.router, prefix=settings.API_V1_PREFIX)
app.include_router(calendar.router, prefix=settings.API_V1_PREFIX)
app.include_router(commencement.router, prefix=settings.API_V1_PREFIX)
app.include_router(absence.router, prefix=settings.API_V1_PREFIX)
app.include_router(dormitory_attendance.router, prefix=settings.API_V1_PREFIX)
app.include_router(examination.router, prefix=settings.API_V1_PREFIX)
app.include_router(announcements.router, prefix=settings.API_V1_PREFIX)
app.include_router(support.router, prefix=settings.API_V1_PREFIX)
app.include_router(notifications.router, prefix=settings.API_V1_PREFIX)
app.include_router(documents.router, prefix=settings.API_V1_PREFIX)
app.include_router(reports.router, prefix=settings.API_V1_PREFIX)
app.include_router(audit.router, prefix=settings.API_V1_PREFIX)

# Also mount health at root for load balancers
app.include_router(health.router)


@app.get("/")
async def root():
    """Root endpoint."""
    payload = {"name": settings.APP_NAME, "version": settings.APP_VERSION}
    if _docs_enabled:
        payload["docs"] = "/docs"
    return payload
