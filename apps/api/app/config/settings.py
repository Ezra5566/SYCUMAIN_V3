"""Typed configuration system with environment separation."""

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        # Without this, pydantic appends the whole input mapping to a
        # ValidationError — so a startup failure would print SECRET_KEY,
        # POSTGRES_PASSWORD and every other value to the container log. The
        # validator names the offending variables instead.
        hide_input_in_errors=True,
    )

    # Application
    APP_NAME: str = "School Portal API"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3100"]

    # Database
    DATABASE_URL: str = "postgresql://portal:portal@localhost:5433/school_portal"

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Pin the PostgreSQL driver to psycopg (v3).

        The project declares `psycopg[binary]` (v3) as its only PostgreSQL
        driver, but SQLAlchemy maps a bare `postgresql://` URL to psycopg2.
        Development machines often have psycopg2 installed incidentally, so
        the mismatch only surfaces in slim production/CI images where it
        crashes with `ModuleNotFoundError: No module named 'psycopg2'`.

        Normalizing the scheme here keeps every environment identical and
        means operators never have to remember the `+psycopg` suffix.
        """
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    # API
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str = "change-me-in-production"

    # Session configuration
    SESSION_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    SESSION_COOKIE_NAME: str = "session_token"
    # `None` means "secure exactly when running in production". Explicitly
    # setting it to false in production is refused by the validator below.
    SESSION_COOKIE_SECURE: bool | None = None

    # Document storage. "local" is the development default; production should
    # set "s3" and provide S3-compatible credentials.
    STORAGE_BACKEND: str = "local"
    STORAGE_LOCAL_ROOT: str = "var/storage"
    STORAGE_S3_BUCKET: str = ""
    STORAGE_S3_REGION: str | None = None
    STORAGE_S3_ENDPOINT_URL: str | None = None
    STORAGE_S3_ACCESS_KEY_ID: str | None = None
    STORAGE_S3_SECRET_ACCESS_KEY: str | None = None
    # Presigned download URLs expire quickly; they are never persisted.
    STORAGE_PRESIGN_EXPIRE_SECONDS: int = 300

    # Upload limits
    MAX_UPLOAD_SIZE_MB: int = 10

    # Malware scanning. "disabled" fails closed: uploads are refused rather
    # than stored unscanned. "clamav" uses the ClamAV INSTREAM protocol over
    # TCP (no Python package or public URL required). "eicar-test" is a test
    # double and is refused outside ENVIRONMENT=testing. "dev-clean" is a
    # local-clone convenience that performs no inspection, is refused outside
    # ENVIRONMENT=development and is rejected by the production validator.
    MALWARE_SCANNER: str = "disabled"
    CLAMAV_HOST: str = "clamav"
    CLAMAV_PORT: int = 3310
    CLAMAV_TIMEOUT_SECONDS: float = 10.0

    # --- Operations --------------------------------------------------------
    # Logging is configured once at process start (see app/core/logging.py).
    # "auto" emits JSON everywhere except a local development run, where a
    # readable line is more useful than a parseable one.
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "auto"
    # Requests slower than this are logged at WARNING with slow=true. This is
    # the cheapest early warning that a query or the database is degrading.
    SLOW_REQUEST_MS: int = 1500
    # SQL statement logging includes bound parameters (names, student numbers,
    # dates), so it is off unless explicitly enabled. It is deliberately not
    # tied to DEBUG.
    SQL_ECHO: bool = False

    # Whether the demo dataset (test accounts, sample buildings, the academic
    # catalogue and announcements) is created on startup. Unset means "yes in
    # every environment except production", so a production database can never
    # be seeded with the documented `password123` demo accounts.
    SEED_DEMO_DATA: bool | None = None

    # --- Admission writes --------------------------------------------------
    # Phase 1 admission episode creation and transitions. Off by default so a
    # rollback is a flag change: onboarding falls back to the legacy placement
    # write, admission read endpoints stay available, and episodes already
    # written remain inert history. Never delete them.
    ADMISSIONS_WRITE_ENABLED: bool = False
    # Phase 2 migration verification console. Off by default; turning it off
    # only hides the workflow — existing acts, trust states and pointers stay.
    ADMISSION_MIGRATION_CONSOLE_ENABLED: bool = False
    # Phase 4 controlled change requests. Off by default: read-only history
    # stays available, while request creation and review are gated. Approved
    # changes remain authoritative history when the flag is turned off again.
    ADMISSION_CHANGE_REQUESTS_ENABLED: bool = False
    # Phase 5 controlled intake-date correction. Off by default; the correction
    # endpoint and its dialog disappear, while recorded corrections remain
    # readable history. Reversal is another correction, never SQL.
    ADMISSION_DATE_CORRECTION_ENABLED: bool = False
    # Phase 7 administrative corrections. Off by default so both correction
    # surfaces can be withdrawn without losing the history they have written.
    # Re-enabling allows a wrong correction to be corrected again; rows are
    # never deleted.
    ADMISSION_CORRECTIONS_ENABLED: bool = False
    # Phase 6 immigration cohort source. POINTER is the accepted basis:
    # students.original_admission_id -> academic_admissions.admission_intake_id.
    # LEGACY is the instant rollback to the pre-Phase-6 overview. This controls
    # reads only; no data is changed in either direction.
    ADMISSION_COHORT_SOURCE: str = "POINTER"

    @field_validator("ADMISSION_COHORT_SOURCE")
    @classmethod
    def _valid_cohort_source(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in {"LEGACY", "POINTER"}:
            raise ValueError("ADMISSION_COHORT_SOURCE must be LEGACY or POINTER")
        return normalized

    # --- Authentication rate limiting --------------------------------------
    # Counters live in PostgreSQL (see app/core/ratelimit.py), so the limits
    # hold across API workers and restarts without adding Redis.
    RATE_LIMIT_ENABLED: bool = True
    # Failed sign-ins per address per window. Generous enough for a shared
    # campus NAT, small enough to make online guessing pointless.
    RATE_LIMIT_LOGIN_PER_IP: int = 20
    # Failed sign-ins per (address, account) pair. Keyed together so an
    # attacker cannot lock a known student out from a different address.
    RATE_LIMIT_LOGIN_PER_ACCOUNT: int = 5
    RATE_LIMIT_LOGIN_WINDOW_SECONDS: int = 900
    RATE_LIMIT_RESET_REQUEST_PER_IP: int = 5
    RATE_LIMIT_RESET_REQUEST_PER_EMAIL: int = 3
    RATE_LIMIT_RESET_SUBMIT_PER_IP: int = 10
    RATE_LIMIT_RESET_WINDOW_SECONDS: int = 3600

    # First administrator for a production deployment. `python -m app.cli
    # bootstrap-admin` reads this when --email is not given.
    BOOTSTRAP_ADMIN_EMAIL: str = ""

    # --- Data retention ----------------------------------------------------
    # Left unset on purpose: an institution must approve these values, and this
    # project does not invent statutory periods. `python -m app.cli
    # retention-report` treats `None` as "policy pending approval".
    RETENTION_GRADUATED_YEARS: int | None = None
    RETENTION_WITHDRAWN_YEARS: int | None = None
    RETENTION_INACTIVE_YEARS: int | None = None
    RETENTION_DOCUMENT_YEARS: int | None = None
    RETENTION_AUDIT_YEARS: int | None = None

    # Bulk student intake. Bounded so a mistake in a spreadsheet cannot turn
    # into an unbounded transaction.
    MAX_IMPORT_ROWS: int = 500
    MAX_IMPORT_SIZE_MB: int = 5
    MAX_EXPORT_ROWS: int = 10000

    # Immigration expiration warning windows (days).
    IMMIGRATION_WARNING_DAYS_URGENT: int = 30
    IMMIGRATION_WARNING_DAYS_WARNING: int = 90

    # Document categories the institution expects an international student to
    # provide. Configuration rather than schema: a school that does not issue
    # residence permits changes one environment variable. Missing categories
    # are reported by the student document summary as MISSING.
    REQUIRED_DOCUMENT_TYPES: str = "PASSPORT,VISA,RESIDENCE_PERMIT,STUDENT_ID"

    # --- Password recovery -------------------------------------------------
    # How a reset link reaches the user. Only "email" is production-appropriate.
    # "disabled" (the default) means no delivery channel is configured, and the
    # API reports that so the UI hides the flow rather than offering a button
    # that cannot work.
    #
    # "dev" is a development-only channel: the token is returned in the reset
    # request response so the flow can be exercised end to end without an
    # email provider. It must never be enabled in production, because the
    # token would be readable by anyone who can see the HTTP response.
    PASSWORD_RESET_DELIVERY: str = "disabled"
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30

    # --- Account activation ------------------------------------------------
    # A migrated account has no password until the student completes a
    # single-use activation link. Seven days covers a registration week without
    # leaving a working link in an inbox for a month.
    ACTIVATION_EXPIRE_HOURS: int = 168
    # Where the activation link points. The console origin, not the API.
    ACTIVATION_LINK_BASE: str = "http://localhost:3101"
    # Development only: return the link to the issuing administrator so the
    # flow can be exercised without a mail provider. In production the token
    # must travel through a configured delivery channel, never an HTTP
    # response that a third party could read.
    ACTIVATION_RETURN_LINK: bool = True

    # Localization
    SUPPORTED_LOCALES: list[str] = ["en", "zh", "fr", "ar", "ru"]
    DEFAULT_LOCALE: str = "en"

    @property
    def session_cookie_secure(self) -> bool:
        """Whether the session cookie must only travel over HTTPS."""
        if self.SESSION_COOKIE_SECURE is None:
            return self.is_production
        return self.SESSION_COOKIE_SECURE

    @model_validator(mode="after")
    def _validate_production_configuration(self) -> "Settings":
        """Refuse to start with a development configuration in production.

        This is a startup check, not a warning: a production portal that
        accepts a published `SECRET_KEY`, the documented `portal:portal`
        database credentials, the `dev` reset channel or demo seeding is not
        "running with defaults", it is running insecurely — and the failure
        would only be discovered by whoever reads the database.

        Problems are reported by variable name only. The message is written to
        the container log and to an operator's terminal, and echoing the
        offending value would turn a startup failure into a credential leak.
        """
        if not self.is_production:
            return self

        problems: list[str] = []

        weak_secrets = {
            "",
            "change-me",
            "changeme",
            "change-me-in-production",
            "secret",
        }
        if (
            self.SECRET_KEY.strip().lower() in weak_secrets
            or len(self.SECRET_KEY) < 32
        ):
            problems.append(
                "SECRET_KEY must be a unique value of at least 32 characters"
            )

        if self.DEBUG:
            problems.append("DEBUG must be false in production")

        if self.SEED_DEMO_DATA:
            problems.append("SEED_DEMO_DATA must be false in production")

        if self.PASSWORD_RESET_DELIVERY.strip().lower() == "dev":
            problems.append("PASSWORD_RESET_DELIVERY must not be 'dev' in production")

        if self.ACTIVATION_RETURN_LINK:
            problems.append(
                "ACTIVATION_RETURN_LINK must be false in production; activation "
                "tokens must be delivered out of band, not returned over HTTP"
            )
        if not self.ACTIVATION_LINK_BASE.startswith("https://"):
            problems.append("ACTIVATION_LINK_BASE must be an https:// origin in production")

        scanner = self.MALWARE_SCANNER.strip().lower()
        if scanner in {"eicar-test", "dev-clean"}:
            problems.append(
                f"MALWARE_SCANNER={scanner} is forbidden in production; "
                "use clamav"
            )

        if "portal:portal" in self.DATABASE_URL or ":portal@" in self.DATABASE_URL:
            problems.append(
                "DATABASE_URL must not use the documented portal:portal credentials"
            )

        if not self.CORS_ORIGINS:
            problems.append("CORS_ORIGINS must list the deployed web origin")
        elif any(not origin.startswith("https://") for origin in self.CORS_ORIGINS):
            problems.append("CORS_ORIGINS must contain only https:// origins")

        backend = self.STORAGE_BACKEND.strip().lower()
        if backend == "local":
            root = self.STORAGE_LOCAL_ROOT.strip()
            if not root or root == "var/storage":
                problems.append(
                    "STORAGE_LOCAL_ROOT must be set to an explicit persistent "
                    "path in production"
                )
        elif backend == "s3":
            if not self.STORAGE_S3_BUCKET.strip():
                problems.append(
                    "STORAGE_S3_BUCKET is required when STORAGE_BACKEND=s3"
                )
        else:
            problems.append("STORAGE_BACKEND must be 'local' or 's3'")

        if self.session_cookie_secure is False:
            problems.append("SESSION_COOKIE_SECURE must not be false in production")

        if problems:
            raise ValueError(
                "Refusing to start with an insecure production configuration: "
                + "; ".join(problems)
            )

        return self

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_testing(self) -> bool:
        return self.ENVIRONMENT == "testing"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def should_seed_demo_data(self) -> bool:
        """Whether startup may create demonstration data.

        Roles and permissions are reconciled unconditionally — they are part of
        the application's contract. Everything else is demo material whose
        presence in a production database would be a security defect.
        """
        # Tests install only the fixtures they declare. Seeding the full
        # demonstration cohort during TestClient startup would add academic
        # rows underneath assertions that expect a clean database.
        if self.ENVIRONMENT == "testing":
            return False
        if self.SEED_DEMO_DATA is not None:
            return self.SEED_DEMO_DATA
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
