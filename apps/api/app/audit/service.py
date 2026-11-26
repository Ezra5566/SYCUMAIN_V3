"""Audit recording service.

Design notes
------------
* `record_audit` only *adds* to the caller's session — it never commits on
  its own. This means an audit entry shares the transaction of the change it
  describes: if the change rolls back, so does its audit record. There is no
  way to end up with an audit trail that claims something happened when it
  did not.
* Any context passed in is passed through :func:`sanitize_context` first.
  The denylist below is a safety net, not a licence to pass sensitive data
  in: callers must still only pass identifiers and non-sensitive metadata.
"""

import enum
import uuid
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session as DBSession

from app.models.audit import AuditLog
from app.models.identity import User

# Keys whose values must never reach the audit log, matched
# case-insensitively as substrings.
SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "password",
    "hashed",
    "token",
    "secret",
    "session",
    "cookie",
    "authorization",
    "passport_number",
    "visa_number",
    "residence_permit_number",
    "passport_name",
    "checksum",
    "content",
    "body",
    "file_bytes",
)

REDACTED = "[redacted]"
MAX_CONTEXT_VALUE_LENGTH = 200

#: Sentinel for "this field was not present in the snapshot".
_MISSING = object()


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS)


def sanitize_value(value: Any) -> Any:
    """Convert one value to something stable and JSON-safe for the audit log.

    Dates, enums, decimals and UUIDs get an explicit representation rather
    than a bare ``str()``, so a previous/new pair recorded from a historical
    record and one recorded from a request payload compare equal. Anything
    else falls back to a truncated string, which is what the log always did.
    """
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) > MAX_CONTEXT_VALUE_LENGTH:
            return value[:MAX_CONTEXT_VALUE_LENGTH] + "..."
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, Decimal):
        # A JSON number keeps prior/new comparable with the float scores the
        # existing audit events already store ("previous_score": 85.5).
        return float(value)
    return str(value)[:MAX_CONTEXT_VALUE_LENGTH]


def sanitize_context(value: Any) -> Any:
    """Recursively strip sensitive keys and over-long values.

    This is deliberately conservative: a key that merely *looks* sensitive is
    redacted rather than logged.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(str(key)) else sanitize_context(val)
            for key, val in value.items()
        }
    if isinstance(value, list | tuple):
        return [sanitize_context(item) for item in value]
    return sanitize_value(value)


def field_changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    fields: Iterable[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return ``{field: {"previous": ..., "new": ...}}`` for changed fields.

    Only fields whose value actually differs are included, so a request that
    resubmits an unchanged value does not create a misleading "change". A
    field that appears in one snapshot and not the other is a change from/to
    ``None``, which is how a cleared optional field is represented.

    Values are *not* sanitized here: ``record_audit`` runs the whole context
    through :func:`sanitize_context`, which applies the field-level policy
    (identifiers such as ``passport_number`` are redacted, and the key itself
    still shows that the field changed).
    """
    candidate_keys = list(fields) if fields is not None else sorted(
        set(before) | set(after)
    )
    changes: dict[str, dict[str, Any]] = {}
    for key in candidate_keys:
        previous = before.get(key, _MISSING)
        current = after.get(key, _MISSING)
        if previous is _MISSING and current is _MISSING:
            continue
        if previous is not _MISSING and current is not _MISSING:
            if previous == current:
                continue
        changes[key] = {
            "previous": None if previous is _MISSING else sanitize_value(previous),
            "new": None if current is _MISSING else sanitize_value(current),
        }
    return changes


def request_context(request: Any | None) -> dict[str, str | None]:
    """Extract safe request metadata (client IP and correlation id)."""
    if request is None:
        return {"ip_address": None, "request_id": None}

    request_id = request.headers.get("x-request-id")
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip_address = forwarded.split(",")[0].strip()
    else:
        ip_address = request.client.host if request.client else None

    return {"ip_address": ip_address, "request_id": request_id}


def record_audit(
    db: DBSession,
    *,
    action: str,
    actor: User | None = None,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    context: dict[str, Any] | None = None,
    request: Any | None = None,
) -> AuditLog:
    """Stage an audit entry on the current transaction.

    The caller is responsible for committing (usually by committing the same
    transaction that performed the audited change).
    """
    request_meta = request_context(request)

    entry = AuditLog(
        actor_id=actor.id if actor is not None else actor_id,
        actor_email=actor.email if actor is not None else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        context=sanitize_context(context) if context else None,
        request_id=request_meta["request_id"],
        ip_address=request_meta["ip_address"],
    )
    db.add(entry)
    return entry


__all__ = [
    "field_changes",
    "record_audit",
    "request_context",
    "sanitize_context",
    "sanitize_value",
]
