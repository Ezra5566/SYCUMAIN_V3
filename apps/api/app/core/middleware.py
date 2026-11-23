"""Request correlation and access logging.

Every response carries an ``X-Request-ID``. An inbound id from a proxy or load
balancer is preserved, so a trace started upstream stays intact; otherwise one
is generated. The id is bound to the logging context for the whole request, and
one structured line is emitted per request with its status and latency.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config.settings import get_settings
from app.core.logging import request_id_var, user_id_var

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response

logger = logging.getLogger("app.request")

#: Paths that are probed every few seconds by container health checks. Logging
#: them at INFO would bury real traffic and make the log volume of a healthy
#: system look like an incident.
_QUIET_PATHS = frozenset({"/health", "/ready", "/api/v1/health", "/api/v1/ready"})


#: Baseline browser protections applied to every API response.
#:
#: The API returns JSON to a first-party Next.js client, so a CSP would add
#: little here (the web app sets its own). What matters is that a response can
#: never be interpreted as another type, framed into a hostile page, or leak the
#: backend origin through the referrer.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-site",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a correlation id to the request and log one line for it."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = (request.headers.get("x-request-id") or "").strip()
        # Trusting an arbitrarily long header would let a caller write megabytes
        # into every log line for the duration of the request.
        request_id = incoming[:128] or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            for header, value in _SECURITY_HEADERS.items():
                response.headers.setdefault(header, value)
            if get_settings().is_production and request.url.scheme == "https":
                # Only over TLS: sending HSTS from a plain-HTTP development
                # origin would pin the browser to HTTPS for localhost.
                response.headers.setdefault(
                    "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                )
            return response
        finally:
            # `finally` (not a trailing statement) so a request that raises is
            # still logged — the failing requests are the ones worth having.
            self._log(request, status_code, started, request_id)
            user_id_var.set("")
            request_id_var.reset(token)

    @staticmethod
    def _log(
        request: Request, status_code: int, started: float, request_id: str
    ) -> None:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        path = request.url.path

        if path in _QUIET_PATHS:
            level = logging.DEBUG
        elif status_code >= 500:
            level = logging.ERROR
        elif status_code >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO

        slow_after = get_settings().SLOW_REQUEST_MS
        extra = {
            "method": request.method,
            "path": path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else None,
        }
        if duration_ms >= slow_after:
            extra["slow"] = True
            # A slow but successful request is the early warning that something
            # (a query, the database, storage) is degrading. Surface it at
            # WARNING so it is visible without turning on debug logging.
            level = max(level, logging.WARNING)

        logger.log(level, "request_completed", extra=extra)


__all__ = ["RequestContextMiddleware"]
