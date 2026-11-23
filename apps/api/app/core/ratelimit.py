"""Fixed-window rate limiting for login and password recovery.

Three properties matter more than the algorithm:

* **Shared across processes.** Counters live in PostgreSQL, so two API workers
  enforce one limit instead of two independent ones.
* **No permanent lockout.** A fixed window expires on its own. An attacker who
  knows an address cannot lock its owner out of the portal indefinitely, which
  is what a per-account lockout counter would allow.
* **No personal data at rest.** Keys are HMAC-SHA256 of the limited value under
  ``SECRET_KEY``; the table holds neither addresses nor email.

Throttling is checked *before* credentials are verified, so a locked-out
attacker learns nothing about whether an address exists.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config.settings import get_settings
from app.models.ratelimit import AuthRateLimit

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession


class RateLimitError(Exception):
    """Raised when a caller has spent its allowance for the current window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limit exceeded")
        #: Seconds until the current window ends; never zero, so the
        #: ``Retry-After`` header is always actionable.
        self.retry_after_seconds = max(retry_after_seconds, 1)


@dataclass(frozen=True)
class Limit:
    """One allowance: a scope, a number of attempts, and a window."""

    scope: str
    max_attempts: int
    window_seconds: int


def _key_hash(scope: str, value: str) -> str:
    """Hash the limited value under the application secret."""
    secret = get_settings().SECRET_KEY.encode()
    return hmac.new(secret, f"{scope}:{value}".encode(), hashlib.sha256).hexdigest()


def _window_start(now: datetime, window_seconds: int) -> datetime:
    """Start of the fixed window containing ``now``."""
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % window_seconds), UTC)


def check(
    db: DBSession, *, limit: Limit, value: str, now: datetime | None = None
) -> None:
    """Count one attempt and raise when the allowance is spent.

    The increment is a single ``INSERT ... ON CONFLICT DO UPDATE``, so
    concurrent requests cannot both read a stale count and slip through.
    """
    moment = now or datetime.now(UTC)
    window_start = _window_start(moment, limit.window_seconds)
    key_hash = _key_hash(limit.scope, value)

    statement = (
        pg_insert(AuthRateLimit)
        .values(
            scope=limit.scope,
            key_hash=key_hash,
            window_start=window_start,
            count=1,
        )
        .on_conflict_do_update(
            index_elements=[
                AuthRateLimit.scope,
                AuthRateLimit.key_hash,
                AuthRateLimit.window_start,
            ],
            set_={"count": AuthRateLimit.count + 1},
        )
        .returning(AuthRateLimit.count)
    )
    count = db.execute(statement).scalar_one()
    db.commit()

    if count > limit.max_attempts:
        window_end = window_start + timedelta(seconds=limit.window_seconds)
        raise RateLimitError(int((window_end - moment).total_seconds()) + 1)


def clear(db: DBSession, *, limit: Limit, value: str) -> None:
    """Forget a caller's counters for this scope.

    Called after a *successful* authentication: a legitimate user who mistyped
    their password a few times should not carry that history into their next
    session.
    """
    db.execute(
        delete(AuthRateLimit).where(
            AuthRateLimit.scope == limit.scope,
            AuthRateLimit.key_hash == _key_hash(limit.scope, value),
        )
    )
    db.commit()


def purge_expired(db: DBSession, *, older_than_hours: int = 24) -> int:
    """Delete counters whose window closed long ago.

    Age is measured from the end of the window, not its start, so a counter is
    only removed once it can no longer affect a decision.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
    deleted = (
        db.query(AuthRateLimit)
        .filter(AuthRateLimit.window_start < cutoff)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted)


__all__ = ["Limit", "RateLimitError", "check", "clear", "purge_expired"]
