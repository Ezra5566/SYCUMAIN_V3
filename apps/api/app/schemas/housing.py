"""Housing Pydantic schemas for API request/response validation."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.housing import HousingAssignmentStatus, RoomStatus

# --- Building Schemas ---


class BuildingBrief(BaseModel):
    """Brief building representation."""

    id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}


class FloorInBuilding(BaseModel):
    """Floor summary within building detail."""

    id: uuid.UUID
    floor_number: int
    is_active: bool
    room_count: int = 0
    bed_count: int = 0
    occupied_count: int = 0
    available_count: int = 0
    occupancy_status: str = "AVAILABLE"

    model_config = {"from_attributes": True}


class RoomInFloor(BaseModel):
    """Room summary within floor detail."""

    id: uuid.UUID
    room_number: str
    capacity: int
    is_active: bool
    status: RoomStatus
    occupied: int = 0
    available: int = 0
    occupancy_status: str = "AVAILABLE"

    model_config = {"from_attributes": True}


class FloorDetail(BaseModel):
    """Floor with rooms list."""

    id: uuid.UUID
    floor_number: int
    is_active: bool
    room_count: int = 0
    bed_count: int = 0
    occupied_count: int = 0
    available_count: int = 0
    occupancy_status: str = "AVAILABLE"
    rooms: list[RoomInFloor] = []

    model_config = {"from_attributes": True}


class BuildingDetail(BaseModel):
    """Detailed building with floors and occupancy."""

    id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool
    floor_count: int = 0
    room_count: int = 0
    bed_count: int = 0
    occupied_count: int = 0
    available_count: int = 0
    occupancy_status: str = "AVAILABLE"
    floors: list[FloorInBuilding] = []

    model_config = {"from_attributes": True}


# --- Floor Schemas ---


class FloorBrief(BaseModel):
    """Brief floor representation."""

    id: uuid.UUID
    floor_number: int
    is_active: bool
    room_count: int = 0
    bed_count: int = 0
    occupied_count: int = 0

    model_config = {"from_attributes": True}


# --- Room Schemas ---


class RoomBrief(BaseModel):
    """Brief room representation for floor view."""

    id: uuid.UUID
    room_number: str
    capacity: int
    status: RoomStatus
    occupied: int = 0
    available: int = 0
    occupancy_status: str = "AVAILABLE"

    model_config = {"from_attributes": True}


class BedResponse(BaseModel):
    """Bed representation."""

    id: uuid.UUID
    #: Permanent physical-bed number. Never rewritten by retirement.
    bed_number: int
    #: Current sequential number among this room's active beds. Display only;
    #: it changes when an earlier active bed is retired and is never an
    #: identifier for history or assignments.
    display_number: int
    label: str | None = None
    is_active: bool
    is_occupied: bool = False
    student_name: str | None = None
    #: User id that owns the housing assignment (the Stage 4 foreign key).
    student_id: uuid.UUID | None = None
    #: Student-record id for the profile route, not the user id above.
    student_record_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class RoomDetail(BaseModel):
    """Detailed room view with beds."""

    id: uuid.UUID
    room_number: str
    capacity: int
    status: RoomStatus
    occupied: int = 0
    available: int = 0
    occupancy_status: str = "AVAILABLE"
    beds: list[BedResponse] = []

    # Location context
    floor_number: int | None = None
    building_name: str | None = None

    model_config = {"from_attributes": True}


# --- Structure administration schemas ---
#
# Buildings, floors, rooms and beds were seed-only until Stage 8B: the
# dormitory could be visualised but never changed. These schemas drive the
# administrative endpoints that make the structure configurable.


class BuildingCreate(BaseModel):
    """Create a building."""

    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)


class BuildingUpdate(BaseModel):
    """Edit a building. Archiving is `is_active`, never a delete."""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class FloorCreate(BaseModel):
    """Create a floor within a building."""

    floor_number: int = Field(ge=-5, le=200)


class FloorUpdate(BaseModel):
    """Edit a floor."""

    floor_number: int | None = Field(default=None, ge=-5, le=200)
    is_active: bool | None = None


class RoomCreate(BaseModel):
    """Create a room.

    `capacity` is the number of beds to create, expressed as an integer
    because that is what an operator reasons about. The beds are created with
    it, so capacity and beds can never disagree.
    """

    room_number: str = Field(min_length=1, max_length=20)
    capacity: int = Field(default=4, ge=0, le=20)
    status: RoomStatus = RoomStatus.AVAILABLE


class RoomUpdate(BaseModel):
    """Edit a room.

    Raising `capacity` adds the missing beds; lowering it retires the
    highest-numbered empty beds and is refused while they are occupied.
    """

    room_number: str | None = Field(default=None, min_length=1, max_length=20)
    capacity: int | None = Field(default=None, ge=0, le=20)
    status: RoomStatus | None = None
    is_active: bool | None = None


class BedCreate(BaseModel):
    """Add a bed to a room."""

    label: str | None = Field(default=None, max_length=50)
    bed_number: int | None = Field(default=None, ge=1, le=50)


class BedUpdate(BaseModel):
    """Edit or retire a bed."""

    label: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None


# --- Housing Assignment Schemas ---


class HousingAssignmentCreate(BaseModel):
    """Schema for creating a housing assignment."""

    student_id: uuid.UUID
    bed_id: uuid.UUID
    start_date: datetime
    notes: str | None = None


class HousingAssignmentUpdate(BaseModel):
    """Schema for updating a housing assignment."""

    end_date: datetime | None = None
    status: HousingAssignmentStatus | None = None
    notes: str | None = None


class HousingAssignmentTransfer(BaseModel):
    """Schema for transferring a student to a new bed."""

    new_bed_id: uuid.UUID
    transfer_date: datetime
    notes: str | None = None


class HousingAssignmentResponse(BaseModel):
    """Housing assignment response."""

    id: uuid.UUID
    student_id: uuid.UUID
    student_name: str | None = None
    bed_id: uuid.UUID
    bed_label: str | None = None
    room_number: str | None = None
    floor_number: int | None = None
    building_name: str | None = None
    start_date: datetime
    end_date: datetime | None = None
    status: HousingAssignmentStatus
    notes: str | None = None
    created_by_id: uuid.UUID | None = None
    created_by_name: str | None = None
    ended_by_id: uuid.UUID | None = None
    ended_by_name: str | None = None
    ended_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Housing Overview Schemas ---


class RoomOverview(BaseModel):
    """Room in overview visualization."""

    id: uuid.UUID
    room_number: str
    capacity: int
    is_active: bool
    status: RoomStatus
    occupied: int = 0
    available: int = 0
    occupancy_status: str = "AVAILABLE"

    model_config = {"from_attributes": True}


class FloorOverview(BaseModel):
    """Floor in overview visualization."""

    id: uuid.UUID
    floor_number: int
    is_active: bool
    room_count: int = 0
    bed_count: int = 0
    occupied_count: int = 0
    available_count: int = 0
    rooms: list[RoomOverview] = []

    model_config = {"from_attributes": True}


class BuildingOverview(BaseModel):
    """Building overview for dormitory visualization."""

    id: uuid.UUID
    name: str
    floor_count: int
    room_count: int
    bed_count: int
    occupied_count: int
    available_count: int
    occupancy_status: str = "AVAILABLE"
    floors: list[FloorOverview] = []

    model_config = {"from_attributes": True}


class HousingOverviewResponse(BaseModel):
    """Complete housing overview."""

    buildings: list[BuildingOverview]
    total_buildings: int
    total_rooms: int
    total_beds: int
    total_occupied: int
    total_available: int


# --- Student Housing Schemas ---


class StudentHousingResponse(BaseModel):
    """Student's housing information."""

    has_assignment: bool = False
    assignment: HousingAssignmentResponse | None = None
