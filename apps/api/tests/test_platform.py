"""Stage 7 tests: announcements, support, notifications, documents, reports, audit.

These tests deliberately exercise authorization and ownership, not just the
happy path: the whole point of the platform layer is that a student cannot
reach another student's records or internal staff notes.
"""

import asyncio
import io
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.audit import sanitize_context
from app.database.session import SessionLocal
from app.main import app, global_exception_handler
from app.models.audit import AuditLog
from app.models.identity import Student, User
from app.models.platform import (
    Announcement,
    Document,
    Notification,
    SupportTicket,
)
from app.seed import seed_roles_and_permissions, seed_test_users
from app.seed_academic import seed_academic
from app.seed_platform import seed_platform
from app.storage import set_storage
from app.storage.local import LocalFilesystemStorage

API = "/api/v1"


@pytest.fixture(scope="module")
def seed_data():
    """Seed everything the platform tests need, once per module."""
    db = SessionLocal()
    try:
        seed_roles_and_permissions(db)
        seed_test_users(db)
        seed_academic(db)
        seed_platform(db)
    finally:
        db.close()


@pytest.fixture
def client(seed_data):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    """Give every test its own private storage root."""
    set_storage(LocalFilesystemStorage(tmp_path))
    yield
    set_storage(None)


def _login(client: TestClient, email: str, password: str = "password123") -> bool:
    return (
        client.post(
            f"{API}/auth/login", json={"email": email, "password": password}
        ).status_code
        == 200
    )


def _student_record(db, email: str) -> Student | None:
    user = db.query(User).filter(User.email == email).first()
    return db.query(Student).filter(Student.user_id == user.id).first() if user else None


def _student_id(client: TestClient, email: str = "student@school.portal") -> uuid.UUID:
    """The authenticated student's own student-record id."""
    db = SessionLocal()
    try:
        return _student_record(db, email).id
    finally:
        db.close()


def _pdf_bytes() -> bytes:
    return b"%PDF-1.4\n% demonstration payload\n"


# ===========================================================================
# 7A/7B — Announcements
# ===========================================================================


