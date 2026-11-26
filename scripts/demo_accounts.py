#!/usr/bin/env python3
"""Prepare the four synthetic presentation accounts.

The presentation must not rely on the shared demonstration password for its
administrator either: this script issues a fresh, strong password to each of the
four seeded accounts through the *admin-assisted password reset* endpoint — the
same supported path the international office uses at the counter — and records
the result in a file that is ignored by git and readable only by its owner.

It uses the running API, so it also proves that:

* the ADMIN account can authenticate and manage accounts;
* each reset takes effect immediately;
* each account can sign in with its new password and is not left behind the
  forced password-change screen.

No real person's data is involved: the accounts and the cohort are synthetic
seed data.

Usage:
    python3 scripts/demo_accounts.py            # rotate and verify
    python3 scripts/demo_accounts.py --show     # print the stored passwords

The administrator password used to sign in for the rotation is taken from
``DEMO_ADMIN_PASSWORD``, then from the credentials this script recorded last
time, then from ``DEMO_PASSWORD`` (the value the API seeds). It never falls back
to the published catalogue default: the demonstration accounts are rotated away
from it, so that default no longer authenticates anything.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import string
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

# ADMIN is deliberately last: resetting the password of the account making the
# requests revokes its sessions (correctly), so every other account must be
# prepared first.
ROLES = [
    ("MANAGEMENT", "management@school.portal", "Management (read + approvals)"),
    ("TEACHER", "teacher@school.portal", "Teacher (scoped to own classes)"),
    ("STUDENT", "student@school.portal", "Student (self-service, STU-001)"),
    ("ADMIN", "admin@school.portal", "Institutional administrator"),
]

ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_=+"

# Must match the API's `Settings.DEMO_PASSWORD` default. This is the value a
# fresh development seed creates; it is not a secret and must never be reused by
# an institution.
DEFAULT_DEMO_PASSWORD = "Sycumain2026!"


def strong_password(length: int = 18) -> str:
    """Generate a password that satisfies the documented policy."""
    while True:
        candidate = "".join(secrets.choice(ALPHABET) for _ in range(length))
        classes = sum(
            (
                any(c.islower() for c in candidate),
                any(c.isupper() for c in candidate),
                any(c.isdigit() for c in candidate),
                any(not c.isalnum() for c in candidate),
            )
        )
        if classes == 4:
            return candidate


def stored_admin_password(path: Path) -> str | None:
    """The administrator password this script last verified, if it recorded one."""
    try:
        accounts = json.loads(path.read_text())["accounts"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    for account in accounts:
        if account.get("role") == "ADMIN" and account.get("password"):
            return account["password"]
    return None


def default_admin_password(output: Path) -> tuple[str, str]:
    """Password to sign in as the administrator, and where it came from.

    Order: an explicit environment variable, then the credentials this script
    recorded on its last rotation, then the configured demonstration password.
    The catalogue default ``password123`` used to be the last fallback, but the
    demonstration accounts are rotated away from it, so re-running the
    documented command without a flag authenticated nothing at all.
    """
    explicit = os.environ.get("DEMO_ADMIN_PASSWORD")
    if explicit:
        return explicit, "DEMO_ADMIN_PASSWORD"

    recorded = stored_admin_password(output)
    if recorded:
        return recorded, str(output)

    return os.environ.get("DEMO_PASSWORD", DEFAULT_DEMO_PASSWORD), "DEMO_PASSWORD"


class Api:
    """Minimal cookie-aware client (stdlib only, no project dependency)."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def call(
        self, method: str, path: str, payload: dict | None = None
    ) -> tuple[int, dict]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                body = response.read().decode()
                return response.status, (json.loads(body) if body else {})
        except urllib.error.HTTPError as error:
            body = error.read().decode()
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body[:200]}
            return error.code, parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.environ.get("DEMO_API_URL", "http://localhost:8001"))
    parser.add_argument(
        "--admin-email", default=os.environ.get("DEMO_ADMIN_EMAIL", "admin@school.portal")
    )
    parser.add_argument(
        "--admin-password",
        default=None,
        help=(
            "password for --admin-email. Defaults to DEMO_ADMIN_PASSWORD, then to "
            "the credentials recorded by the last run, then to DEMO_PASSWORD."
        ),
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parent.parent / ".demo-credentials.json"),
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("DEMO_PASSWORD"),
        help=(
            "Use one fixed password for every demo account instead of random ones. "
            "Defaults to DEMO_PASSWORD when that is set."
        ),
    )
    parser.add_argument("--show", action="store_true", help="print stored passwords")
    args = parser.parse_args()

    output = Path(args.output)

    if args.show:
        if not output.exists():
            print(f"No credentials at {output}; run without --show first.", file=sys.stderr)
            return 1
        for account in json.loads(output.read_text())["accounts"]:
            print(f"{account['role']:11} {account['email']:28} {account['password']}")
        return 0

    if args.admin_password:
        admin_password, source = args.admin_password, "--admin-password"
    else:
        admin_password, source = default_admin_password(output)

    api = Api(args.api_url)
    print(f"Signing in as {args.admin_email} (password from {source})")

    status, body = api.call(
        "POST", "/api/v1/auth/login",
        {"email": args.admin_email, "password": admin_password},
    )
    if status != 200:
        print(f"Cannot sign in as {args.admin_email}: HTTP {status} {body}", file=sys.stderr)
        return 1

    accounts = []
    for role, email, description in ROLES:
        status, listing = api.call("GET", f"/api/v1/users/?search={email}")
        if status != 200:
            print(f"Cannot list accounts: HTTP {status} {listing}", file=sys.stderr)
            return 1

        match = next(
            (item for item in listing.get("items", []) if item["email"] == email), None
        )
        if match is None:
            print(f"Account {email} is missing from this database.", file=sys.stderr)
            return 1

        password = args.password or strong_password()
        status, result = api.call(
            "POST",
            f"/api/v1/users/{match['id']}/reset-password",
            {"new_password": password, "must_change_password": False},
        )
        if status != 200:
            print(f"Reset failed for {email}: HTTP {status} {result}", file=sys.stderr)
            return 1

        # Verify the account can actually sign in with the new password and is
        # not trapped behind the forced-change screen.
        probe = Api(args.api_url)
        status, me = probe.call(
            "POST", "/api/v1/auth/login", {"email": email, "password": password}
        )
        if status != 200:
            print(f"New password does not work for {email}: HTTP {status} {me}", file=sys.stderr)
            return 1
        status, identity = probe.call("GET", "/api/v1/auth/me")
        if status != 200 or identity.get("must_change_password"):
            print(f"{email} signed in but is not usable (HTTP {status}).", file=sys.stderr)
            return 1

        accounts.append(
            {
                "role": role,
                "email": email,
                "password": password,
                "description": description,
                "sessions_revoked": result.get("sessions_revoked"),
            }
        )
        print(f"verified  {role:11} {email}")

    # 0600: the file holds working credentials for a local, synthetic stack.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"accounts": accounts}, indent=2) + "\n")
    os.chmod(output, stat.S_IRUSR | stat.S_IWUSR)

    print(f"\nCredentials written to {output} (mode 0600, git-ignored).")
    print("Read them with: python3 scripts/demo_accounts.py --show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
