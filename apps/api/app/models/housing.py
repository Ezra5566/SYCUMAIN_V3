"""Housing models: Building, Floor, Room, Bed, HousingAssignment."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.session import Base

if TYPE_CHECKING:
    from app.models.identity import User


class RoomStatus(enum.StrEnum):
    """Room operational status."""

    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RESERVED = "RESERVED"


class HousingAssignmentStatus(enum.StrEnum):
    """Housing assignment status."""

    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class Building(Base):
    """Dormitory building."""

    __tablename__ = "buildings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    floors: Mapped[list[Floor]] = relationship(
        back_populates="building", order_by="Floor.floor_number", lazy="selectin"
    )


class Floor(Base):
    """Building floor."""

    __tablename__ = "floors"
    __table_args__ = (
        UniqueConstraint("building_id", "floor_number", name="uq_floor_building_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    building_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("buildings.id"), nullable=False, index=True
    )
    floor_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    building: Mapped[Building] = relationship(back_populates="floors")
    rooms: Mapped[list[Room]] = relationship(
        back_populates="floor", order_by="Room.room_number", lazy="selectin"
    )


class Room(Base):
    """Dormitory room."""

    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("floor_id", "room_number", name="uq_room_floor_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    floor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("floors.id"), nullable=False, index=True
    )
    room_number: Mapped[str] = mapped_column(String(20), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    status: Mapped[RoomStatus] = mapped_column(
        String(20), nullable=False, default=RoomStatus.AVAILABLE
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    floor: Mapped[Floor] = relationship(back_populates="rooms")
    beds: Mapped[list[Bed]] = relationship(
        back_populates="room", order_by="Bed.bed_number", lazy="selectin"
    )


class Bed(Base):
    """Individual bed in a room."""

    __tablename__ = "beds"
    __table_args__ = (
        UniqueConstraint("room_id", "bed_number", name="uq_bed_room_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rooms.id"), nullable=False, index=True
    )
    bed_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    room: Mapped[Room] = relationship(back_populates="beds")
    assignments: Mapped[list[HousingAssignment]] = relationship(
        back_populates="bed", lazy="selectin"
    )


class HousingAssignment(Base):
    """Student housing assignment linking a student to a bed."""

    __tablename__ = "housing_assignments"
    # At most one ACTIVE assignment per bed and per student. Application checks
    # alone cannot close the check-then-insert race, so PostgreSQL enforces it.
    __table_args__ = (
        Index(
            "uq_housing_assignment_active_bed",
            "bed_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index(
            "uq_housing_assignment_active_student",
            "student_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    bed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("beds.id"), nullable=False, index=True
    )
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[HousingAssignmentStatus] = mapped_column(
        String(20), nullable=False, default=HousingAssignmentStatus.ACTIVE, index=True
    )
    notes: Mapped[str | None] = mapped_column(String(500))

    # Responsibility is part of the record, not only of the audit log. History
    # must remain readable even if audit retention is configured separately.
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    ended_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    student: Mapped[User] = relationship(
        "User", foreign_keys=[student_id]
    )
    created_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[created_by_id]
    )
    ended_by: Mapped[User | None] = relationship(
        "User", foreign_keys=[ended_by_id]
    )
    bed: Mapped[Bed] = relationship(back_populates="assignments")


__all__ = [
    "Building",
    "Floor",
    "Room",
    "Bed",
    "HousingAssignment",
    "RoomStatus",
    "HousingAssignmentStatus",
]
