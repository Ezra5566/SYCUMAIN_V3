"""Institutional lifecycle and governance regression tests.

These tests exercise the rules that make the operational workflows safe:
staff profile linkage, reasoned role changes, teacher data boundaries,
document review transitions, accepted-version immutability and import
provenance.
"""

from __future__ import annotations

import io
import uuid
from typing import TYPE_CHECKING

from app.auth.service import hash_password
from app.database.session import SessionLocal
from app.models.identity import Role, Staff, Student, User
from app.models.immigration import ImmigrationProfile
from app.models.platform import Document, DocumentReviewStatus, DocumentScanStatus
from app.services.immigration import (
    import_immigration_profile,
    update_immigration_profile,
)
from app.storage import get_storage

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

API = "/api/v1"
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<<>>\n%%EOF\n"
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x00\x05\xfe\x02\xfe\xdc\xcc\x59\xe7\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _login(client: TestClient, email: str, password: str = "password123") -> None:
    response = client.post(
        f"{API}/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _create_account(client: TestClient, *, roles: list[str], **extra: object):
    payload = {
        "email": f"{_unique('staff')}@example.com",
        "full_name": "Institutional Staff",
        "roles": roles,
        **extra,
    }
    return client.post(f"{API}/users/", json=payload)


def _upload(client: TestClient, title: str = "Governance file", data: bytes = PDF):
    return client.post(
        f"{API}/documents",
        files={"file": ("evidence.pdf", io.BytesIO(data), "application/pdf")},
        data={"document_type": "PASSPORT", "title": title},
    )


class TestStaffLifecycle:
    def test_staff_account_creates_linked_profile_without_invented_number(
        self, client, db_session
    ):
        _login(client, "admin@school.portal")
        response = _create_account(
            client,
            roles=["TEACHER"],
            department="Faculty of Engineering",
            title="Lecturer",
        )
        assert response.status_code == 201, response.text
        account = response.json()["account"]
        assert account["has_staff_record"] is True
        assert account["staff_id"] is None
        assert account["staff_department"] == "Faculty of Engineering"
        assert account["staff_title"] == "Lecturer"

        staff = db_session.query(Staff).filter(Staff.user_id == account["id"]).first()
        assert staff is not None
        assert staff.staff_id is None
        assert staff.department == "Faculty of Engineering"

    def test_role_change_requires_reason_and_preserves_staff_profile(self, client):
        _login(client, "admin@school.portal")
        account_id = _create_account(client, roles=["STUDENT"]).json()["account"]["id"]

        missing_reason = client.patch(
            f"{API}/users/{account_id}/roles", json={"roles": ["TEACHER"]}
        )
        assert missing_reason.status_code == 422
        assert missing_reason.json()["error"]["code"] == "ROLE_CHANGE_REASON_REQUIRED"

        promoted = client.patch(
            f"{API}/users/{account_id}/roles",
            json={"roles": ["TEACHER"], "reason": "Approved teaching appointment"},
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["has_staff_record"] is True
        staff_record_id = promoted.json()["staff_record_id"]

        changed = client.patch(
            f"{API}/users/{account_id}/roles",
            json={"roles": ["MANAGEMENT"], "reason": "Moved to operations"},
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["staff_record_id"] == staff_record_id

        audit = client.get(
            f"{API}/audit",
            params={"action": "account.roles_changed", "entity_id": account_id},
        )
        assert audit.status_code == 200
        entry = audit.json()["items"][0]
        assert entry["context"]["from"] == ["TEACHER"]
        assert entry["context"]["to"] == ["MANAGEMENT"]
        assert entry["context"]["reason"] == "Moved to operations"

    def test_management_still_cannot_assign_admin(self, client):
        _login(client, "management@school.portal")
        account_id = _create_account(client, roles=["STUDENT"]).json()["account"]["id"]
        response = client.patch(
            f"{API}/users/{account_id}/roles",
            json={"roles": ["ADMIN"], "reason": "Unauthorized escalation"},
        )
        assert response.status_code == 403


def _new_student_account(db_session, tag: str):
    user = User(
        email=f"{_unique(tag)}@example.com",
        username=_unique(tag),
        hashed_password=hash_password("password123"),
        full_name=f"Second {tag}",
        is_active=True,
    )
    role = db_session.query(Role).filter(Role.name == "STUDENT").first()
    assert role is not None
    user.roles.append(role)
    db_session.add(user)
    db_session.flush()
    student = Student(
        user_id=user.id,
        student_id=_unique("GOV"),
        first_name="Second",
        last_name=tag,
    )
    db_session.add(student)
    db_session.commit()
    return user


class TestDocumentGovernance:
    def test_review_lifecycle_and_accepted_immutability(self, client, db_session):
        _login(client, "admin@school.portal")
        uploaded = _upload(client, "Passport evidence")
        assert uploaded.status_code == 201, uploaded.text
        document_id = uploaded.json()["id"]
        assert uploaded.json()["review_status"] == "PENDING"

        under_review = client.post(
            f"{API}/documents/{document_id}/review",
            json={"decision": "UNDER_REVIEW"},
        )
        assert under_review.status_code == 200
        assert under_review.json()["review_status"] == "UNDER_REVIEW"

        accepted = client.post(
            f"{API}/documents/{document_id}/review",
            json={"decision": "APPROVED", "note": "Passport checked against original"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["review_status"] == "APPROVED"

        second_decision = client.post(
            f"{API}/documents/{document_id}/review",
            json={"decision": "REJECTED", "note": "Changed my mind"},
        )
        assert second_decision.status_code == 409
        assert (
            second_decision.json()["error"]["code"] == "INVALID_REVIEW_TRANSITION"
        )

        archived = client.delete(f"{API}/documents/{document_id}")
        assert archived.status_code == 409
        assert archived.json()["error"]["code"] == "ACCEPTED_DOCUMENT_IMMUTABLE"
        assert client.get(f"{API}/documents/{document_id}/download").status_code == 200

        replacement = client.post(
            f"{API}/documents/{document_id}/replace",
            files={"file": ("renewed.pdf", io.BytesIO(PDF), "application/pdf")},
            data={"title": "Renewed passport"},
        )
        assert replacement.status_code == 201, replacement.text
        assert replacement.json()["review_status"] == "PENDING"
        assert replacement.json()["id"] != document_id

        previous = client.get(f"{API}/documents/{document_id}").json()
        assert previous["superseded_by_id"] == replacement.json()["id"]
        assert previous["review_status"] == "APPROVED"

        # A superseded version remains downloadable and its bytes are unchanged.
        assert client.get(f"{API}/documents/{document_id}/download").content == PDF

        old = db_session.query(Document).filter(Document.id == document_id).first()
        new = (
            db_session.query(Document)
            .filter(Document.id == replacement.json()["id"])
            .first()
        )
        assert old is not None and new is not None
        assert old.object_key != new.object_key
        assert old.review_status == DocumentReviewStatus.APPROVED

    def test_replacement_requires_reason(self, client):
        _login(client, "admin@school.portal")
        document_id = _upload(client, "Needs replacement").json()["id"]
        response = client.post(
            f"{API}/documents/{document_id}/review",
            json={"decision": "REPLACEMENT_REQUIRED"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "REPLACEMENT_REASON_REQUIRED"

    def test_teacher_has_no_document_or_immigration_access(self, client):
        _login(client, "teacher@school.portal")
        assert client.get(f"{API}/documents").status_code == 403

        db = SessionLocal()
        try:
            student = db.query(Student).first()
            student_id = str(student.id)
        finally:
            db.close()
        assert client.get(f"{API}/documents/students/{student_id}/summary").status_code == 403
        assert client.get(f"{API}/students/{student_id}/immigration").status_code == 403


class TestImmigrationProvenance:
    def test_student_submission_does_not_verify_or_change_official_data(
        self, client, db_session
    ):
        student = db_session.query(Student).filter(Student.student_id == "STU-001").first()
        assert student is not None
        profile = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        if profile is None:
            profile = ImmigrationProfile(student_id=student.id)
            db_session.add(profile)
        profile.passport_number = "OFFICIAL-OLD"
        profile.verification_status = "UNVERIFIED"
        db_session.commit()

        _login(client, "student@school.portal")
        submitted = client.post(
            f"{API}/students/{student.id}/immigration/change-requests",
            json={
                "change_type": "PASSPORT",
                "proposed_data": {"passport_number": "STUDENT-PROPOSED"},
            },
        )
        assert submitted.status_code == 201, submitted.text

        db_session.expire_all()
        profile = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        assert profile is not None
        assert profile.passport_number == "OFFICIAL-OLD"
        assert profile.verification_status == "UNVERIFIED"

        client.post(f"{API}/auth/logout")
        _login(client, "management@school.portal")
        approved = client.post(
            f"{API}/immigration/change-requests/{submitted.json()['id']}/approve"
        )
        assert approved.status_code == 200, approved.text

        db_session.expire_all()
        verified = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        assert verified is not None
        assert verified.passport_number == "STUDENT-PROPOSED"
        assert verified.verification_status == "VERIFIED"
        assert verified.data_source == "STUDENT"

    def test_student_cannot_propose_verification_or_ownership_fields(self, client):
        student = SessionLocal().query(Student).filter(Student.student_id == "STU-001").first()
        assert student is not None
        _login(client, "student@school.portal")
        response = client.post(
            f"{API}/students/{student.id}/immigration/change-requests",
            json={
                "change_type": "PASSPORT",
                "proposed_data": {
                    "passport_number": "PROPOSED",
                    "verification_status": "VERIFIED",
                },
            },
        )
        assert response.status_code == 422

    def test_document_acceptance_does_not_verify_immigration(self, client, db_session):
        student = db_session.query(Student).filter(Student.student_id == "STU-001").first()
        assert student is not None
        profile = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        if profile is None:
            profile = ImmigrationProfile(student_id=student.id)
            db_session.add(profile)
        profile.passport_number = "DOC-UNCHANGED"
        profile.verification_status = "UNVERIFIED"
        db_session.commit()

        _login(client, "admin@school.portal")
        document_id = _upload(client, "Passport copy").json()["id"]
        accepted = client.post(
            f"{API}/documents/{document_id}/review",
            json={"decision": "APPROVED"},
        )
        assert accepted.status_code == 200, accepted.text

        db_session.expire_all()
        unchanged = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        assert unchanged is not None
        assert unchanged.passport_number == "DOC-UNCHANGED"
        assert unchanged.verification_status == "UNVERIFIED"

    def test_eicar_upload_is_rejected_before_storage(self, client):
        _login(client, "admin@school.portal")
        response = _upload(client, "Infected file", PDF + EICAR)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MALWARE_DETECTED"

    def test_unscanned_document_cannot_enter_review(self, client, db_session):
        _login(client, "admin@school.portal")
        document_id = _upload(client, "Legacy unscanned").json()["id"]
        row = db_session.query(Document).filter(Document.id == document_id).first()
        assert row is not None
        row.scan_status = DocumentScanStatus.LEGACY_UNSCANNED
        db_session.commit()

        blocked = client.post(
            f"{API}/documents/{document_id}/review",
            json={"decision": "UNDER_REVIEW"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "DOCUMENT_NOT_SCANNED"

    def test_preview_is_authorized_and_streams_inline(self, client):
        assert client.get(
            f"{API}/documents/00000000-0000-0000-0000-000000000000/preview"
        ).status_code == 401

        _login(client, "admin@school.portal")
        document_id = _upload(client, "Previewable").json()["id"]
        preview = client.get(f"{API}/documents/{document_id}/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "application/pdf"
        assert preview.headers["content-disposition"].startswith("inline;")
        assert preview.headers["x-content-type-options"] == "nosniff"

    def test_preview_authorization_for_owner_other_student_and_teacher(
        self, client, db_session
    ):
        second_user = _new_student_account(db_session, "preview")
        first = db_session.query(Student).filter(Student.student_id == "STU-001").first()
        assert first is not None

        _login(client, "admin@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={"file": ("visible.pdf", io.BytesIO(PDF), "application/pdf")},
            data={
                "document_type": "OTHER",
                "title": "Owner preview",
                "student_id": str(first.id),
                "student_visible": "true",
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        document_id = uploaded.json()["id"]

        client.post(f"{API}/auth/logout")
        _login(client, second_user.email)
        denied_other = client.get(f"{API}/documents/{document_id}/preview")
        assert denied_other.status_code == 404

        client.post(f"{API}/auth/logout")
        _login(client, "teacher@school.portal")
        denied_teacher = client.get(f"{API}/documents/{document_id}/preview")
        assert denied_teacher.status_code in (403, 404)

        client.post(f"{API}/auth/logout")
        _login(client, "student@school.portal")
        allowed_owner = client.get(f"{API}/documents/{document_id}/preview")
        assert allowed_owner.status_code == 200
        assert allowed_owner.content == PDF

    def test_image_preview_returns_image_headers(self, client):
        _login(client, "admin@school.portal")
        uploaded = client.post(
            f"{API}/documents",
            files={"file": ("photo.png", io.BytesIO(PNG), "image/png")},
            data={"document_type": "PHOTO", "title": "Preview image"},
        )
        assert uploaded.status_code == 201, uploaded.text
        preview = client.get(f"{API}/documents/{uploaded.json()['id']}/preview")
        assert preview.status_code == 200
        assert preview.headers["content-type"] == "image/png"
        assert preview.headers["content-disposition"].startswith("inline;")
        assert preview.headers["cache-control"] == "private, no-store"
        assert preview.content == PNG

    def test_unsupported_type_refuses_inline_preview(self, client, db_session):
        _login(client, "admin@school.portal")
        document_id = _upload(client, "Unsafe type").json()["id"]
        row = db_session.query(Document).filter(Document.id == document_id).first()
        assert row is not None
        row.content_type = "text/html"
        db_session.commit()

        preview = client.get(f"{API}/documents/{document_id}/preview")
        assert preview.status_code == 415
        assert preview.json()["error"]["code"] == "PREVIEW_UNSUPPORTED"

    def test_missing_storage_object_cannot_be_approved(self, client, db_session):
        _login(client, "admin@school.portal")
        document_id = _upload(client, "Missing object").json()["id"]
        row = db_session.query(Document).filter(Document.id == document_id).first()
        assert row is not None
        get_storage().delete(row.object_key)

        review = client.post(
            f"{API}/documents/{document_id}/review",
            json={"decision": "APPROVED"},
        )
        assert review.status_code == 409
        assert review.json()["error"]["code"] == "DOCUMENT_FILE_MISSING"

        db_session.expire_all()
        unchanged = db_session.query(Document).filter(Document.id == document_id).first()
        assert unchanged is not None
        assert unchanged.review_status == DocumentReviewStatus.PENDING

    def test_rejected_upload_leaves_no_pending_record(self, client, db_session):
        _login(client, "admin@school.portal")
        title = _unique("Infected")
        response = _upload(client, title, PDF + EICAR)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MALWARE_DETECTED"
        assert (
            db_session.query(Document).filter(Document.title == title).first()
            is None
        )

    def test_import_cannot_overwrite_verified_difference(self, client):
        _login(client, "admin@school.portal")
        db = SessionLocal()
        try:
            student = db.query(Student).first()
            admin = db.query(User).filter(User.email == "admin@school.portal").first()
            assert student is not None and admin is not None
            student_id = student.id
            admin_id = admin.id
        finally:
            db.close()

        db = SessionLocal()
        try:
            profile = db.query(ImmigrationProfile).filter(
                ImmigrationProfile.student_id == student_id
            ).first()
            if profile is None:
                profile = ImmigrationProfile(student_id=student_id)
                db.add(profile)
                db.commit()
                db.refresh(profile)

            # Leave one field genuinely empty so the import has a permitted
            # blank to fill; a verified non-empty field is conflict-only.
            profile.residence_permit_number = None
            db.commit()

            update_immigration_profile(
                db,
                profile,
                {
                    "passport_number": "OFFICIAL-001",
                    "visa_type": "STUDENT",
                },
                actor_id=admin_id,
                reason="Verified against original passport",
                data_source="MANAGEMENT",
            )

            imported, conflicts, changed = import_immigration_profile(
                db,
                student_id=student_id,
                data={
                    "passport_number": "IMPORTED-DIFFERENT",
                    "visa_type": "STUDENT",
                    "residence_permit_number": "RP-IMPORTED-1",
                },
                source_reference="SCU-import-batch-1",
                actor_id=admin_id,
            )

            assert conflicts == ["passport_number"]
            assert imported.passport_number == "OFFICIAL-001"
            assert imported.residence_permit_number == "RP-IMPORTED-1"
            # Applying new imported data must not quietly certify the profile.
            assert imported.verification_status == "UNVERIFIED"
            assert imported.data_source == "IMPORT"
            assert imported.source_reference == "SCU-import-batch-1"
            # One permitted blank was filled, so the call changed the record.
            assert changed is True
        finally:
            db.close()

    def test_import_preview_requires_confirmation_and_remains_unverified(
        self, client, db_session
    ):
        student = db_session.query(Student).filter(Student.student_id == "STU-001").first()
        assert student is not None
        profile = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        if profile is None:
            profile = ImmigrationProfile(student_id=student.id)
            db_session.add(profile)
        profile.passport_number = None
        profile.verification_status = "UNVERIFIED"
        db_session.commit()

        _login(client, "admin@school.portal")
        records = [
            {
                "student_id": str(student.id),
                "values": {"passport_number": "IMPORT-ONLY"},
            }
        ]
        payload = {"source_reference": "test-batch-1", "records": records}
        preview = client.post(f"{API}/immigration/import/preview", json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()["applyable"] == 1
        assert preview.json()["invalid"] == 0

        db_session.expire_all()
        unchanged = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        assert unchanged is not None
        assert unchanged.passport_number is None
        assert unchanged.verification_status == "UNVERIFIED"

        unconfirmed = client.post(f"{API}/immigration/import/apply", json=payload)
        assert unconfirmed.status_code == 422
        assert unconfirmed.json()["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"

        applied = client.post(
            f"{API}/immigration/import/apply",
            json={**payload, "confirm": True},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] == 1

        db_session.expire_all()
        imported = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        assert imported is not None
        assert imported.passport_number == "IMPORT-ONLY"
        assert imported.verification_status == "UNVERIFIED"
        assert imported.data_source == "IMPORT"

    def test_a_matching_reimport_is_a_noop_and_never_demotes_official_data(
        self, client, db_session
    ):
        """Re-importing what the institution already holds changes nothing.

        An import fills blanks. It must not "re-apply" a value that is already
        identical, and it must not demote a verified record as a side effect:
        a batch that matches the official data is reported as applied=0 and
        leaves the verification, the source and the history untouched.
        """
        student = db_session.query(Student).filter(Student.student_id == "STU-001").first()
        assert student is not None
        profile = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        if profile is None:
            profile = ImmigrationProfile(student_id=student.id)
            db_session.add(profile)
        profile.passport_number = "OFFICIAL-NOOP"
        profile.visa_type = "X1"
        profile.verification_status = "VERIFIED"
        profile.data_source = "STAFF"
        profile.source_reference = "staff-file-2026"
        db_session.commit()

        _login(client, "admin@school.portal")
        payload = {
            "source_reference": "reimport-batch",
            "records": [
                {
                    "student_id": str(student.id),
                    "values": {"passport_number": "OFFICIAL-NOOP", "visa_type": "X1"},
                }
            ],
        }
        applied = client.post(
            f"{API}/immigration/import/apply",
            json={**payload, "confirm": True},
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["applied"] == 0
        assert applied.json()["skipped"] == 1

        db_session.expire_all()
        reread = (
            db_session.query(ImmigrationProfile)
            .filter(ImmigrationProfile.student_id == student.id)
            .first()
        )
        assert reread is not None
        assert reread.verification_status == "VERIFIED"
        assert reread.data_source == "STAFF"
        assert reread.source_reference == "staff-file-2026"
