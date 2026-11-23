"""Baseline browser protections must be on every response.

These are cheap to set once and easy to lose in a refactor, so they are asserted
on a successful response *and* on a rejected one: an error page is still a
response a browser renders.
"""

from __future__ import annotations

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
}


def test_headers_on_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    for header, value in EXPECTED.items():
        assert response.headers.get(header) == value


def test_headers_on_unauthorized_response(client):
    response = client.get("/api/v1/students/")
    assert response.status_code in (401, 403)
    for header, value in EXPECTED.items():
        assert response.headers.get(header) == value
    # Correlation is part of the response contract: a support ticket quoting it
    # must be enough to find the request in the logs.
    assert response.headers.get("x-request-id")


def test_no_hsts_outside_production(client):
    """HSTS on a plain-HTTP development origin would pin localhost to HTTPS."""
    response = client.get("/api/v1/health")
    assert "strict-transport-security" not in response.headers
