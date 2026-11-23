"""Immigration expiry reminders.

These tests pin the rules that make the reminders trustworthy.

* Only ``VERIFIED`` profiles drive an official reminder. An unverified import
  produces nothing, however urgent its dates look.
* The warning windows are the institution's existing tiers (30 / 90 days), not a
  second definition invented for this feature.
* Re-running the job never duplicates a warning.
* When the underlying condition is corrected, the open alert resolves and says
  why; the alert itself stays in the history.
* A student is notified about their own document only. Staff see the operational
  list; students and teachers cannot read it.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from app.auth.service import hash_password
from app.models.identity import Role, Student, User
from app.models.immigration import ImmigrationProfile
from app.models.immigration_reminder import ImmigrationReminder
from app.models.platform import Notification, NotificationType

API = "/api/v1/immigration"
LOGIN = "/api/v1/auth/login"

ADMIN = "admin@school.portal"
MANAGEMENT = "management@school.portal"
TEACHER = "teacher@school.portal"

TODAY = date.today()


def _day(offset: int) -> date:
    return TODAY + timedelta(days=offset)


def _login(client, email: str) -> None:
    response = client.post(LOGIN, json={"email": email, "password": "password123"})
    assert response.status_code == 200, response.text


def _mk_student(db, tag: str) -> Student:
    user = User(
        email=f"rem-{tag}-{uuid.uuid4().hex[:8]}@test.local",
        username=f"rem-{tag}-{uuid.uuid4().hex[:8]}",
        hashed_password=hash_password("password123"),
        full_name=f"Rem {tag}",
        is_active=True,
    )
    db.add(user)
    db.flush()
    role = db.query(Role).filter(Role.name == "STUDENT").first()
    assert role is not None
    user.roles.append(role)
    student = Student(
        user_id=user.id,
        student_id=f"REM-{tag.upper()}-{uuid.uuid4().hex[:6]}",
        first_name="Rem",
        last_name=tag,
        status="ACTIVE",
    )
    db.add(student)
    db.flush()
    return student


def _mk_profile(
    db,
    tag: str,
    *,
    verification: str = "VERIFIED",
    visa_in: int | None = 20,
    passport_in: int | None = 400,
    permit_in: int | None = None,
) -> tuple[Student, ImmigrationProfile]:
    student = _mk_student(db, tag)
    profile = ImmigrationProfile(
        student_id=student.id,
        visa_expiry_date=_day(visa_in) if visa_in is not None else None,
        passport_expiry_date=_day(passport_in) if passport_in is not None else None,
        residence_permit_expiry_date=(
            _day(permit_in) if permit_in is not None else None
        ),
        verification_status=verification,
        data_source="MANAGEMENT",
    )
    db.add(profile)
    db.flush()
    return student, profile


def _run(client):
    return client.post(f"{API}/reminders/run")


def _reminders(db) -> list[ImmigrationReminder]:
    return db.query(ImmigrationReminder).order_by(ImmigrationReminder.created_at).all()


class TestGeneration:
    def test_an_unverified_profile_produces_no_reminder(self, client, db_session):
        _mk_profile(db_session, "unverified", verification="UNVERIFIED", visa_in=5)
        db_session.commit()

        _login(client, MANAGEMENT)
        response = _run(client)
        assert response.status_code == 200, response.text
        assert response.json()["created"] == 0
        assert _reminders(db_session) == []

    def test_a_verified_urgent_document_raises_one_reminder(self, client, db_session):
        student, profile = _mk_profile(db_session, "urgent", visa_in=20)
        db_session.commit()

        # ``evaluated`` is a whole-database figure, so it is compared with the
        # verified profiles actually present rather than assumed to be one.
        verified = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.verification_status == "VERIFIED")
            .count()
        )

        _login(client, MANAGEMENT)
        body = _run(client).json()
        assert body["created"] == 1
        assert body["evaluated"] == verified

        rows = _reminders(db_session)
        assert rows
        rows = [row for row in rows if row.immigration_profile_id == profile.id]
        assert len(rows) == 1
        row = rows[0]
        assert row.immigration_profile_id == profile.id
        assert row.student_id == student.id
        assert row.document_type == "VISA"
        assert row.tier == "URGENT"
        assert row.expiry_date == _day(20)
        assert row.resolved_at is None

    def test_each_tier_is_its_own_reminder(self, client, db_session):
        _mk_profile(
            db_session,
            "tiers",
            passport_in=-3,
            visa_in=20,
            permit_in=70,
        )
        db_session.commit()

        _login(client, MANAGEMENT)
        body = _run(client).json()
        assert body["created"] == 3

        tiers = {(row.document_type, row.tier) for row in _reminders(db_session)}
        assert tiers == {
            ("PASSPORT", "EXPIRED"),
            ("VISA", "URGENT"),
            ("RESIDENCE_PERMIT", "EXPIRING_SOON"),
        }

    def test_a_valid_document_raises_nothing(self, client, db_session):
        _mk_profile(db_session, "valid", visa_in=365, passport_in=800)
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _run(client).json()["created"] == 0
        assert _reminders(db_session) == []

    def test_running_twice_does_not_duplicate(self, client, db_session):
        _mk_profile(db_session, "dedupe", visa_in=10)
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _run(client).json()["created"] == 1
        second = _run(client).json()
        assert second["created"] == 0
        assert second["resolved"] == 0
        assert len(_reminders(db_session)) == 1

    def test_a_reversed_correction_reopens_the_same_alert(self, client, db_session):
        """Resolving then re-qualifying for the same expiry must not 500.

        The unique index covers resolved rows, so the reconciliation has to
        reopen the existing alert instead of inserting an identical one.
        """
        from app.services.immigration_reminders import run_expiry_reminders  # noqa: PLC0415

        _student, profile = _mk_profile(db_session, "reopen", visa_in=10)
        db_session.commit()

        assert run_expiry_reminders(db_session)["created"] == 1

        profile.visa_expiry_date = _day(400)
        db_session.commit()
        assert run_expiry_reminders(db_session)["resolved"] == 1

        profile.visa_expiry_date = _day(10)
        db_session.commit()
        reopened = run_expiry_reminders(db_session)

        assert reopened["created"] == 1
        rows = [
            row for row in _reminders(db_session)
            if row.immigration_profile_id == profile.id
        ]
        assert len(rows) == 1
        assert rows[0].resolved_at is None
        assert rows[0].resolution is None

    def test_direct_service_reruns_are_idempotent(self, client, db_session):
        from app.services.immigration_reminders import run_expiry_reminders  # noqa: PLC0415

        _mk_profile(db_session, "idempotent", visa_in=10)
        db_session.commit()

        first = run_expiry_reminders(db_session)
        second = run_expiry_reminders(db_session)
        assert first["created"] == 1
        assert second["created"] == 0
        assert len(_reminders(db_session)) == 1


class TestRecipients:
    def test_the_student_is_notified_about_their_own_document_only(
        self, client, db_session
    ):
        mine, _profile = _mk_profile(db_session, "recipient-mine", visa_in=15)
        other, _other_profile = _mk_profile(db_session, "recipient-other", visa_in=200)
        db_session.commit()

        _login(client, MANAGEMENT)
        _run(client)

        mine_notifications = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == mine.user_id,
                Notification.type == NotificationType.IMMIGRATION_EXPIRY_URGENT,
            )
            .all()
        )
        other_notifications = (
            db_session.query(Notification)
            .filter(
                Notification.user_id == other.user_id,
                Notification.type == NotificationType.IMMIGRATION_EXPIRY_URGENT,
            )
            .all()
        )
        assert len(mine_notifications) == 1
        assert mine_notifications[0].params["document"] == "visa"
        assert other_notifications == []

    def test_admin_and_management_receive_the_operational_alert(
        self, client, db_session
    ):
        _mk_profile(db_session, "staff-alert", visa_in=15)
        db_session.commit()

        _login(client, MANAGEMENT)
        _run(client)

        recipients = {
            row.user_id
            for row in db_session.query(Notification)
            .filter(Notification.type == NotificationType.IMMIGRATION_EXPIRY_URGENT)
            .all()
        }
        admin = db_session.query(User).filter(User.email == ADMIN).first()
        management = db_session.query(User).filter(User.email == MANAGEMENT).first()
        assert admin is not None and management is not None
        assert admin.id in recipients
        assert management.id in recipients


class TestResolution:
    def test_renewing_the_document_resolves_the_alert(self, client, db_session):
        _student, profile = _mk_profile(db_session, "renew", visa_in=10)
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _run(client).json()["created"] == 1

        profile.visa_expiry_date = _day(400)
        db_session.commit()

        body = _run(client).json()
        assert body["created"] == 0
        assert body["resolved"] == 1

        row = _reminders(db_session)[0]
        assert row.resolved_at is not None
        assert row.resolution == "EXPIRY_UPDATED"

    def test_a_corrected_date_resolves_the_alert(self, client, db_session):
        _student, profile = _mk_profile(db_session, "corrected", visa_in=10)
        db_session.commit()

        _login(client, MANAGEMENT)
        _run(client)

        # Same tier, different date: a typo was corrected to a later, still
        # urgent expiry. The old alert must not linger.
        profile.visa_expiry_date = _day(25)
        db_session.commit()

        body = _run(client).json()
        assert body["resolved"] == 1
        rows = _reminders(db_session)
        assert any(row.resolution == "EXPIRY_UPDATED" for row in rows)
        assert any(row.resolved_at is None and row.expiry_date == _day(25) for row in rows)

    def test_losing_verification_resolves_the_alert(self, client, db_session):
        _student, profile = _mk_profile(db_session, "unverify", visa_in=10)
        db_session.commit()

        _login(client, MANAGEMENT)
        _run(client)

        profile.verification_status = "DISPUTED"
        db_session.commit()

        body = _run(client).json()
        assert body["resolved"] == 1
        assert _reminders(db_session)[0].resolution == "PROFILE_UNVERIFIED"

    def test_resolved_history_is_kept(self, client, db_session):
        _student, profile = _mk_profile(db_session, "history", visa_in=10)
        db_session.commit()

        _login(client, MANAGEMENT)
        _run(client)
        profile.visa_expiry_date = None
        db_session.commit()
        _run(client)

        rows = _reminders(db_session)
        assert len(rows) == 1
        assert rows[0].resolved_at is not None

        listed = client.get(f"{API}/reminders", params={"status": "resolved"}).json()
        assert listed["total"] == 1
        assert listed["items"][0]["resolution"] is not None

        still_open = client.get(f"{API}/reminders", params={"status": "open"}).json()
        assert still_open["total"] == 0


class TestAccess:
    def test_a_student_cannot_read_the_reminder_list(self, client, db_session):
        student, _profile = _mk_profile(db_session, "access-student", visa_in=10)
        db_session.commit()

        _login(client, student.user.email)
        assert client.get(f"{API}/reminders").status_code == 403
        assert _run(client).status_code == 403

    def test_a_teacher_cannot_read_the_reminder_list(self, client, db_session):
        _login(client, TEACHER)
        assert client.get(f"{API}/reminders").status_code == 403
        assert _run(client).status_code == 403

    def test_management_can_list_and_run(self, client, db_session):
        _mk_profile(db_session, "access-management", visa_in=10)
        db_session.commit()

        _login(client, MANAGEMENT)
        assert _run(client).status_code == 200
        listing = client.get(f"{API}/reminders").json()
        assert listing["total"] == 1
        assert listing["items"][0]["document_type"] == "VISA"
        assert listing["items"][0]["student_number"].startswith("REM-")
