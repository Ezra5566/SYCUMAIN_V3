"""Audit log model.

The audit log is an append-only record of security-sensitive and
administrative actions. It deliberately stores *references* and *safe
metadata* only — never credentials, session tokens, document contents, or
unnecessary personal data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import audit_immutability
from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import User


class AuditLog(Base):
    """A single auditable action performed by a user (or the system)."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Who performed the action. Nullable to allow system-generated entries.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    actor_email: Mapped[str | None] = mapped_column(String(255))

    # What happened. Action codes are stable machine-readable identifiers
    # such as "student.updated" or "immigration.change_request.approved".
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # What it happened to.
    entity_type: Mapped[str | None] = mapped_column(String(50), index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Safe, structured context. Never store secrets or sensitive values here.
    context: Mapped[dict | None] = mapped_column(JSON)

    # Request context, useful for investigations.
    request_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    actor: Mapped[User | None] = relationship("User", foreign_keys=[actor_id])


# Append-only is enforced by the database, not by convention. The trigger is
# installed when the table is created so that `Base.metadata.create_all` (the
# pytest fixture, and any fresh database built from metadata) carries exactly
# the same guarantee as a migrated production schema. The migration
# `d1e4a7b9c2f5` applies the identical SQL to databases whose table already
# exists. See `app/database/audit_immutability.py` for what is installed and
# for the documented limitation (a superuser can still disable the trigger).
event.listen(
    AuditLog.__table__,
    "after_create",
    lambda _target, connection, **_kw: audit_immutability.install(connection),
)
# `drop_all` is used by the test fixture; removing the triggers first keeps the
# function from outliving the table it protects.
event.listen(
    AuditLog.__table__,
    "before_drop",
    lambda _target, connection, **_kw: audit_immutability.uninstall(connection),
)


__all__ = ["AuditLog"]
