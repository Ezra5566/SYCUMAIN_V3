"""One demonstration credential, defined once, for development only.

The defect this guards against was silent. The login page's account chips filled
one password while the seeder wrote another, so clicking a chip submitted
rejected credentials, the form reappeared unchanged, and the portal looked
broken immediately before a presentation.

Four things therefore have to agree:

* the API's ``DEMO_PASSWORD`` default, which development seeding uses;
* the login page's fallback for ``NEXT_PUBLIC_DEMO_PASSWORD``;
* the rotation script's starting point when nothing is configured;
* the development compose file, which feeds the first two from one variable.

None of them may be the published ``password123`` catalogue default that the
demonstration accounts are deliberately rotated away from — and the password
must stay a real hash, not a compared string.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

from app.auth.service import hash_password, verify_password
from app.config.settings import Settings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOGIN_PAGE = PROJECT_ROOT / "apps/web/src/app" / "[locale]" / "login/page.tsx"
ROTATION_SCRIPT = PROJECT_ROOT / "scripts/demo_accounts.py"
DEV_COMPOSE = PROJECT_ROOT / "docker-compose.yml"

# The single place a fallback is declared on the client.
FRONTEND_PATTERN = re.compile(
    r'const DEMO_PASSWORD = process\.env\.NEXT_PUBLIC_DEMO_PASSWORD \?\? "([^"]+)";'
)

CATALOGUE_DEFAULT = "password123"


def configured_default() -> str:
    """The API's DEMO_PASSWORD *default*, independent of any local `.env`."""
    default: Any = Settings.model_fields["DEMO_PASSWORD"].default
    assert isinstance(default, str)
    return default


@pytest.fixture(scope="module")
def rotation_script() -> Any:
    spec = importlib.util.spec_from_file_location("demo_accounts_under_test", ROTATION_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_login_page_fills_the_configured_demo_password() -> None:
    """The chip and the seed must not be able to drift apart again."""
    source = LOGIN_PAGE.read_text()
    matches = FRONTEND_PATTERN.findall(source)
    assert len(matches) == 1, "the login page must declare exactly one demo fallback"

    assert matches[0] == configured_default(), (
        "the login page's demo password differs from Settings.DEMO_PASSWORD; a "
        "fresh seed would reject the credentials its own chips fill"
    )


def test_demo_password_is_not_the_published_catalogue_default() -> None:
    password = configured_default()

    assert password != CATALOGUE_DEFAULT
    assert len(password) >= 12
    # One character from each class: the policy applied to a changed password
    # must be satisfied by the seeded one too, or a demo account would be
    # rejected on its first "change password" screen.
    assert any(character.islower() for character in password)
    assert any(character.isupper() for character in password)
    assert any(character.isdigit() for character in password)
    assert any(not character.isalnum() for character in password)


def test_demo_password_is_stored_as_a_hash() -> None:
    password = configured_default()
    digest = hash_password(password)

    assert digest != password
    assert password not in digest
    assert verify_password(password, digest)
    assert not verify_password(CATALOGUE_DEFAULT, digest)
    # The hasher must not have been weakened into a plain comparison.
    assert digest.startswith("$")


def test_rotation_script_starts_from_the_demo_password(
    rotation_script: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    output = tmp_path / ".demo-credentials.json"

    password, source = rotation_script.default_admin_password(output)

    assert password == configured_default()
    assert password != CATALOGUE_DEFAULT
    assert source == "DEMO_PASSWORD"


def test_rotation_script_prefers_the_credentials_it_recorded(
    rotation_script: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("DEMO_PASSWORD", raising=False)
    output = tmp_path / ".demo-credentials.json"
    output.write_text(
        '{"accounts": [{"role": "ADMIN", "email": "admin@school.portal", '
        '"password": "recorded-by-the-last-rotation"}]}'
    )

    password, source = rotation_script.default_admin_password(output)

    assert password == "recorded-by-the-last-rotation"
    assert source == str(output)


def test_rotation_script_honours_an_explicit_override(
    rotation_script: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "supplied-by-the-operator")

    password, source = rotation_script.default_admin_password(tmp_path / "absent.json")

    assert password == "supplied-by-the-operator"
    assert source == "DEMO_ADMIN_PASSWORD"


def test_development_stack_feeds_both_services_from_one_variable() -> None:
    """Compose is the wiring that makes the source of truth single at runtime."""
    compose = DEV_COMPOSE.read_text()

    assert "DEMO_PASSWORD: ${DEMO_PASSWORD:-" in compose
    assert "NEXT_PUBLIC_DEMO_PASSWORD: ${DEMO_PASSWORD:-" in compose
