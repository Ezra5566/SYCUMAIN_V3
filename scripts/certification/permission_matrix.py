#!/usr/bin/env python3
"""Live role/permission matrix against a running portal.

Automated unit tests prove the policy in isolation; this proves what the running
stack actually answers for each of the four institutional roles, using real
sessions and the same endpoints the browser calls.

It is read-only except for two deliberately refused writes (a teacher creating a
student and a teacher changing roles), which must be rejected before any row is
touched. Results are written as JSON for the certification report.

Usage:
    python3 scripts/certification/permission_matrix.py [--api-url URL]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROLES = {
    "ADMIN": "admin@school.portal",
    "MANAGEMENT": "management@school.portal",
    "TEACHER": "teacher@school.portal",
    "STUDENT": "student@school.portal",
}

READ_PROBES = [
    ("own identity", "GET", "/api/v1/auth/me", None),
    ("student directory", "GET", "/api/v1/students/", None),
    ("account list", "GET", "/api/v1/users/", None),
    ("operations report", "GET", "/api/v1/reports/overview", None),
    ("audit trail", "GET", "/api/v1/audit/?page=1&page_size=1", None),
    ("housing estate", "GET", "/api/v1/housing/overview", None),
    ("academic periods", "GET", "/api/v1/academics/periods", None),
]

WRITE_PROBES = [
    (
        "create student",
        "POST",
        "/api/v1/students/",
        # A syntactically valid body, so the answer proves the *authorization*
        # decision rather than a validation failure. The referenced user does
        # not exist; a permitted caller fails on that, a forbidden one must
        # never get that far.
        {
            "user_id": "00000000-0000-0000-0000-000000000000",
            "student_id": "PROBE-DENY-0001",
            "first_name": "Probe",
            "last_name": "Denied",
        },
    ),
    ("change roles", "PATCH", "/api/v1/users/00000000-0000-0000-0000-000000000000/roles", {"roles": ["ADMIN"], "reason": "probe"}),
]


class Session:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def call(self, method: str, path: str, payload: dict | None = None) -> int:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=30) as response:
                response.read()
                return response.status
        except urllib.error.HTTPError as error:
            error.read()
            return error.code

    def login(self, email: str, password: str) -> int:
        return self.call(
            "POST", "/api/v1/auth/login", {"email": email, "password": password}
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://localhost:8001")
    parser.add_argument("--password", default="password123")
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[2] / ".perf" / "permission-matrix.json"),
    )
    args = parser.parse_args()

    results: dict[str, dict[str, int | str]] = {}
    for role, email in ROLES.items():
        session = Session(args.api_url)
        status = session.login(email, args.password)
        row: dict[str, int | str] = {"login": status}
        if status == 200:
            for label, method, path, payload in READ_PROBES:
                row[label] = session.call(method, path, payload)
            for label, method, path, payload in WRITE_PROBES:
                row[label] = session.call(method, path, payload)
        results[role] = row
        print(f"{role:11} {row}")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n")
    print(f"\nwritten to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
