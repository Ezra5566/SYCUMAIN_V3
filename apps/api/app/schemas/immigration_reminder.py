"""Immigration expiry reminder schemas.

The reminder is described by the *condition* it was raised for (document, tier,
expiry date) and by its resolution. There is no free-text message here: the
client composes the sentence from ``notifications.<type>`` keys, so the API
stays language-neutral.
"""

from __future__ import annotations

import uuid  # noqa: TC003 - FastAPI resolves UUID at runtime
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel


class ImmigrationReminderRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_number: str
    student_name: str
    #: PASSPORT | VISA | RESIDENCE_PERMIT
    document_type: str
    #: EXPIRED | URGENT | EXPIRING_SOON
    tier: str
    expiry_date: date
    notified_at: datetime
    resolved_at: datetime | None = None
    #: CORRECTED | EXPIRY_UPDATED | PROFILE_UNVERIFIED | STUDENT_INACTIVE
    resolution: str | None = None


class ImmigrationReminderList(BaseModel):
    items: list[ImmigrationReminderRead]
    total: int
    page: int
    page_size: int


class ImmigrationReminderRunResult(BaseModel):
    """What one reconciliation pass changed."""

    evaluated: int
    created: int
    resolved: int
    today: date
