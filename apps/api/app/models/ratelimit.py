"""Rate-limit counters for the authentication surface.

The limiter is deliberately database-backed rather than in-process: a
per-process dictionary stops working the moment the API runs more than one
worker or is restarted, which is exactly when an attacker would benefit. The
deployment already has PostgreSQL, so a small table with an atomic upsert gives
a shared counter without adding Redis to the architecture.

Rows hold an HMAC of the limited value, never the address or email itself: the
table is operational state, not another copy of the identity data.
"""

from __future__ import annotations

# Imported at runtime, not under TYPE_CHECKING: SQLAlchemy resolves the
# annotations of mapped attributes when the class is created.
from datetime import datetime  # noqa: TC003

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class AuthRateLimit(Base):
    """One fixed-window counter per (scope, hashed key, window)."""

    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        # Cleanup and reporting scan by window, not by key.
        Index("ix_auth_rate_limits_window_start", "window_start"),
    )

    #: Which surface is limited, e.g. ``login:ip`` or ``reset-request:email``.
    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    #: HMAC-SHA256 of the limited value (address, email, or both).
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: Start of the fixed window this counter belongs to.
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


__all__ = ["AuthRateLimit"]
