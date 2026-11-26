"""Cross-site request protection for state-changing requests.

The API authenticates with an HttpOnly session cookie. A cookie alone does not
stop a hostile page from making the browser send a state-changing request, so
that class of request needs an explicit check. ``SameSite=Lax`` already blocks
the common cross-site ``POST`` — but it is a *browser default*, not an
application decision: it changes with browser policy, a future ``SameSite=None``
(e.g. for an embedded portal) would silently remove the protection, and it does
not cover clients that ignore cookie attributes.

This middleware is the application-level decision. It applies to unsafe methods
only (``POST``, ``PUT``, ``PATCH``, ``DELETE``) and compares the request's
``Origin`` against the explicitly configured trusted origins — the same list the
CORS configuration uses, so there is exactly one place to configure an origin
and no way for the two policies to drift apart.

Trust decisions, stated deliberately:

* **``Origin`` present and trusted** — allowed. This is every same-origin
  request from the portal, because browsers send ``Origin`` on unsafe methods
  even when the target is the same origin.
* **``Origin`` present and not trusted** — rejected with ``403`` and
  ``CSRF_ORIGIN_REJECTED`` before routing, authentication or any database write.
  This includes the literal ``null`` origin used by sandboxed frames and
  ``file://`` documents.
* **No ``Origin`` at all** — allowed *only* when the request does not look like
  a cross-site browser navigation. Browsers always send ``Origin`` for unsafe
  methods, so its absence means a non-browser client: the browser test suite,
  ``curl``, an institutional integration, or a health probe. Two headers that
  can accompany a forged request are still checked when present:
  ``Sec-Fetch-Site: cross-site`` and a cross-origin ``Referer`` both cause a
  rejection.

The host header is deliberately never consulted: behind a reverse proxy it is
caller-controlled unless the proxy is trusted to rewrite it, so deciding
"same-origin" from ``Host`` would let a forged ``Host`` authorize a request.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

logger = logging.getLogger("app.security")

#: Methods that can change state. ``GET``/``HEAD``/``OPTIONS`` are excluded:
#: they must remain safe, and a CORS preflight is an ``OPTIONS`` request that
#: carries no cookie and performs no action.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Error code carried by a rejection. It has a message in all five locales.
REJECTION_CODE = "CSRF_ORIGIN_REJECTED"


def normalise_origin(value: str) -> str:
    """Return a comparable origin: lower-case, no trailing slash.

    An origin is scheme, host and port only. Paths, queries and userinfo are
    stripped rather than compared, so ``https://portal.example.edu/login`` and
    ``https://portal.example.edu`` are the same origin — which is what the
    browser's ``Origin`` header means.
    """
    candidate = value.strip()
    if not candidate:
        return ""
    parts = urlsplit(candidate)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}".lower()


class OriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject unsafe cross-origin requests before they reach the application."""

    def __init__(self, app: ASGIApp, trusted_origins: Iterable[str]) -> None:
        super().__init__(app)
        self._trusted: frozenset[str] = frozenset(
            normalised
            for normalised in (normalise_origin(origin) for origin in trusted_origins)
            if normalised
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin is not None:
            if normalise_origin(origin) in self._trusted:
                return await call_next(request)
            return self._reject(request, f"untrusted Origin {origin!r}")

        # No Origin header: a browser would have sent one for an unsafe method.
        fetch_site = (request.headers.get("sec-fetch-site") or "").strip().lower()
        if fetch_site == "cross-site":
            return self._reject(request, "Sec-Fetch-Site: cross-site without Origin")

        referer = request.headers.get("referer")
        if referer:
            referer_origin = normalise_origin(referer)
            if referer_origin and referer_origin not in self._trusted:
                return self._reject(request, f"cross-origin Referer {referer!r}")

        return await call_next(request)

    @staticmethod
    def _reject(request: Request, reason: str) -> JSONResponse:
        # Logged at WARNING: a rejected unsafe request is either a
        # misconfigured deployment origin or an attack attempt. Both are worth
        # seeing, and neither should be silent.
        logger.warning(
            "origin_rejected",
            extra={"method": request.method, "path": request.url.path, "reason": reason},
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    # Written as a literal so the translation-parity check sees
                    # this code as emitted by the API, not merely reserved.
                    "code": "CSRF_ORIGIN_REJECTED",
                    "message": (
                        "This request did not come from a trusted origin. "
                        "Sign in again from the portal."
                    ),
                }
            },
            headers={"Vary": "Origin"},
        )


__all__: Sequence[str] = ["OriginGuardMiddleware", "UNSAFE_METHODS", "normalise_origin"]