class TestAnnouncements:
    def test_unauthenticated_denied(self, client):
        assert client.get(f"{API}/announcements").status_code == 401

    def test_student_can_view_feed(self, client):
        assert _login(client, "student@school.portal")
        response = client.get(f"{API}/announcements")
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert body["total"] >= 1

    def test_student_only_sees_published(self, client):
        """A draft must never appear in a student's feed."""
        assert _login(client, "student@school.portal")
        items = client.get(f"{API}/announcements").json()["items"]
        assert all(item["status"] == "PUBLISHED" for item in items)

    def test_student_cannot_create(self, client):
        assert _login(client, "student@school.portal")
        response = client.post(
            f"{API}/announcements",
            json={"translations": [{"locale": "en", "title": "x", "body": "y"}]},
        )
        assert response.status_code == 403

    def test_management_can_create_draft(self, client):
        assert _login(client, "management@school.portal")
        response = client.post(
            f"{API}/announcements",
            json={
                "translations": [
                    {"locale": "en", "title": "Draft notice", "body": "Body text"},
                    {"locale": "zh", "title": "草稿通知", "body": "正文"},
                ],
                "priority": "HIGH",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "DRAFT"
        assert {t["locale"] for t in data["translations"]} == {"en", "zh"}

    def test_create_requires_a_translation(self, client):
        assert _login(client, "management@school.portal")
        response = client.post(f"{API}/announcements", json={"translations": []})
        assert response.status_code == 422

    def test_teacher_cannot_publish(self, client):
        assert _login(client, "teacher@school.portal")
        db = SessionLocal()
        try:
            announcement = db.query(Announcement).first()
            announcement_id = str(announcement.id)
        finally:
            db.close()

        response = client.post(f"{API}/announcements/{announcement_id}/publish")
        assert response.status_code == 403

    def test_publish_then_visible(self, client):
        assert _login(client, "admin@school.portal")
        created = client.post(
            f"{API}/announcements",
            json={
                "translations": [
                    {"locale": "en", "title": "Publish me", "body": "Body"},
                ],
            },
        ).json()

        published = client.post(f"{API}/announcements/{created['id']}/publish")
        assert published.status_code == 200
        assert published.json()["status"] == "PUBLISHED"

        client.post(f"{API}/auth/logout")
        assert _login(client, "student@school.portal")
        items = client.get(f"{API}/announcements").json()["items"]
        assert any(item["id"] == created["id"] for item in items)

    def test_staff_audience_hidden_from_student(self, client):
        assert _login(client, "admin@school.portal")
        created = client.post(
            f"{API}/announcements",
            json={
                "audience_type": "STAFF",
                "translations": [
                    {"locale": "en", "title": "Internal only", "body": "Staff body"},
                ],
            },
        ).json()
        client.post(f"{API}/announcements/{created['id']}/publish")

        client.post(f"{API}/auth/logout")
        assert _login(client, "student@school.portal")
        items = client.get(f"{API}/announcements").json()["items"]
        assert all(item["id"] != created["id"] for item in items)

        # Direct access must also be refused, not just hidden from the feed.
        detail = client.get(f"{API}/announcements/{created['id']}")
        assert detail.status_code in (403, 404)

    def test_locale_resolution_and_fallback(self, client):
        assert _login(client, "admin@school.portal")
        created = client.post(
            f"{API}/announcements",
            json={
                "default_locale": "en",
                "translations": [
                    {"locale": "en", "title": "English title", "body": "English body"},
                    {"locale": "zh", "title": "中文标题", "body": "中文正文"},
                ],
            },
        ).json()
        announcement_id = created["id"]
        client.post(f"{API}/announcements/{announcement_id}/publish")

        zh = client.get(
            f"{API}/announcements/{announcement_id}",
            headers={"Accept-Language": "zh-CN,zh;q=0.9"},
        ).json()
        assert zh["resolved_title"] == "中文标题"
        assert zh["resolved_locale"] == "zh"

        # French has no translation: fall back to the default locale, keeping
        # the original content intact rather than blanking it.
        fr = client.get(
            f"{API}/announcements/{announcement_id}",
            headers={"Accept-Language": "fr"},
        ).json()
        assert fr["resolved_title"] == "English title"
        assert fr["resolved_locale"] == "en"

    def test_archived_cannot_be_published(self, client):
        assert _login(client, "admin@school.portal")
        created = client.post(
            f"{API}/announcements",
            json={"translations": [{"locale": "en", "title": "A", "body": "B"}]},
        ).json()
        client.post(f"{API}/announcements/{created['id']}/archive")

        response = client.post(f"{API}/announcements/{created['id']}/publish")
        assert response.status_code == 409

    def test_scheduled_announcement_not_yet_live(self, client):
        assert _login(client, "admin@school.portal")
        future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        created = client.post(
            f"{API}/announcements",
            json={
                "scheduled_at": future,
                "translations": [
                    {"locale": "en", "title": "Later", "body": "Not yet"},
                ],
            },
        ).json()
        published = client.post(f"{API}/announcements/{created['id']}/publish")
        assert published.json()["status"] == "SCHEDULED"


# ===========================================================================
# 7C — Support tickets
# ===========================================================================


class TestSupportTickets:
    def test_unauthenticated_denied(self, client):
        assert client.get(f"{API}/support").status_code == 401

    def test_student_can_create_ticket(self, client):
        assert _login(client, "student@school.portal")
        response = client.post(
            f"{API}/support",
            json={
                "category": "HOUSING",
                "subject": "My room heater is broken",
                "description": "The heater in my room has not worked for three days.",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "OPEN"
        assert data["ticket_number"].startswith("SUP-")

    def test_student_cannot_open_ticket_for_someone_else(self, client):
        assert _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            other = db.query(Student).filter(Student.student_id != "STU-001").first()
            other_id = str(other.id) if other else str(uuid.uuid4())
        finally:
            db.close()

        response = client.post(
            f"{API}/support",
            json={
                "category": "GENERAL",
                "subject": "Not mine",
                "description": "Attempting to open a ticket for another student.",
                "student_id": other_id,
            },
        )
        assert response.status_code == 403

    def test_student_cannot_read_another_students_ticket(self, client):
        """A ticket that exists but is not theirs must look like a 404."""
        db = SessionLocal()
        try:
            student = _student_record(db, "student@school.portal")
            ticket = SupportTicket(
                ticket_number=f"SUP-9{uuid.uuid4().hex[:3]}",
                student_id=student.id,
                created_by=student.user_id,
                category="GENERAL",
                subject="Existence probe",
                description="Probe",
            )
            db.add(ticket)
            db.commit()
            ticket_id = str(ticket.id)
        finally:
            db.close()

        assert _login(client, "teacher@school.portal")
        assert client.get(f"{API}/support/{ticket_id}").status_code == 404

    def test_internal_note_never_reaches_student(self, client):
        assert _login(client, "student@school.portal")
        created = client.post(
            f"{API}/support",
            json={
                "category": "IT",
                "subject": "Password reset problem",
                "description": "I cannot reset my portal password.",
            },
        ).json()
        ticket_id = created["id"]

        client.post(f"{API}/auth/logout")
        assert _login(client, "management@school.portal")
        client.post(
            f"{API}/support/{ticket_id}/messages",
            json={"body": "Internal: verify identity offline.", "is_internal": True},
        )
        staff_view = client.get(f"{API}/support/{ticket_id}").json()
        assert any(m["is_internal"] for m in staff_view["messages"])

        client.post(f"{API}/auth/logout")
        assert _login(client, "student@school.portal")
        student_view = client.get(f"{API}/support/{ticket_id}").json()
        assert student_view["messages"] == []
        assert "Internal:" not in str(student_view)

    def test_student_cannot_author_internal_note(self, client):
        assert _login(client, "student@school.portal")
        created = client.post(
            f"{API}/support",
            json={
                "category": "GENERAL",
                "subject": "Requesting internal note",
                "description": "Trying to smuggle an internal note into the thread.",
            },
        ).json()

        message = client.post(
            f"{API}/support/{created['id']}/messages",
            json={"body": "Not internal", "is_internal": True},
        )
        assert message.status_code == 201
        assert message.json()["is_internal"] is False

    def test_student_cannot_update_ticket(self, client):
        assert _login(client, "student@school.portal")
        created = client.post(
            f"{API}/support",
            json={
                "category": "ACADEMIC",
                "subject": "Cannot change subject",
                "description": "Students must not be able to mutate ticket state.",
            },
        ).json()

        response = client.patch(
            f"{API}/support/{created['id']}", json={"status": "RESOLVED"}
        )
        assert response.status_code == 403

    def test_management_can_resolve(self, client):
        assert _login(client, "management@school.portal")
        open_tickets = client.get(f"{API}/support?status=OPEN").json()["items"]
        if not open_tickets:
            pytest.skip("no open tickets available")
        ticket_id = open_tickets[0]["id"]
        response = client.patch(
            f"{API}/support/{ticket_id}",
            json={"status": "RESOLVED", "resolution_note": "Handled."},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "RESOLVED"

    def test_teacher_only_sees_own_or_assigned(self, client):
        assert _login(client, "teacher@school.portal")
        items = client.get(f"{API}/support").json()["items"]
        # A teacher has no assignments or authored tickets in the seed.
        assert items == []

    def test_stats_are_scoped(self, client):
        assert _login(client, "student@school.portal")
        response = client.get(f"{API}/support/stats")
        assert response.status_code == 200
        assert response.json()["total"] >= 1


# ===========================================================================
# 7D — Notifications
# ===========================================================================


class TestNotifications:
    def test_unauthenticated_denied(self, client):
        assert client.get(f"{API}/notifications").status_code == 401

    def test_ticket_creation_notifies_management(self, client):
        assert _login(client, "student@school.portal")
        client.post(
            f"{API}/support",
            json={
                "category": "VISA_IMMIGRATION",
                "subject": "Visa question needing staff attention",
                "description": "I have a question about my visa renewal.",
            },
        )
        client.post(f"{API}/auth/logout")

        assert _login(client, "management@school.portal")
        items = client.get(f"{API}/notifications").json()["items"]
        assert any(n["type"] == "SUPPORT_TICKET_CREATED" for n in items)

    def test_student_only_sees_own_notifications(self, client):
        assert _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            me = db.query(User).filter(User.email == "student@school.portal").first()
            my_id = me.id
        finally:
            db.close()

        items = client.get(f"{API}/notifications").json()["items"]
        db = SessionLocal()
        try:
            for item in items:
                row = db.query(Notification).filter(Notification.id == item["id"]).first()
                assert row.user_id == my_id
        finally:
            db.close()

    def test_cannot_mark_another_users_notification_read(self, client):
        db = SessionLocal()
        try:
            other = db.query(User).filter(User.email == "admin@school.portal").first()
            notification = Notification(
                user_id=other.id,
                type="DOCUMENT_UPLOADED",
                params={},
            )
            db.add(notification)
            db.commit()
            notification_id = str(notification.id)
        finally:
            db.close()

        assert _login(client, "student@school.portal")
        response = client.post(f"{API}/notifications/{notification_id}/read")
        assert response.status_code == 404

    def test_mark_read_and_read_all(self, client):
        assert _login(client, "student@school.portal")
        listing = client.get(f"{API}/notifications").json()
        if not listing["items"]:
            pytest.skip("no notifications for student")
        first = listing["items"][0]["id"]
        assert client.post(f"{API}/notifications/{first}/read").status_code == 200

        assert client.post(f"{API}/notifications/read-all").status_code == 200
        assert client.get(f"{API}/notifications/unread-count").json()["unread_count"] == 0

    def test_reply_notifies_student(self, client):
        assert _login(client, "student@school.portal")
        created = client.post(
            f"{API}/support",
            json={
                "category": "GENERAL",
                "subject": "Notification round trip",
                "description": "Staff reply should notify the student.",
            },
        ).json()
        client.post(f"{API}/auth/logout")

        assert _login(client, "management@school.portal")
        client.post(
            f"{API}/support/{created['id']}/messages",
            json={"body": "We are looking into this.", "is_internal": False},
        )
        client.post(f"{API}/auth/logout")

        assert _login(client, "student@school.portal")
        items = client.get(f"{API}/notifications").json()["items"]
        assert any(n["type"] == "SUPPORT_TICKET_REPLIED" for n in items)


# ===========================================================================
# 7E — Documents
# ===========================================================================


class TestDocuments:
    def test_unauthenticated_upload_denied(self, client):
        response = client.post(
            f"{API}/documents",
            files={"file": ("x.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={"document_type": "OTHER", "title": "x"},
        )
        assert response.status_code == 401

    def test_student_uploads_own_document(self, client):
        assert _login(client, "student@school.portal")
        response = client.post(
            f"{API}/documents",
            files={"file": ("cert.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={"document_type": "OTHER", "title": "My certificate"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["content_type"] == "application/pdf"
        assert data["visibility"] == "STUDENT_VISIBLE"
        # Storage internals must never leak to the client.
        assert "object_key" not in data
        assert "storage_provider" not in data

    def test_student_cannot_upload_for_another_student(self, client):
        assert _login(client, "student@school.portal")
        db = SessionLocal()
        try:
            other = db.query(Student).filter(Student.student_id != "STU-001").first()
            other_id = str(other.id) if other else str(uuid.uuid4())
        finally:
            db.close()

        response = client.post(
            f"{API}/documents",
            files={"file": ("x.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={
                "document_type": "OTHER",
                "title": "Not mine",
                "student_id": other_id,
            },
        )
        assert response.status_code == 403

    def test_text_file_rejected_despite_pdf_filename(self, client):
        """A lying filename/Content-Type must not get past validation."""
        assert _login(client, "student@school.portal")
        response = client.post(
            f"{API}/documents",
            files={
                "file": (
                    "innocent.pdf",
                    io.BytesIO(b"#!/bin/sh\nrm -rf /\n"),
                    "application/pdf",
                )
            },
            data={"document_type": "OTHER", "title": "Trojan"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    def test_content_type_mismatch_rejected(self, client):
        assert _login(client, "student@school.portal")
        response = client.post(
            f"{API}/documents",
            files={
                "file": ("photo.png", io.BytesIO(_pdf_bytes()), "image/png"),
            },
            data={"document_type": "OTHER", "title": "Mismatch"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "CONTENT_TYPE_MISMATCH"

    def test_oversized_upload_rejected(self, client, monkeypatch):
        from app.config.settings import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)

        assert _login(client, "student@school.portal")
        big = _pdf_bytes() + b"0" * (1024 * 1024 + 10)
        response = client.post(
            f"{API}/documents",
            files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
            data={"document_type": "OTHER", "title": "Too big"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "FILE_TOO_LARGE"

    def test_empty_file_rejected(self, client):
        assert _login(client, "student@school.portal")
        response = client.post(
            f"{API}/documents",
            files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
            data={"document_type": "OTHER", "title": "Empty"},
        )
        assert response.status_code == 422

    def test_staff_only_document_hidden_from_student(self, client):
        db = SessionLocal()
        try:
            student = _student_record(db, "student@school.portal")
            admin = db.query(User).filter(User.email == "admin@school.portal").first()
            student_id = str(student.id)
            admin_id = admin.id
        finally:
            db.close()

        assert _login(client, "admin@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={"file": ("internal.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={
                "document_type": "OTHER",
                "title": "Staff-only note",
                "student_id": student_id,
                "student_visible": "false",
            },
        )
        assert uploaded.status_code == 201
        document_id = uploaded.json()["id"]
        assert uploaded.json()["visibility"] == "STAFF_ONLY"

        db = SessionLocal()
        try:
            row = db.query(Document).filter(Document.id == document_id).first()
            assert row.uploaded_by == admin_id
        finally:
            db.close()

        client.post(f"{API}/auth/logout")
        assert _login(client, "student@school.portal")
        # Listing must hide it, and direct access must 404 rather than leak.
        listed = client.get(f"{API}/documents").json()["items"]
        assert all(d["id"] != document_id for d in listed)
        assert client.get(f"{API}/documents/{document_id}").status_code == 404
        assert (
            client.get(f"{API}/documents/{document_id}/download").status_code == 404
        )

    def test_authorized_download_returns_bytes(self, client):
        assert _login(client, "student@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={"file": ("dl.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={"document_type": "OTHER", "title": "Download me"},
        ).json()

        response = client.get(f"{API}/documents/{uploaded['id']}/download")
        assert response.status_code == 200
        assert response.content == _pdf_bytes()
        assert response.headers["content-type"] == "application/pdf"
        assert "no-store" in response.headers.get("cache-control", "")

    def test_archived_document_not_listed(self, client):
        assert _login(client, "admin@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={"file": ("arch.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={"document_type": "OTHER", "title": "Archive me"},
        ).json()
        assert client.delete(f"{API}/documents/{uploaded['id']}").status_code == 204

        listed = client.get(
            f"{API}/documents", params={"search": "Archive me"}
        ).json()["items"]
        assert listed == []

        # Archived documents are not downloadable either.
        assert (
            client.get(f"{API}/documents/{uploaded['id']}/download").status_code
            == 404
        )

        # Managers can still see them for audit purposes.
        archived = client.get(
            f"{API}/documents",
            params={"search": "Archive me", "include_archived": True},
        ).json()["items"]
        assert len(archived) == 1
        assert archived[0]["status"] == "ARCHIVED"

    def test_student_cannot_delete_documents(self, client):
        assert _login(client, "student@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={"file": ("mine.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={"document_type": "OTHER", "title": "Mine"},
        ).json()

        assert client.delete(f"{API}/documents/{uploaded['id']}").status_code == 403

    def test_storage_key_does_not_embed_unsafe_filename(self, client):
        """Keys must be generated, never derived from the uploaded name."""
        assert _login(client, "student@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={
                "file": (
                    "../../etc/passwd.pdf",
                    io.BytesIO(_pdf_bytes()),
                    "application/pdf",
                )
            },
            data={"document_type": "OTHER", "title": "Traversal"},
        )
        assert uploaded.status_code == 201

        db = SessionLocal()
        try:
            row = (
                db.query(Document)
                .filter(Document.id == uploaded.json()["id"])
                .first()
            )
            assert ".." not in row.object_key
            assert "/etc/" not in row.object_key
            assert row.object_key.endswith(".pdf")
        finally:
            db.close()


# ===========================================================================
# 7F — Reports
# ===========================================================================


class TestReports:
    def test_unauthenticated_denied(self, client):
        assert client.get(f"{API}/reports/overview").status_code == 401

    def test_student_denied(self, client):
        assert _login(client, "student@school.portal")
        assert client.get(f"{API}/reports/overview").status_code == 403

    def test_teacher_denied(self, client):
        assert _login(client, "teacher@school.portal")
        assert client.get(f"{API}/reports/students").status_code == 403

    def test_management_can_read_reports(self, client):
        assert _login(client, "management@school.portal")
        overview = client.get(f"{API}/reports/overview")
        assert overview.status_code == 200
        data = overview.json()
        assert set(data) >= {"students", "immigration", "housing", "academics"}
        assert data["students"]["total"] >= 1

    def test_housing_report_matches_housing_service(self, client):
        """The report must not disagree with the canonical occupancy logic."""
        from app.models.housing import Room
        from app.services.housing import calculate_room_occupancy

        assert _login(client, "management@school.portal")
        report = client.get(f"{API}/reports/housing").json()

        db = SessionLocal()
        try:
            rooms = db.query(Room).all()
            expected_full = sum(
                1
                for r in rooms
                if calculate_room_occupancy(r)["occupancy_status"] == "FULL"
            )
        finally:
            db.close()

        assert report["rooms_full"] == expected_full

    def test_housing_report_uses_active_inventory_only(self, client):
        """Inactive beds and deactivated buildings must not add capacity."""
        from app.models.housing import Bed, Building, Floor, Room

        assert _login(client, "management@school.portal")
        baseline_report = client.get(f"{API}/reports/housing").json()
        baseline_overview = client.get(f"{API}/housing/overview").json()

        suffix = uuid.uuid4().hex[:8]
        db = SessionLocal()
        building = None
        try:
            building = Building(name=f"UAT Active Inventory {suffix}", is_active=True)
            db.add(building)
            db.flush()
            floor = Floor(building_id=building.id, floor_number=1, is_active=True)
            db.add(floor)
            db.flush()
            room = Room(
                floor_id=floor.id,
                room_number="TEST-1",
                capacity=2,
                status="AVAILABLE",
                is_active=True,
            )
            db.add(room)
            db.flush()
            db.add_all(
                [
                    Bed(room_id=room.id, bed_number=1, is_active=True),
                    # Historical inventory: present in the table, but not a
                    # usable bed for capacity or occupancy.
                    Bed(room_id=room.id, bed_number=2, is_active=False),
                ]
            )
            db.commit()

            report = client.get(f"{API}/reports/housing").json()
            overview = client.get(f"{API}/housing/overview").json()
            assert report["total_beds"] == baseline_report["total_beds"] + 1
            assert overview["total_beds"] == baseline_overview["total_beds"] + 1
            assert report["total_beds"] == overview["total_beds"]
            assert report["total_rooms"] == overview["total_rooms"]
            assert report["total_buildings"] == overview["total_buildings"]

            building.is_active = False
            db.commit()

            report = client.get(f"{API}/reports/housing").json()
            overview = client.get(f"{API}/housing/overview").json()
            assert report["total_beds"] == baseline_report["total_beds"]
            assert overview["total_beds"] == baseline_overview["total_beds"]
            assert report["total_rooms"] == baseline_report["total_rooms"]
            assert report["total_buildings"] == baseline_report["total_buildings"]
        finally:
            if building is not None:
                db.rollback()
                db.query(Bed).filter(
                    Bed.room_id.in_(
                        db.query(Room.id)
                        .join(Floor, Floor.id == Room.floor_id)
                        .filter(Floor.building_id == building.id)
                    )
                ).delete(synchronize_session=False)
                db.query(Room).filter(
                    Room.floor_id.in_(
                        db.query(Floor.id).filter(Floor.building_id == building.id)
                    )
                ).delete(synchronize_session=False)
                db.query(Floor).filter(Floor.building_id == building.id).delete(
                    synchronize_session=False
                )
                db.query(Building).filter(Building.id == building.id).delete(
                    synchronize_session=False
                )
                db.commit()
            db.close()

    def test_immigration_report_buckets(self, client):
        assert _login(client, "management@school.portal")
        report = client.get(f"{API}/reports/immigration").json()
        for key in (
            "valid",
            "expiring_30_days",
            "expiring_90_days",
            "expired",
            "missing_information",
        ):
            assert key in report
            assert report[key] >= 0


# ===========================================================================
# 7G — Audit
# ===========================================================================


class TestAudit:
    def test_student_denied(self, client):
        assert _login(client, "student@school.portal")
        assert client.get(f"{API}/audit").status_code == 403

    def test_teacher_denied(self, client):
        assert _login(client, "teacher@school.portal")
        assert client.get(f"{API}/audit").status_code == 403

    def test_login_is_audited_without_credentials(self, client):
        assert _login(client, "admin@school.portal")
        entries = client.get(f"{API}/audit?action=auth.login_succeeded").json()
        assert entries["total"] >= 1

        entry = entries["items"][0]
        serialized = str(entry)
        assert "password123" not in serialized
        assert "session_token" not in serialized
        assert entry["context"] in (None, {})

    def test_failed_login_is_audited(self, client):
        client.post(
            f"{API}/auth/login",
            json={"email": "admin@school.portal", "password": "wrong-password"},
        )
        assert _login(client, "admin@school.portal")
        entries = client.get(f"{API}/audit?action=auth.login_failed").json()
        assert entries["total"] >= 1
        # The attempted address must not be recorded for failed logins.
        assert "wrong-password" not in str(entries)

    def test_student_update_is_audited_without_values(self, client):
        db = SessionLocal()
        try:
            student = _student_record(db, "student@school.portal")
            student_id = str(student.id)
        finally:
            db.close()

        assert _login(client, "management@school.portal")
        client.patch(f"{API}/students/{student_id}", json={"phone": "+1 555 0100"})

        entries = client.get(
            f"{API}/audit?action=student.updated&entity_id={student_id}"
        ).json()
        assert entries["total"] >= 1
        # Field names are recorded; the new value is not.
        assert "+1 555 0100" not in str(entries)

    def test_ticket_and_document_actions_are_audited(self, client):
        assert _login(client, "admin@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={"file": ("audit.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")},
            data={"document_type": "OTHER", "title": "Audited"},
        ).json()
        assert uploaded["id"]

        entries = client.get(f"{API}/audit?action=document.uploaded").json()
        assert entries["total"] >= 1

    def test_sanitize_context_redacts_sensitive_keys(self):
        sanitized = sanitize_context(
            {
                "password": "hunter2",
                "session_token": "abc",
                "passport_number": "X1234567",
                "nested": {"api_secret": "shh", "ok": "visible"},
                "changed_fields": ["phone"],
            }
        )
        assert sanitized["password"] == "[redacted]"
        assert sanitized["session_token"] == "[redacted]"
        assert sanitized["passport_number"] == "[redacted]"
        assert sanitized["nested"]["api_secret"] == "[redacted]"
        assert sanitized["nested"]["ok"] == "visible"
        assert sanitized["changed_fields"] == ["phone"]


# ===========================================================================
# Cross-module integration
# ===========================================================================


class TestCrossModuleIntegration:
    def test_publishing_announcement_notifies_recipients(self, client):
        assert _login(client, "admin@school.portal")
        created = client.post(
            f"{API}/announcements",
            json={
                "audience_type": "STUDENTS",
                "translations": [
                    {"locale": "en", "title": "Notify students", "body": "Hello"},
                ],
            },
        ).json()
        client.post(f"{API}/announcements/{created['id']}/publish")
        client.post(f"{API}/auth/logout")

        assert _login(client, "student@school.portal")
        items = client.get(f"{API}/notifications").json()["items"]
        assert any(
            n["type"] == "ANNOUNCEMENT_PUBLISHED"
            and n["entity_id"] == created["id"]
            for n in items
        )

    def test_immigration_submission_notifies_reviewers(self, client):
        student_id = _student_id(client)
        assert _login(client, "student@school.portal")
        submitted = client.post(
            f"{API}/students/{student_id}/immigration/change-requests",
            json={
                "change_type": "VISA",
                "proposed_data": {"visa_expiry_date": "2028-01-01"},
            },
        )
        assert submitted.status_code == 201
        request_id = submitted.json()["id"]
        client.post(f"{API}/auth/logout")

        assert _login(client, "management@school.portal")
        items = client.get(f"{API}/notifications").json()["items"]
        assert any(
            n["type"] == "IMMIGRATION_CHANGE_SUBMITTED"
            and n["entity_id"] == request_id
            for n in items
        )

    def test_immigration_approval_notifies_student(self, client):
        student_id = _student_id(client)
        assert _login(client, "student@school.portal")
        request_id = client.post(
            f"{API}/students/{student_id}/immigration/change-requests",
            json={
                "change_type": "PASSPORT",
                "proposed_data": {"passport_issuing_country": "Kazakhstan"},
            },
        ).json()["id"]
        client.post(f"{API}/auth/logout")

        assert _login(client, "management@school.portal")
        approved = client.post(f"{API}/immigration/change-requests/{request_id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "APPROVED"
        client.post(f"{API}/auth/logout")

        assert _login(client, "student@school.portal")
        items = client.get(f"{API}/notifications").json()["items"]
        assert any(
            n["type"] == "IMMIGRATION_CHANGE_APPROVED"
            and n["entity_id"] == request_id
            for n in items
        )

    def test_sensitive_immigration_values_absent_from_audit(self, client):
        db = SessionLocal()
        try:
            student = _student_record(db, "student@school.portal")
            student_id = str(student.id)
        finally:
            db.close()

        assert _login(client, "management@school.portal")
        client.patch(
            f"{API}/students/{student_id}/immigration",
            json={"passport_number": "ZZ9999999"},
        )

        entries = client.get(f"{API}/audit?entity_type=student").json()
        assert "ZZ9999999" not in str(entries)


# ===========================================================================
# Regression: previous stages still behave
# ===========================================================================


class TestStage7Regression:
    def test_teacher_scope_on_students_is_enforced(self, client):
        """Teachers are limited to their own class rosters (Stage 6 gap closed)."""
        assert _login(client, "teacher@school.portal")
        listing = client.get(f"{API}/students")
        assert listing.status_code == 200

        db = SessionLocal()
        try:
            students = db.query(Student).all()
            allowed_ids = {item["id"] for item in listing.json()["items"]}
            # Any student not in the teacher's scope must 403 on detail.
            for student in students:
                if str(student.id) not in allowed_ids:
                    detail = client.get(f"{API}/students/{student.id}")
                    assert detail.status_code == 403
                    break
        finally:
            db.close()

    def test_housing_assignment_detail_endpoints_work(self, client):
        assert _login(client, "management@school.portal")
        overview = client.get(f"{API}/housing/overview")
        assert overview.status_code == 200

        db = SessionLocal()
        try:
            from app.models.housing import HousingAssignment

            assignment = db.query(HousingAssignment).first()
            assignment_id = str(assignment.id) if assignment else None
        finally:
            db.close()

        if assignment_id:
            assert client.get(
                f"{API}/housing/assignments/{assignment_id}"
            ).status_code == 200

    def test_student_denied_housing_assignment_of_others(self, client):
        db = SessionLocal()
        try:
            from app.models.housing import HousingAssignment

            me = db.query(User).filter(User.email == "student@school.portal").first()
            other = (
                db.query(HousingAssignment)
                .filter(HousingAssignment.student_id != me.id)
                .first()
            )
            other_id = str(other.id) if other else None
        finally:
            db.close()

        if other_id is None:
            pytest.skip("no foreign assignment in seed")

        assert _login(client, "student@school.portal")
        assert (
            client.get(f"{API}/housing/assignments/{other_id}").status_code == 403
        )

    def test_documents_endpoint_does_not_leak_storage_internals(self, client):
        assert _login(client, "admin@school.portal")
        listing = client.get(f"{API}/documents")
        assert listing.status_code == 200
        payload = str(listing.json())
        assert "object_key" not in payload
        assert "storage_provider" not in payload
        assert "checksum" not in payload


# ===========================================================================
# §28 — Authorization hardening across earlier modules
# ===========================================================================


def _first_class_section_id() -> uuid.UUID | None:
    db = SessionLocal()
    try:
        from app.models.academic import ClassSection

        row = db.query(ClassSection).first()
        return row.id if row else None
    finally:
        db.close()


class TestAuthorizationHardening:
    """Cross-module gaps closed during Stage 7.

    Both cases are "object scope was conflated with feature access": holding
    `housing.view` or `academic.view` meant "this record is yours", not "you may
    browse the whole institution".
    """

    def test_student_cannot_browse_dormitory(self, client):
        """A student must not be able to enumerate rooms and their occupants."""
        assert _login(client, "student@school.portal")
        assert client.get(f"{API}/housing/buildings").status_code == 403
        assert client.get(f"{API}/housing/overview").status_code == 403

    def test_student_can_still_read_own_housing(self, client):
        """The self-service path must keep working after the restriction."""
        student_id = _student_id(client)
        assert _login(client, "student@school.portal")
        response = client.get(f"{API}/housing/students/{student_id}/housing")
        assert response.status_code == 200

    def test_management_can_browse_dormitory(self, client):
        assert _login(client, "management@school.portal")
        assert client.get(f"{API}/housing/buildings").status_code == 200
        assert client.get(f"{API}/housing/overview").status_code == 200

    def test_teacher_still_has_no_housing_browse(self, client):
        """Teachers were never granted housing administration."""
        assert _login(client, "teacher@school.portal")
        assert client.get(f"{API}/housing/buildings").status_code == 403

    def test_student_cannot_read_a_class_roster(self, client):
        """`academic.view` is self-scoped for students, not a roster permission."""
        class_id = _first_class_section_id()
        if class_id is None:
            pytest.skip("no class sections in seed")

        assert _login(client, "student@school.portal")
        assert (
            client.get(f"{API}/academics/classes/{class_id}/enrollments").status_code
            == 403
        )
        assert (
            client.get(f"{API}/academics/classes/{class_id}/grades").status_code == 403
        )
        assert (
            client.get(f"{API}/academics/classes/{class_id}/attendance").status_code
            == 403
        )

    def test_student_still_reads_own_attendance_and_grades(self, client):
        student_id = _student_id(client)
        assert _login(client, "student@school.portal")
        assert (
            client.get(f"{API}/academics/students/{student_id}/attendance").status_code
            == 200
        )
        assert (
            client.get(f"{API}/academics/students/{student_id}/grades").status_code
            == 200
        )

    def test_management_can_read_a_class_roster(self, client):
        class_id = _first_class_section_id()
        if class_id is None:
            pytest.skip("no class sections in seed")

        assert _login(client, "management@school.portal")
        assert (
            client.get(f"{API}/academics/classes/{class_id}/enrollments").status_code
            == 200
        )


class TestAuditVocabularyContract:
    """The audit action vocabulary is a contract shared with the web catalogs.

    A code the frontend cannot name is displayed humanized at best, and an
    untranslated token at worst. Scanning the call sites here means adding a
    new audited action without a translation fails CI instead of shipping.
    """

    @staticmethod
    def _recorded_actions() -> set[str]:
        app_dir = Path(__file__).resolve().parent.parent / "app"
        pattern = re.compile(r'action="([a-z_]+\.[a-z_.]+)"')
        found: set[str] = set()
        for path in app_dir.rglob("*.py"):
            found.update(pattern.findall(path.read_text(encoding="utf-8")))
        return found

    @staticmethod
    def _catalog_actions() -> set[str]:
        catalog = (
            Path(__file__).resolve().parent.parent.parent
            / "web"
            / "messages"
            / "en.json"
        )
        if not catalog.exists():
            pytest.skip("web message catalog is not present in this checkout")
        data = json.loads(catalog.read_text(encoding="utf-8"))["audit"]["actions"]

        found: set[str] = set()

        def walk(node: dict, prefix: str) -> None:
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    walk(value, path)
                else:
                    found.add(path)

        walk(data, "")
        return found

    def test_backend_records_at_least_one_action(self):
        # Guards the scanner itself: a regex that matches nothing would make
        # the contract test below vacuously pass.
        assert len(self._recorded_actions()) > 10

    def test_every_recorded_action_has_a_translation(self):
        missing = sorted(self._recorded_actions() - self._catalog_actions())
        assert missing == [], f"audited actions without a message: {missing}"


class TestAcademicAudit:
    """Stage 6 mutations must leave an audit trail (Stage 7 §30)."""

    def test_enrollment_mutations_are_audited(self, client):
        """Drop an existing enrollment, then re-enroll the same student.

        Re-using a seeded enrollment avoids depending on spare capacity: the
        drop frees the seat we immediately take again.
        """
        db = SessionLocal()
        try:
            from app.models.academic import Enrollment

            enrollment = db.query(Enrollment).first()
            if enrollment is None:
                pytest.skip("seed has no enrollments")
            class_id = str(enrollment.class_section_id)
            enrollment_id = str(enrollment.id)
            student_id = str(enrollment.student_id)
        finally:
            db.close()

        assert _login(client, "management@school.portal")

        dropped = client.post(
            f"{API}/academics/classes/{class_id}/enrollments/{enrollment_id}/drop"
        )
        if dropped.status_code != 200:
            pytest.skip(f"seed enrollment cannot be dropped ({dropped.status_code})")

        created = client.post(
            f"{API}/academics/classes/{class_id}/enrollments",
            json={"student_id": student_id},
        )
        assert created.status_code == 201

        db = SessionLocal()
        try:
            actions = {
                entry.action
                for entry in db.query(AuditLog)
                .filter(
                    AuditLog.action.in_(
                        ["academic.enrollment.created", "academic.enrollment.dropped"]
                    )
                )
                .order_by(AuditLog.created_at.desc())
                .limit(10)
                .all()
            }
        finally:
            db.close()

        assert "academic.enrollment.dropped" in actions
        assert "academic.enrollment.created" in actions


def _origin_request(origin: str | None) -> Request:
    headers = [(b"origin", origin.encode())] if origin else []
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/attendance/commencements",
            "raw_path": b"/api/v1/attendance/commencements",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 51234),
            "server": ("testserver", 80),
        }
    )


class TestUnhandledErrorCors:
    """A 500 must stay readable by the browser, not look like a network failure.

    Starlette installs the 500 handler on ``ServerErrorMiddleware``, which sits
    outside ``CORSMiddleware``. Without headers attached in the handler the
    browser rejects the response as a CORS failure, so the UI reports an
    unreachable server for a request the server actually answered.
    """

    def test_allowed_origin_receives_cors_headers(self) -> None:
        response = asyncio.run(
            global_exception_handler(
                _origin_request("http://localhost:3100"), RuntimeError("boom")
            )
        )

        assert response.status_code == 500
        assert (
            response.headers["access-control-allow-origin"] == "http://localhost:3100"
        )
        assert response.headers["access-control-allow-credentials"] == "true"
        assert json.loads(response.body)["error"]["code"] == "INTERNAL_SERVER_ERROR"

    def test_foreign_origin_is_not_echoed(self) -> None:
        response = asyncio.run(
            global_exception_handler(
                _origin_request("http://evil.example"), RuntimeError("boom")
            )
        )

        assert "access-control-allow-origin" not in response.headers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
