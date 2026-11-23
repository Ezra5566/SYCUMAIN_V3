"""User response schemas (no sensitive fields)."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class RoleOut(BaseModel):
    """Role representation in API responses."""

    id: uuid.UUID
    name: str
    description: str | None = None

    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    """User representation in API responses (no password)."""

    id: uuid.UUID
    email: str
    username: str
    full_name: str
    is_active: bool
    roles: list[RoleOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}
