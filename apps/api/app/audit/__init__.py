"""Audit package - event logging infrastructure.

Usage::

    from app.audit import record_audit

    record_audit(
        db,
        action="student.updated",
        actor=current_user,
        entity_type="student",
        entity_id=student.id,
        context={"changed_fields": ["phone"]},
        request=request,
    )
    db.commit()  # the audit entry commits with the change
"""

from app.audit.service import (
    field_changes,
    record_audit,
    request_context,
    sanitize_context,
    sanitize_value,
)

__all__ = [
    "field_changes",
    "record_audit",
    "request_context",
    "sanitize_context",
    "sanitize_value",
]
