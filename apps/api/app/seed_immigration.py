"""Immigration seed data for development and testing."""

from datetime import date, timedelta

from sqlalchemy.orm import Session as DBSession

from app.models.identity import Student
from app.models.immigration import ImmigrationProfile


def seed_immigration(db: DBSession) -> None:
    """Create immigration profiles for existing test students.

    This is idempotent - running multiple times won't create duplicates.
    """
    # Check if immigration profiles already exist
    existing = db.query(ImmigrationProfile).first()
    if existing:
        return

    students = db.query(Student).all()

    today = date.today()

    for student in students:
        profile = ImmigrationProfile(
            student_id=student.id,
            # Passport data (various statuses for testing)
            passport_number=f"PA{student.student_id[-4:]}",
            passport_issuing_country=student.nationality or "Unknown",
            passport_issue_date=today - timedelta(days=365 * 5),
            passport_expiry_date=today + timedelta(days=365 * 2),
            passport_name_as_shown=f"{student.first_name} {student.last_name}",
            # Visa data (mix of valid, expiring, expired)
            visa_type="X1",
            visa_number=f"V{student.student_id[-6:]}",
            visa_issue_date=today - timedelta(days=180),
            visa_expiry_date=today + timedelta(days=180),
            visa_entries="MULTIPLE",
            visa_issuing_authority="Chinese Embassy",
            # Residence Permit
            residence_permit_number=f"RP{student.student_id[-6:]}",
            residence_permit_issue_date=today - timedelta(days=90),
            residence_permit_expiry_date=today + timedelta(days=275),
            residence_permit_issuing_authority="Local PSB",
        )
        db.add(profile)

    db.commit()
