"""Student profile: profile photo and self-service academic placement.

Two capabilities Stage 8C added to the profile, both of which are easy to get
wrong in ways a happy-path test would not notice:

* the photo is private — it is served through an authorization-checked endpoint
  and never as a URL — and it is validated by magic number, not by filename;
* a student may declare their own major exactly once, after which the placement
  is institutional and only management may change it.

The storage backend is redirected to a per-test temporary directory so these
tests never write into the real object store.
"""

from __future__ import annotations

import struct
import uuid
import zlib
from typing import TYPE_CHECKING

import pytest

from app.database.session import SessionLocal
from app.models.identity import Student, User
from app.seed_academic import seed_academic
from app.storage import set_storage
from app.storage.local import LocalFilesystemStorage

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

API = "/api/v1"


def _png_bytes() -> bytes:
    """A minimal valid 1x1 PNG, built rather than checked in as a fixture."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        crc = zlib.crc32(body) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="module", autouse=True)
def academic_seed():
    """Academic structure the placement tests need, seeded once and committed.

    Committed rather than seeded inside the test transaction: the application
    seeds on startup from a second connection, and rows left uncommitted here
    would make that startup pass block on the uncommitted unique keys.
    """
    db = SessionLocal()
    try:
        seed_academic(db)
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path):
    set_storage(LocalFilesystemStorage(tmp_path))
    yield
    set_storage(None)


def _onboard_stranger(client: TestClient) -> str:
    """Create a student with no enrolments, so no teacher can reach them."""
    suffix = uuid.uuid4().hex[:8]
    resp = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"STR{suffix.upper()}",
            "first_name": "Unauthorised",
            "last_name": "Target",
            "email": f"stranger{suffix}@example.com",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["student"]["id"]


def _login(client: TestClient, email: str, password: str = "password123") -> None:
    resp = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


def _student_record(email: str) -> Student:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None
        student = db.query(Student).filter(Student.user_id == user.id).first()
        assert student is not None
        return student
    finally:
        db.close()


def _error_code(resp) -> str:
    return resp.json()["error"]["code"]


# ── Profile photo ──


def test_student_uploads_and_removes_own_photo(client):
    """The round trip a student actually performs from their profile."""
    _login(client, "student@school.portal")
    student = _student_record("student@school.portal")

    upload = client.put(
        f"{API}/students/{student.id}/photo",
        files={"file": ("avatar.png", _png_bytes(), "image/png")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["has_photo"] is True

    # The response carries no URL: the image is only reachable through the
    # authorization-checked endpoint.
    assert "profile_photo_url" not in upload.json()

    fetched = client.get(f"{API}/students/{student.id}/photo")
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.content == _png_bytes()

    removed = client.delete(f"{API}/students/{student.id}/photo")
    assert removed.status_code == 200
    assert removed.json()["has_photo"] is False
    assert client.get(f"{API}/students/{student.id}/photo").status_code == 404


def test_photo_rejects_a_text_file_named_png(client):
    """Validation is by magic number, so the extension buys nothing."""
    _login(client, "student@school.portal")
    student = _student_record("student@school.portal")

    resp = client.put(
        f"{API}/students/{student.id}/photo",
        files={"file": ("avatar.png", b"this is not an image", "image/png")},
    )
    assert resp.status_code in (400, 415, 422), resp.text


def test_student_cannot_set_another_students_photo(client):
    """Ownership is enforced on the write, not just in the UI.

    The victim is created here rather than picked from the seed: relying on the
    seed having a second student made this test depend on data it does not own.
    """
    _login(client, "admin@school.portal")
    victim_id = _onboard_stranger(client)

    _login(client, "student@school.portal")
    resp = client.put(
        f"{API}/students/{victim_id}/photo",
        files={"file": ("avatar.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code in (403, 404), resp.text


# ── Self-service academic placement ──


def test_placement_status_exposes_whether_selection_is_allowed(client):
    """The UI decides between a picker and a read-only value from this flag."""
    _login(client, "student@school.portal")
    resp = client.get(f"{API}/students/me/academic")
    assert resp.status_code == 200
    assert "can_select" in resp.json()


def test_self_service_direct_selection_is_retired(client):
    """Phase 8a: a student can no longer write the placement projection."""
    _login(client, "student@school.portal")
    majors = client.get(f"{API}/academics/majors").json()["items"]
    assert majors, "academic seed must provide at least one major"
    major_id = majors[0]["id"]

    refused = client.post(f"{API}/students/me/academic", json={"major_id": major_id})
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "PLACEMENT_DIRECT_WRITE_RETIRED"

    # The UI reads the same retirement decision and does not offer the picker.
    assert client.get(f"{API}/students/me/academic").json()["can_select"] is False


def test_onboarding_uses_a_mapped_period_offering(client, monkeypatch):
    """Source-only offerings are shown as unavailable and refused.

    The declaration flow must use the intake offering, not the legacy
    major/program pair, and it must not let a clerk place a student into a
    source row that has no reviewed canonical parent.
    """
    from app.config.settings import get_settings

    monkeypatch.setattr(get_settings(), "ADMISSIONS_WRITE_ENABLED", True)
    _login(client, "admin@school.portal")
    suffix = uuid.uuid4().hex[:8]
    period = client.post(
        f"{API}/academics/periods",
        json={
            "name": f"Placement intake {suffix}",
            "code": f"PI-{suffix}",
            "start_date": "2034-09-01",
            "end_date": "2034-12-20",
            "status": "ACTIVE",
        },
    )
    assert period.status_code == 201, period.text
    period_id = period.json()["id"]
    program = client.get(f"{API}/academics/programs").json()["items"][0]

    source_only = client.post(
        f"{API}/academics/program-offerings",
        json={
            "academic_period_id": period_id,
            "source_id": f"source-{suffix}",
            "name": f"Unmapped source {suffix}",
        },
    )
    assert source_only.status_code == 201, source_only.text
    assert source_only.json()["selectable"] is False
    assert source_only.json()["unavailable_reason"] == "SOURCE_ONLY"

    refused = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"SRC{suffix.upper()}",
            "first_name": "Source",
            "last_name": "Only",
            "email": f"source-{suffix}@example.com",
            "program_offering_id": source_only.json()["id"],
        },
    )
    assert refused.status_code == 409, refused.text
    assert _error_code(refused) == "PROGRAM_OFFERING_NOT_MAPPED"

    mapped = client.post(
        f"{API}/academics/program-offerings",
        json={
            "academic_period_id": period_id,
            "source_id": f"mapped-{suffix}",
            "name": f"Mapped source {suffix}",
            "program_id": program["id"],
        },
    )
    assert mapped.status_code == 201, mapped.text
    assert mapped.json()["selectable"] is True

    created = client.post(
        f"{API}/students/onboard",
        json={
            "student_id": f"MAP{suffix.upper()}",
            "first_name": "Mapped",
            "last_name": "Offering",
            "email": f"mapped-{suffix}@example.com",
            "program_offering_id": mapped.json()["id"],
            "initial_admission_status": "ACTIVE",
        },
    )
    assert created.status_code == 201, created.text
    student = created.json()["student"]
    assert student["program_offering_id"] == mapped.json()["id"]
    assert student["program_id"] == program["id"]
    assert student["major_id"] == program["major_id"]


def test_management_cannot_change_a_students_major_through_the_profile(client):
    """Phase 8a retires the profile placement fields for every role."""
    _login(client, "admin@school.portal")
    listing = client.get(f"{API}/students/", params={"page_size": 5}).json()
    student_id = listing["items"][0]["id"]
    majors = client.get(f"{API}/academics/majors").json()["items"]
    before = client.get(f"{API}/students/{student_id}").json()

    resp = client.patch(
        f"{API}/students/{student_id}",
        json={"major_id": majors[0]["id"]},
    )
    assert resp.status_code == 409, resp.text
    assert _error_code(resp) == "PLACEMENT_DIRECT_WRITE_RETIRED"

    after = client.get(f"{API}/students/{student_id}").json()
    assert after["major_id"] == before["major_id"]
    assert after["program_id"] == before["program_id"]
    assert after["program_offering_id"] == before["program_offering_id"]


def test_student_cannot_change_official_fields_through_self_service(client):
    """The self-service allowlist is the boundary, not the form."""
    _login(client, "student@school.portal")
    student = _student_record("student@school.portal")
    original_number = student.student_id
    original_status = student.status

    resp = client.patch(
        f"{API}/students/{student.id}/self",
        json={
            "phone": "+86 555 0100",
            # Neither of these is on the allowlist; both must be ignored.
            "student_id": "HACKED-1",
            "status": "GRADUATED",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phone"] == "+86 555 0100"
    assert body["student_id"] == original_number
    assert body["status"] == original_status


def test_student_cannot_use_the_management_update_endpoint(client):
    """`PATCH /students/{id}` is the administrative path, not self-service."""
    _login(client, "student@school.portal")
    student = _student_record("student@school.portal")
    resp = client.patch(f"{API}/students/{student.id}", json={"status": "GRADUATED"})
    assert resp.status_code == 403


def test_teacher_cannot_read_an_unrelated_students_records(client):
    """A teacher's reach is their own class rosters and nothing wider.

    `permissions/scope.py` deliberately scopes teachers to students enrolled in
    a class section they are assigned to, so this asserts the *outside* of that
    boundary: a student with no enrolment is invisible, and immigration — which
    teachers do not hold at all — stays invisible even for the students they
    do teach.
    """
    _login(client, "admin@school.portal")
    stranger_id = _onboard_stranger(client)

    _login(client, "teacher@school.portal")
    assert client.get(f"{API}/documents/students/{stranger_id}/summary").status_code in (
        403,
        404,
    )
    assert client.get(f"{API}/students/{stranger_id}").status_code in (403, 404)
    assert client.get(f"{API}/students/{stranger_id}/immigration").status_code in (
        401,
        403,
        404,
    )
