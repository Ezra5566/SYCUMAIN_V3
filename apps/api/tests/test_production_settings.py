"""Production configuration validation.

The startup check in ``Settings`` exists to make an insecure deployment fail
loudly and immediately rather than quietly, months later, in a database
disclosure. Two properties are tested here:

* every documented development default is refused in production;
* the failure message names the variable and never repeats its value — the
  message goes to container logs and operator terminals.

Settings objects are constructed directly with explicit values instead of
relying on the ambient environment, so the test proves the validator and not
whatever happens to be in ``.env`` on the machine running it.
"""

import pytest
from pydantic import ValidationError

from app.config.settings import Settings

SECRET = "b7c1f0d9a2e84f6b9c3d5e7a1f2b4c6d8e0f1a3b5c7d9e2f"

SAFE_PRODUCTION = {
    "ENVIRONMENT": "production",
    "DEBUG": False,
    "SEED_DEMO_DATA": False,
    "PASSWORD_RESET_DELIVERY": "disabled",
    "DATABASE_URL": "postgresql://portal_service:not-the-default@db:5432/portal",
    "SECRET_KEY": SECRET,
    "CORS_ORIGINS": ["https://portal.example.edu"],
    "STORAGE_BACKEND": "local",
    "STORAGE_LOCAL_ROOT": "/app/var/storage",
    "MALWARE_SCANNER": "clamav",
}


def build_settings(**overrides) -> Settings:
    values = {**SAFE_PRODUCTION, **overrides}
    return Settings(**values)


def test_safe_production_configuration_is_accepted():
    settings = build_settings()

    assert settings.is_production is True
    assert settings.should_seed_demo_data is False
    assert settings.session_cookie_secure is True


def test_development_configuration_is_not_policed():
    """The check must not make local development impossible."""
    settings = Settings(
        ENVIRONMENT="development",
        DEBUG=True,
        SECRET_KEY="change-me-in-production",
        STORAGE_LOCAL_ROOT="var/storage",
        CORS_ORIGINS=["http://localhost:3000"],
    )

    assert settings.is_production is False
    assert settings.session_cookie_secure is False


@pytest.mark.parametrize(
    ("overrides", "expected_fragment"),
    [
        (
            {"SECRET_KEY": "change-me-in-production"},
            "SECRET_KEY must be a unique value",
        ),
        ({"SECRET_KEY": "a-very-secret-but-short-value"}, "at least 32 characters"),
        ({"DEBUG": True}, "DEBUG must be false in production"),
        ({"SEED_DEMO_DATA": True}, "SEED_DEMO_DATA must be false in production"),
        (
            {"PASSWORD_RESET_DELIVERY": "dev"},
            "PASSWORD_RESET_DELIVERY must not be 'dev'",
        ),
        (
            {"DATABASE_URL": "postgresql://portal:portal@db:5432/portal"},
            "DATABASE_URL must not use the documented portal:portal credentials",
        ),
        ({"CORS_ORIGINS": ["http://portal.example.edu"]}, "only https:// origins"),
        ({"CORS_ORIGINS": []}, "CORS_ORIGINS must list the deployed web origin"),
        (
            {"STORAGE_LOCAL_ROOT": "var/storage"},
            "STORAGE_LOCAL_ROOT must be set to an explicit persistent path",
        ),
        (
            {"STORAGE_BACKEND": "s3", "STORAGE_S3_BUCKET": ""},
            "STORAGE_S3_BUCKET is required",
        ),
        ({"STORAGE_BACKEND": "filesystem"}, "'local' or 's3'"),
        (
            {"MALWARE_SCANNER": "eicar-test"},
            "MALWARE_SCANNER=eicar-test is forbidden in production",
        ),
        ({"SESSION_COOKIE_SECURE": False}, "SESSION_COOKIE_SECURE must not be false"),
    ],
)
def test_insecure_production_configuration_is_rejected(overrides, expected_fragment):
    with pytest.raises(ValidationError) as excinfo:
        build_settings(**overrides)

    assert expected_fragment in str(excinfo.value)


def test_failure_message_never_repeats_a_secret_value():
    """A startup failure must not print the credential it rejected.

    Pydantic includes the whole input mapping in a ValidationError by default,
    which would print the secret key, the database password and every other
    value on startup. ``hide_input_in_errors`` is what makes the message safe
    for a container log, and this test is what keeps it that way.
    """
    weak = "change-me-in-production"

    with pytest.raises(ValidationError) as excinfo:
        build_settings(
            SECRET_KEY=weak,
            CORS_ORIGINS=["http://insecure.example.edu"],
            DATABASE_URL="postgresql://portal_service:s3cr3t-value@db:5432/portal",
        )

    message = str(excinfo.value)
    assert "SECRET_KEY" in message
    assert "CORS_ORIGINS" in message
    assert weak not in message
    assert "insecure.example.edu" not in message
    assert "s3cr3t-value" not in message


def test_every_problem_is_reported_together():
    """One restart should reveal every issue, not one per attempt."""
    with pytest.raises(ValidationError) as excinfo:
        build_settings(
            SECRET_KEY="change-me-in-production",
            DEBUG=True,
            SEED_DEMO_DATA=True,
            PASSWORD_RESET_DELIVERY="dev",
        )

    message = str(excinfo.value)
    for name in (
        "SECRET_KEY",
        "DEBUG",
        "SEED_DEMO_DATA",
        "PASSWORD_RESET_DELIVERY",
    ):
        assert name in message
