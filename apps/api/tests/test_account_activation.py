"""Account activation for migrated students.

These tests exercise the security properties the migration depends on: a
provisioned account has no password, only a single-use token can establish one,
the token expires and is spent once, re-issue requires identity verification,
and no credential ever appears in a report.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

VALID_HEADER = "student_id,first_name,last_name,email\n"
STRONG_PASSWORD = "CorrectHorse9!Battery"


def _login(client, email="admin@school.portal", password="password123"):
    response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response


def _logout(client):
    client.post("/api/v1/auth/logout")


def _import_student(client, db_session):
    """Import one synthetic student and return (number, email, user, token_row)."""
    from app.models.identity import Student
    from app.models.session import AccountActivationToken

    number = f"ACT-{uuid.uuid4().hex[:10].upper()}"
    email = f"{number.lower()}@example.com"
    response = client.post(
        "/api/v1/students/import",
        params={"dry_run": False, "skip_invalid": False},
        files={
            "file": (
                "students.csv",
                (VALID_HEADER + f"{number},Ada,Activation,{email}\n").encode(),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1, response.text

    db_session.expire_all()
    student = db_session.query(Student).filter(Student.student_id == number).first()
    assert student is not None
    token = (
        db_session.query(AccountActivationToken)
        .filter(AccountActivationToken.user_id == student.user_id)
        .first()
    )
    assert token is not None
    return number, email, student.user, token


def _raw_token_for(db_session, user) -> str:
    """Test-only: mint a token through the service so the raw value is known."""
    from app.auth.activation import issue_activation

    _, raw = issue_activation(
        db_session, user, reason="MIGRATION", delivery="ADMIN_COUNTER"
    )
    db_session.commit()
    return raw


class TestProvisionedAccount:
    def test_imported_account_has_no_password_and_no_readable_credential(
        self, client, db_session
    ):
        _login(client)
        number, email, user, token = _import_student(client, db_session)

        assert user.activation_required is True
        assert user.hashed_password == "!"
        assert user.must_change_password is False
        assert user.activated_at is None
        assert token.delivery == "MIGRATION_PENDING"
        # The report is the thing that gets emailed around: it must not carry
        # the token, its hash, or any password.
        report = client.get("/api/v1/users/migration/account-report").json()
        serialized = str(report)
        assert token.token_hash not in serialized
        assert "temporary_password" not in serialized
        assert email not in serialized

    def test_login_is_refused_until_activation(self, client, db_session):
        _login(client)
        _, email, _user, _token = _import_student(client, db_session)
        _logout(client)

        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "anything-at-all-1!"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "ACCOUNT_NOT_ACTIVATED"


class TestActivationLink:
    def test_preview_masks_the_address(self, client, db_session):
        _login(client)
        _, email, user, _token = _import_student(client, db_session)
        raw = _raw_token_for(db_session, user)

        preview = client.get(f"/api/v1/auth/activation/{raw}")
        assert preview.status_code == 200
        body = preview.json()
        assert body["state"] == "VALID"
        assert body["email_masked"] != email
        assert body["email_masked"].endswith(email.split("@", 1)[1])
        assert "expires_at" in body

    def test_activation_establishes_the_students_own_password(self, client, db_session):
        _login(client)
        _, email, user, _token = _import_student(client, db_session)
        raw = _raw_token_for(db_session, user)

        response = client.post(
            "/api/v1/auth/activation",
            json={"token": raw, "new_password": STRONG_PASSWORD},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {"activated": True, "email": email}

        db_session.expire_all()
        db_session.refresh(user)
        assert user.activation_required is False
        assert user.activated_at is not None

        _logout(client)
        signed_in = client.post(
            "/api/v1/auth/login", json={"email": email, "password": STRONG_PASSWORD}
        )
        assert signed_in.status_code == 200, signed_in.text

    def test_token_is_single_use(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        raw = _raw_token_for(db_session, user)

        first = client.post(
            "/api/v1/auth/activation",
            json={"token": raw, "new_password": STRONG_PASSWORD},
        )
        assert first.status_code == 200

        second = client.post(
            "/api/v1/auth/activation",
            json={"token": raw, "new_password": "AnotherStrong1!Pass"},
        )
        assert second.status_code == 404
        assert second.json()["error"]["code"] == "INVALID_ACTIVATION_TOKEN"

        preview = client.get(f"/api/v1/auth/activation/{raw}")
        assert preview.json()["state"] == "USED"

    def test_expired_link_is_refused_and_reported_as_expired(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        raw = _raw_token_for(db_session, user)

        from app.models.session import AccountActivationToken

        record = (
            db_session.query(AccountActivationToken)
            .filter(
                AccountActivationToken.user_id == user.id,
                AccountActivationToken.used_at.is_(None),
            )
            .first()
        )
        record.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db_session.commit()

        preview = client.get(f"/api/v1/auth/activation/{raw}")
        assert preview.json()["state"] == "EXPIRED"

        response = client.post(
            "/api/v1/auth/activation",
            json={"token": raw, "new_password": STRONG_PASSWORD},
        )
        assert response.status_code == 404

    def test_weak_password_is_rejected_before_the_token_is_spent(
        self, client, db_session
    ):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        raw = _raw_token_for(db_session, user)

        response = client.post(
            "/api/v1/auth/activation",
            json={"token": raw, "new_password": "short"},
        )
        assert response.status_code == 422

        preview = client.get(f"/api/v1/auth/activation/{raw}")
        assert preview.json()["state"] == "VALID"


class TestAdministrativeActivation:
    def test_issue_requires_identity_verification(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)

        refused = client.post(f"/api/v1/users/{user.id}/activation", json={})
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "IDENTITY_VERIFICATION_REQUIRED"

        issued = client.post(
            f"/api/v1/users/{user.id}/activation",
            json={
                "identity_verified": True,
                "verification_reference": "PASSPORT-7781",
            },
        )
        assert issued.status_code == 200, issued.text
        body = issued.json()
        assert body["state"] == "PENDING"
        assert body["activation_url"]  # development channel returns the link
        assert "token=" in body["activation_url"]

        # The link works, and the audit entry exists without the token.
        from app.models.audit import AuditLog

        entries = (
            db_session.query(AuditLog)
            .filter(AuditLog.action == "account.activation_issued")
            .all()
        )
        assert entries
        raw = body["activation_url"].split("token=", 1)[1]
        for entry in entries:
            assert raw not in str(entry.context)
            assert raw not in str(entry.action)

    def test_reissue_invalidates_the_previous_link(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        first = _raw_token_for(db_session, user)

        second_body = client.post(
            f"/api/v1/users/{user.id}/activation",
            json={"identity_verified": True, "verification_reference": "ID-1"},
        ).json()
        second = second_body["activation_url"].split("token=", 1)[1]

        assert client.get(f"/api/v1/auth/activation/{first}").json()["state"] == "UNKNOWN"
        assert client.get(f"/api/v1/auth/activation/{second}").json()["state"] == "VALID"

    def test_revoke_withdraws_the_link(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        body = client.post(
            f"/api/v1/users/{user.id}/activation",
            json={"identity_verified": True, "verification_reference": "ID-2"},
        ).json()
        raw = body["activation_url"].split("token=", 1)[1]

        revoked = client.delete(f"/api/v1/users/{user.id}/activation")
        assert revoked.status_code == 204
        assert client.get(f"/api/v1/auth/activation/{raw}").json()["state"] == "UNKNOWN"

    def test_completing_activation_drops_sessions_from_before_it(
        self, client, db_session
    ):
        _login(client)
        _, email, user, _token = _import_student(client, db_session)
        body = client.post(
            f"/api/v1/users/{user.id}/activation",
            json={"identity_verified": True, "verification_reference": "ID-3"},
        ).json()
        raw = body["activation_url"].split("token=", 1)[1]

        assert client.post(
            "/api/v1/auth/activation",
            json={"token": raw, "new_password": STRONG_PASSWORD},
        ).status_code == 200

        # Now re-issue on the activated account: old password and session must
        # stop working until the new link is completed.
        _logout(client)
        assert client.post(
            "/api/v1/auth/login", json={"email": email, "password": STRONG_PASSWORD}
        ).status_code == 200

        _logout(client)
        _login(client)
        again = client.post(
            f"/api/v1/users/{user.id}/activation",
            json={"identity_verified": True, "verification_reference": "ID-4"},
        ).json()
        raw_again = again["activation_url"].split("token=", 1)[1]

        _logout(client)
        blocked = client.post(
            "/api/v1/auth/login", json={"email": email, "password": STRONG_PASSWORD}
        )
        assert blocked.status_code == 403

        strict = client.post(
            "/api/v1/auth/activation",
            json={"token": raw_again, "new_password": "NewStrong1!Pass"},
        )
        assert strict.status_code == 200
        assert client.post(
            "/api/v1/auth/login", json={"email": email, "password": "NewStrong1!Pass"}
        ).status_code == 200

    def test_disabled_account_cannot_be_issued_an_activation(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        user.is_active = False
        db_session.commit()

        response = client.post(
            f"/api/v1/users/{user.id}/activation",
            json={"identity_verified": True, "verification_reference": "ID-5"},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ACCOUNT_DISABLED"


class TestActivationAuthorization:
    def test_student_cannot_issue_or_read_activation_state(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        _logout(client)

        _login(client, "student@school.portal")
        assert client.post(
            f"/api/v1/users/{user.id}/activation", json={"identity_verified": True}
        ).status_code == 403
        assert client.get(f"/api/v1/users/{user.id}/activation").status_code == 403
        assert client.get("/api/v1/users/migration/account-report").status_code == 403

    def test_teacher_cannot_issue_activation(self, client, db_session):
        _login(client)
        _, _email, user, _token = _import_student(client, db_session)
        _logout(client)

        _login(client, "teacher@school.portal")
        assert client.post(
            f"/api/v1/users/{user.id}/activation", json={"identity_verified": True}
        ).status_code == 403

    def test_management_can_activate_a_student_but_not_an_administrator(
        self, client, db_session
    ):
        from app.models.identity import User

        _login(client)
        _, _email, student_user, _token = _import_student(client, db_session)
        admin = (
            db_session.query(User)
            .filter(User.email == "admin@school.portal")
            .first()
        )
        _logout(client)

        _login(client, "management@school.portal")
        allowed = client.post(
            f"/api/v1/users/{student_user.id}/activation",
            json={"identity_verified": True, "verification_reference": "ID-6"},
        )
        assert allowed.status_code == 200, allowed.text

        refused = client.post(
            f"/api/v1/users/{admin.id}/activation",
            json={"identity_verified": True, "verification_reference": "ID-7"},
        )
        assert refused.status_code == 403


class TestMigrationReport:
    def test_report_counts_and_excludes_credentials(self, client, db_session):
        _login(client)
        _, email, user, token = _import_student(client, db_session)

        report = client.get("/api/v1/users/migration/account-report").json()
        assert report["totals"]["students"] >= 1
        assert report["totals"]["accounts"] >= 1
        assert report["totals"]["activation_pending"] >= 1
        assert report["excludes"] == [
            "passwords",
            "activation_tokens",
            "raw_email_addresses",
        ]

        serialized = str(report)
        assert token.token_hash not in serialized
        assert token.token_hash[:12] not in serialized
        assert STRONG_PASSWORD not in serialized
        assert email not in serialized
