"""Housing seed data for Buildings 18-25 (SCU dormitory structure).

This creates the real SCU dormitory structure:
- 8 buildings (18-25)
- 5 floors per building
- Floors 1-4: rooms 101-108 (8 rooms each)
- Floor 5: rooms 501-506 (6 rooms)
- Total: 304 rooms per building cycle
- 4 beds per room (configurable capacity)
"""

from sqlalchemy.orm import Session

from app.models.housing import Bed, Building, Floor, Room, RoomStatus


def seed_housing(db: Session) -> None:
    """Seed the SCU dormitory structure. Idempotent."""
    # Check if buildings already exist
    existing = db.query(Building).first()
    if existing:
        return

    building_numbers = ["18", "19", "20", "21", "22", "23", "24", "25"]
    default_bed_capacity = 4  # Configurable - not assumed from real data

    for bldg_num in building_numbers:
        # Create building
        building = Building(
            name=f"Building {bldg_num}",
            description=f"Dormitory Building {bldg_num}",
            is_active=True,
        )
        db.add(building)
        db.flush()

        # Create 5 floors
        for floor_num in range(1, 6):
            floor = Floor(
                building_id=building.id,
                floor_number=floor_num,
                is_active=True,
            )
            db.add(floor)
            db.flush()

            # Determine rooms for this floor
            if floor_num <= 4:
                # Floors 1-4: rooms 101-108
                room_numbers = [f"{floor_num}{room:02d}" for room in range(1, 9)]
            else:
                # Floor 5: rooms 501-506
                room_numbers = [f"5{room:02d}" for room in range(1, 7)]

            for room_num in room_numbers:
                room = Room(
                    floor_id=floor.id,
                    room_number=room_num,
                    capacity=default_bed_capacity,
                    status=RoomStatus.AVAILABLE,
                    is_active=True,
                )
                db.add(room)
                db.flush()

                # Create beds for each room
                for bed_num in range(1, default_bed_capacity + 1):
                    bed = Bed(
                        room_id=room.id,
                        bed_number=bed_num,
                        label=f"Bed {bed_num}",
                        is_active=True,
                    )
                    db.add(bed)

    db.commit()
