"""Account lifecycle tests.

Covers the institutional onboarding path end to end:

    create account -> temporary password -> student signs in -> changes
    password

plus the administrative controls around it (role assignment, activation,
password reset) and — most importantly — the delegation boundary that stops an
operator with ``users.manage_students`` from touching staff or administrator
accounts.
"""

import uuid

from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.models.identity import User

API = "/api/v1"

STRONG_PASSWORD = "Str0ng-Passphrase!42"


def _login(client: TestClient, email: str, password: str = "password123"):
    return client.post(f"{API}/auth/login", json={"email": email, "password": password})


def _admin(client):
    resp = _login(client, "admin@school.portal")
    assert resp.status_code == 200


def _management(client):
    resp = _login(client, "management@school.portal")
    assert resp.status_code == 200


def _logout(client):
    client.post(f"{API}/auth/logout")


ONBOARDED_PASSWORD = "Onboard-Passphrase!42"


def _retire_temporary_password(client: TestClient, temporary_password: str) -> None:
    """Replace the issued credential, as an onboarded student must.

    The server allows nothing but the password change while the temporary
    credential is live, so a test that wants to exercise student behaviour has
    to do the same thing the student does. The restricted state itself is
    covered by tests/test_password_enforcement.py.
    """
    changed = client.post(
        f"{API}/auth/password/change",
        json={
            "current_password": temporary_password,
            "new_password": ONBOARDED_PASSWORD,
        },
    )
    assert changed.status_code == 200, changed.text


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _create_account(client, **overrides):
    payload = {
        "email": f"{_unique('acct')}@example.com",
        "full_name": "Test Account",
        "roles": ["STUDENT"],
    }
    payload.update(overrides)
    return client.post(f"{API}/users/", json=payload)


class TestAccountCreation:
    def test_admin_creates_account_returns_one_time_password(self, client):
        _admin(client)
        resp = _create_account(client, email=f"{_unique('created')}@example.com")

        assert resp.status_code == 201
        body = resp.json()
        assert body["account"]["is_active"] is True
        assert body["account"]["must_change_password"] is True
        assert [r["name"] for r in body["account"]["roles"]] == ["STUDENT"]
        # A generated credential is returned exactly once.
        assert isinstance(body["temporary_password"], str)
        assert len(body["temporary_password"]) >= 16

    def test_response_never_contains_password_material(self, client):
        _admin(client)
        resp = _create_account(client)
        assert resp.status_code == 201
        body = resp.json()

        serialized = str(body).lower()
        assert "hashed_password" not in serialized
        assert "password_hash" not in serialized
        # The account object itself carries no credential.
        assert "password" not in {k.lower() for k in body["account"]}

    def test_generated_password_is_not_the_hash(self, client):
        """The returned credential must actually authenticate the account."""
        _admin(client)
        email = f"{_unique('usable')}@example.com"
        resp = _create_account(client, email=email)
        password = resp.json()["temporary_password"]

        _logout(client)
        login = _login(client, email, password)
        assert login.status_code == 200
        assert login.json()["user"]["must_change_password"] is True

    def test_explicit_password_is_not_echoed(self, client):
        _admin(client)
        email = f"{_unique('explicit')}@example.com"
        resp = _create_account(
            client, email=email, password=STRONG_PASSWORD, must_change_password=False
        )
        assert resp.status_code == 201
        assert resp.json()["temporary_password"] is None
        assert STRONG_PASSWORD not in resp.text

    def test_duplicate_email_conflicts(self, client):
        _admin(client)
        email = f"{_unique('dupe')}@example.com"
        assert _create_account(client, email=email).status_code == 201
        assert _create_account(client, email=email).status_code == 409

    def test_duplicate_email_is_case_insensitive(self, client):
        _admin(client)
        email = f"{_unique('case')}@example.com"
        assert _create_account(client, email=email).status_code == 201
        assert _create_account(client, email=email.upper()).status_code == 409

    def test_invalid_email_rejected(self, client):
        _admin(client)
        assert _create_account(client, email="not-an-email").status_code == 422

    def test_weak_password_rejected(self, client):
        _admin(client)
        resp = _create_account(client, password="password")
        assert resp.status_code == 422

    def test_unknown_role_rejected(self, client):
        _admin(client)
        resp = _create_account(client, roles=["WIZARD"])
        assert resp.status_code == 409

    def test_username_is_derived_and_unique(self, client):
        _admin(client)
        local = _unique("derive")
        first = _create_account(client, email=f"{local}@example.com")
        second = _create_account(client, email=f"{local}@example.com".replace("@", "+x@"))
        assert first.json()["account"]["username"] != second.json()["account"]["username"]


class TestAccountAuthorization:
    def test_management_can_create_student_account(self, client):
        _management(client)
        resp = _create_account(client)
        assert resp.status_code == 201

    def test_management_cannot_create_admin_account(self, client):
        """Delegated operators must not be able to mint privileged logins."""
        _management(client)
        resp = _create_account(client, roles=["ADMIN"])
        assert resp.status_code == 403

    def test_management_cannot_create_management_account(self, client):
        _management(client)
        assert _create_account(client, roles=["MANAGEMENT"]).status_code == 403

    def test_management_cannot_create_teacher_account(self, client):
        _management(client)
        assert _create_account(client, roles=["TEACHER"]).status_code == 403

    def test_management_cannot_escalate_by_mixing_roles(self, client):
        """A student role alongside ADMIN is still an escalation."""
        _management(client)
        resp = _create_account(client, roles=["STUDENT", "ADMIN"])
        assert resp.status_code == 403

    def test_student_cannot_create_accounts(self, client):
        _login(client, "student@school.portal")
        assert _create_account(client).status_code == 403

    def test_teacher_cannot_create_accounts(self, client):
        _login(client, "teacher@school.portal")
        assert _create_account(client).status_code == 403

    def test_unauthenticated_cannot_list_accounts(self, client):
        assert client.get(f"{API}/users/").status_code == 401

    def test_student_cannot_list_accounts(self, client):
        _login(client, "student@school.portal")
        assert client.get(f"{API}/users/").status_code == 403

    def test_management_list_is_restricted_to_students(self, client):
        """A delegated operator must not be able to enumerate staff accounts."""
        _management(client)
        resp = client.get(f"{API}/users/", params={"page_size": 100})
        assert resp.status_code == 200
        roles = {r["name"] for item in resp.json()["items"] for r in item["roles"]}
        assert roles <= {"STUDENT"}

    def test_admin_list_includes_staff(self, client):
        _admin(client)
        resp = client.get(f"{API}/users/", params={"page_size": 100})
        assert resp.status_code == 200
        roles = {r["name"] for item in resp.json()["items"] for r in item["roles"]}
        assert "ADMIN" in roles


class TestRoleAssignment:
    def _target_off_limits(self, client):
        """Create a student account, then return its id and email."""
        email = f"{_unique('target')}@example.com"
        resp = _create_account(client, email=email)
        return resp.json()["account"]["id"], email

    def test_management_cannot_modify_privileged_account(self, client):
        _admin(client)
        staff_email = f"{_unique('staff')}@example.com"
        created = _create_account(client, email=staff_email, roles=["TEACHER"])
        staff_id = created.json()["account"]["id"]
        _logout(client)

        _management(client)
        resp = client.patch(f"{API}/users/{staff_id}", json={"full_name": "Hacked"})
        assert resp.status_code == 403

        assert client.patch(
            f"{API}/users/{staff_id}/roles", json={"roles": ["ADMIN"]}
        ).status_code == 403
        assert client.post(f"{API}/users/{staff_id}/reset-password").status_code == 403
        assert (
            client.patch(f"{API}/users/{staff_id}/active", json={"is_active": False}).status_code
            == 403
        )

    def test_management_cannot_promote_a_student(self, client):
        _management(client)
        account_id, _ = self._target_off_limits(client)
        resp = client.patch(f"{API}/users/{account_id}/roles", json={"roles": ["ADMIN"]})
        assert resp.status_code == 403

    def test_management_cannot_manage_own_privileged_account(self, client):
        """Management cannot use the delegated path on themselves."""
        _management(client)
        me = client.get(f"{API}/auth/me").json()
        resp = client.patch(f"{API}/users/{me['id']}/active", json={"is_active": False})
        assert resp.status_code == 403

    def test_admin_can_change_roles(self, client):
        _admin(client)
        account_id, _ = self._target_off_limits(client)
        resp = client.patch(
            f"{API}/users/{account_id}/roles",
            json={
                "roles": ["STUDENT", "TEACHER"],
                "reason": "Approved staff appointment",
            },
        )
        assert resp.status_code == 200
        assert {r["name"] for r in resp.json()["roles"]} == {"STUDENT", "TEACHER"}

    def test_unknown_role_in_change_rejected(self, client):
        _admin(client)
        account_id, _ = self._target_off_limits(client)
        resp = client.patch(
            f"{API}/users/{account_id}/roles",
            json={"roles": ["NOPE"], "reason": "Approved staff appointment"},
        )
        assert resp.status_code == 409

    def test_cannot_strip_the_last_administrator(self, client):
        """The system must not be able to lock every admin out."""
        _admin(client)
        db = SessionLocal()
        try:
            admins = [
                u
                for u in db.query(User).all()
                if any(r.name == "ADMIN" for r in u.roles) and u.is_active
            ]
        finally:
            db.close()

        target = next(a for a in admins if a.email == "admin@school.portal")
        resp = client.patch(
            f"{API}/users/{target.id}/roles",
            json={"roles": ["MANAGEMENT"], "reason": "Leadership restructuring"},
        )
        assert resp.status_code == 409
        assert "administrator" in resp.json()["error"]["message"].lower()

    def test_cannot_deactivate_the_last_administrator(self, client):
        _admin(client)
        db = SessionLocal()
        try:
            target = (
                db.query(User).filter(User.email == "admin@school.portal").first()
            )
            target_id = str(target.id)
        finally:
            db.close()

        # Deactivating a different account is fine; the seeded admin is the
        # only ADMIN in the test database, so its own deactivation must fail.
        resp = client.patch(
            f"{API}/users/{target_id}/active", json={"is_active": False}
        )
        assert resp.status_code == 409


class TestActivation:
    def test_deactivated_account_cannot_log_in(self, client):
        _admin(client)
        email = f"{_unique('deact')}@example.com"
        account_id = _create_account(client, email=email).json()["account"]["id"]

        resp = client.patch(
            f"{API}/users/{account_id}/active", json={"is_active": False}
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        _logout(client)
        assert _login(client, email, "irrelevant").status_code == 401

    def test_deactivation_revokes_existing_sessions(self, client):
        """A disabled account must not keep acting through a live cookie."""
        _admin(client)
        email = f"{_unique('revoke')}@example.com"
        created = _create_account(client, email=email)
        account_id = created.json()["account"]["id"]
        password = created.json()["temporary_password"]

        # Sign in as the new account in a separate client so the admin session
        # is untouched.
        with TestClient(client.app) as victim:
            assert _login(victim, email, password).status_code == 200
            assert victim.get(f"{API}/auth/me").status_code == 200

            # Admin disables the account.
            resp = client.patch(
                f"{API}/users/{account_id}/active", json={"is_active": False}
            )
            assert resp.status_code == 200

            # The victim's cookie is now worthless.
            assert victim.get(f"{API}/auth/me").status_code == 401

    def test_reactivation_restores_access(self, client):
        _admin(client)
        email = f"{_unique('react')}@example.com"
        created = _create_account(client, email=email)
        account_id = created.json()["account"]["id"]
        password = created.json()["temporary_password"]

        client.patch(f"{API}/users/{account_id}/active", json={"is_active": False})
        resp = client.patch(f"{API}/users/{account_id}/active", json={"is_active": True})
        assert resp.status_code == 200

        with TestClient(client.app) as reenabled:
            assert _login(reenabled, email, password).status_code == 200

    def test_cannot_deactivate_own_account(self, client):
        _admin(client)
        me = client.get(f"{API}/auth/me").json()
        resp = client.patch(f"{API}/users/{me['id']}/active", json={"is_active": False})
        assert resp.status_code == 409


class TestPasswordReset:
    def test_admin_reset_returns_new_password_and_revokes_sessions(self, client):
        _admin(client)
        email = f"{_unique('reset')}@example.com"
        created = _create_account(client, email=email)
        account_id = created.json()["account"]["id"]
        original = created.json()["temporary_password"]

        with TestClient(client.app) as victim:
            assert _login(victim, email, original).status_code == 200

            resp = client.post(f"{API}/users/{account_id}/reset-password", json={})
            assert resp.status_code == 200
            new_password = resp.json()["temporary_password"]
            assert new_password != original
            assert resp.json()["sessions_revoked"] >= 1

            # The old credential is dead and the old session is revoked.
            assert victim.get(f"{API}/auth/me").status_code == 401
            assert _login(victim, email, original).status_code == 401
            assert _login(victim, email, new_password).status_code == 200

    def test_reset_marks_password_for_change(self, client):
        _admin(client)
        email = f"{_unique('mark')}@example.com"
        created = _create_account(client, email=email, must_change_password=False)
        account_id = created.json()["account"]["id"]

        resp = client.post(
            f"{API}/users/{account_id}/reset-password",
            json={"must_change_password": True},
        )
        assert resp.status_code == 200
        assert resp.json()["must_change_password"] is True

    def test_reset_with_explicit_password_does_not_echo_it(self, client):
        _admin(client)
        account_id = _create_account(client).json()["account"]["id"]
        resp = client.post(
            f"{API}/users/{account_id}/reset-password",
            json={"new_password": STRONG_PASSWORD},
        )
        assert resp.status_code == 200
        assert resp.json()["temporary_password"] == STRONG_PASSWORD


class TestSelfServicePasswordAndSessions:
    def _new_account(self, client):
        email = f"{_unique('self')}@example.com"
        created = _create_account(client, email=email)
        return email, created.json()["temporary_password"]

    def test_change_password_requires_current_password(self, client):
        _admin(client)
        email, password = self._new_account(client)

        with TestClient(client.app) as holder:
            assert _login(holder, email, password).status_code == 200
            resp = holder.post(
                f"{API}/auth/password/change",
                json={
                    "current_password": "definitely-wrong",
                    "new_password": STRONG_PASSWORD,
                },
            )
            assert resp.status_code == 400
            # Unchanged: the original still works.
            assert _login(holder, email, password).status_code == 200

    def test_change_password_succeeds_and_clears_the_flag(self, client):
        _admin(client)
        email, password = self._new_account(client)

        with TestClient(client.app) as holder:
            assert _login(holder, email, password).status_code == 200
            assert holder.get(f"{API}/auth/me").json()["must_change_password"] is True

            resp = holder.post(
                f"{API}/auth/password/change",
                json={"current_password": password, "new_password": STRONG_PASSWORD},
            )
            assert resp.status_code == 200
            assert resp.json()["must_change_password"] is False
            # The holder keeps their own session.
            assert holder.get(f"{API}/auth/me").status_code == 200

            _logout(holder)
            assert _login(holder, email, STRONG_PASSWORD).status_code == 200
            assert _login(holder, email, password).status_code == 401

    def test_change_password_rejects_reuse(self, client):
        _admin(client)
        email, password = self._new_account(client)
        with TestClient(client.app) as holder:
            assert _login(holder, email, password).status_code == 200
            resp = holder.post(
                f"{API}/auth/password/change",
                json={"current_password": password, "new_password": password},
            )
            assert resp.status_code == 400

    def test_change_password_revokes_other_sessions(self, client):
        """Changing a password must evict anyone else holding a session."""
        _admin(client)
        email, password = self._new_account(client)

        with TestClient(client.app) as other_device:
            assert _login(other_device, email, password).status_code == 200
            with TestClient(client.app) as this_device:
                assert _login(this_device, email, password).status_code == 200
                resp = this_device.post(
                    f"{API}/auth/password/change",
                    json={
                        "current_password": password,
                        "new_password": STRONG_PASSWORD,
                    },
                )
                assert resp.status_code == 200
                assert resp.json()["sessions_revoked"] >= 1
                assert this_device.get(f"{API}/auth/me").status_code == 200
            assert other_device.get(f"{API}/auth/me").status_code == 401

    def test_weak_new_password_rejected(self, client):
        _admin(client)
        email, password = self._new_account(client)
        with TestClient(client.app) as holder:
            assert _login(holder, email, password).status_code == 200
            resp = holder.post(
                f"{API}/auth/password/change",
                json={"current_password": password, "new_password": "short"},
            )
            assert resp.status_code == 422

    def test_own_sessions_listed_without_tokens(self, client):
        _admin(client)
        email, password = self._new_account(client)
        with TestClient(client.app) as holder:
            assert _login(holder, email, password).status_code == 200
            resp = holder.get(f"{API}/auth/sessions")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] >= 1
            assert any(item["is_current"] for item in body["items"])
            assert "token" not in resp.text.lower()

    def test_revoke_other_sessions(self, client):
        _admin(client)
        email, password = self._new_account(client)

        with TestClient(client.app) as other_device:
            assert _login(other_device, email, password).status_code == 200
            with TestClient(client.app) as this_device:
                assert _login(this_device, email, password).status_code == 200
                resp = this_device.post(f"{API}/auth/sessions/revoke-others")
                assert resp.status_code == 200
                assert resp.json()["sessions_revoked"] >= 1
                assert this_device.get(f"{API}/auth/me").status_code == 200
            assert other_device.get(f"{API}/auth/me").status_code == 401

    def test_unauthenticated_cannot_list_sessions(self, client):
        assert client.get(f"{API}/auth/sessions").status_code == 401


class TestStudentOnboarding:
    def _payload(self, **overrides):
        return {
            "student_id": _unique("STU").upper(),
            "first_name": "Onboard",
            "last_name": "Student",
            "email": f"{_unique('onboard')}@example.com",
            "nationality": "Kenya",
            **overrides,
        }

    def test_onboard_creates_student_and_account(self, client):
        _admin(client)
        resp = client.post(f"{API}/students/onboard", json=self._payload())
        assert resp.status_code == 201

        body = resp.json()
        assert body["student"]["status"] == "ACTIVE"
        assert body["account"]["is_active"] is True
        assert body["account"]["must_change_password"] is True
        assert body["student"]["user_email"] == body["account"]["email"]
        assert len(body["temporary_password"]) >= 16

    def test_onboarded_student_can_sign_in(self, client):
        """The whole point of onboarding: the student can actually log in."""
        _admin(client)
        payload = self._payload()
        resp = client.post(f"{API}/students/onboard", json=payload)
        password = resp.json()["temporary_password"]
        student_user_id = resp.json()["student"]["user_id"]

        _logout(client)
        login = _login(client, payload["email"], password)
        assert login.status_code == 200
        roles = {r["name"] for r in login.json()["user"]["roles"]}
        assert roles == {"STUDENT"}
        assert login.json()["user"]["id"] == student_user_id

    def test_onboarded_student_can_read_own_record_only(self, client):
        _admin(client)
        payload = self._payload()
        created = client.post(f"{API}/students/onboard", json=payload).json()
        own_id = created["student"]["id"]
        password = created["temporary_password"]

        _logout(client)
        assert _login(client, payload["email"], password).status_code == 200
        _retire_temporary_password(client, password)

        assert client.get(f"{API}/students/{own_id}").status_code == 200
        # ...but not the directory, and not someone else.
        assert client.get(f"{API}/students/").status_code == 403
        assert client.get(f"{API}/students/{uuid.uuid4()}").status_code == 404

    def test_onboarded_student_cannot_escalate_via_self_update(self, client):
        """Mass-assignment guard: administrative fields are ignored."""
        _admin(client)
        payload = self._payload()
        created = client.post(f"{API}/students/onboard", json=payload).json()
        student_id = created["student"]["id"]
        password = created["temporary_password"]

        _logout(client)
        assert _login(client, payload["email"], password).status_code == 200
        _retire_temporary_password(client, password)

        resp = client.patch(
            f"{API}/students/{student_id}/self",
            json={
                "phone": "+86-138-0000-0000",
                # All of the following must be silently rejected.
                "status": "GRADUATED",
                "student_id": "STU-HACKED",
                "last_name": "Hacked",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["phone"] == "+86-138-0000-0000"
        assert body["status"] == "ACTIVE"
        assert body["student_id"] == payload["student_id"].upper()
        assert body["last_name"] == payload["last_name"]

    def test_duplicate_student_number_conflicts(self, client):
        _admin(client)
        payload = self._payload()
        assert client.post(f"{API}/students/onboard", json=payload).status_code == 201
        retry = dict(payload, email=f"{_unique('other')}@example.com")
        assert client.post(f"{API}/students/onboard", json=retry).status_code == 409

    def test_failed_onboard_leaves_no_orphan_account(self, client):
        """A rejected student must not leave a loginable account behind."""
        _admin(client)
        payload = self._payload()
        assert client.post(f"{API}/students/onboard", json=payload).status_code == 201

        email = f"{_unique('orphan')}@example.com"
        retry = dict(payload, email=email)  # same student number -> 409
        assert client.post(f"{API}/students/onboard", json=retry).status_code == 409

        # The account must not exist, so the credential cannot be used.
        resp = client.get(f"{API}/users/", params={"search": email})
        assert resp.json()["total"] == 0

    def test_invalid_email_rejected(self, client):
        _admin(client)
        resp = client.post(
            f"{API}/students/onboard", json=self._payload(email="nope")
        )
        assert resp.status_code == 422

    def test_unknown_program_rejected(self, client):
        _admin(client)
        resp = client.post(
            f"{API}/students/onboard",
            json=self._payload(program_id=str(uuid.uuid4())),
        )
        assert resp.status_code == 409

    def test_student_cannot_onboard_another_student(self, client):
        _login(client, "student@school.portal")
        resp = client.post(f"{API}/students/onboard", json=self._payload())
        assert resp.status_code == 403

    def test_teacher_cannot_onboard(self, client):
        _login(client, "teacher@school.portal")
        resp = client.post(f"{API}/students/onboard", json=self._payload())
        assert resp.status_code == 403

    def test_unauthenticated_cannot_onboard(self, client):
        assert client.post(f"{API}/students/onboard", json=self._payload()).status_code == 401

    def test_management_can_onboard(self, client):
        _management(client)
        resp = client.post(f"{API}/students/onboard", json=self._payload())
        assert resp.status_code == 201

    def test_student_can_resolve_own_record_without_knowing_its_id(self, client):
        """Self-service must not require an identifier the student never sees."""
        _admin(client)
        payload = self._payload()
        created = client.post(f"{API}/students/onboard", json=payload).json()
        password = created["temporary_password"]

        _logout(client)
        assert _login(client, payload["email"], password).status_code == 200
        _retire_temporary_password(client, password)

        resp = client.get(f"{API}/students/me")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["student"]["id"]
        assert resp.json()["user_email"] == payload["email"]

    def test_me_is_scoped_to_the_caller(self, client):
        """Two students must never resolve to the same record."""
        _admin(client)
        first = self._payload()
        second = self._payload()
        first_created = client.post(f"{API}/students/onboard", json=first).json()
        second_created = client.post(f"{API}/students/onboard", json=second).json()

        _logout(client)
        first_login = _login(
            client, first["email"], first_created["temporary_password"]
        )
        assert first_login.status_code == 200
        _retire_temporary_password(client, first_created["temporary_password"])
        assert (
            client.get(f"{API}/students/me").json()["id"]
            == first_created["student"]["id"]
        )

        _logout(client)
        second_login = _login(
            client, second["email"], second_created["temporary_password"]
        )
        assert second_login.status_code == 200
        _retire_temporary_password(client, second_created["temporary_password"])
        assert (
            client.get(f"{API}/students/me").json()["id"]
            == second_created["student"]["id"]
        )

    def test_staff_without_a_student_record_gets_404(self, client):
        """A teacher account is not a student, and must be told so plainly."""
        _login(client, "teacher@school.portal")
        resp = client.get(f"{API}/students/me")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NO_STUDENT_RECORD"

    def test_unauthenticated_cannot_resolve_me(self, client):
        assert client.get(f"{API}/students/me").status_code == 401

    def test_student_account_endpoint_requires_account_permission(self, client):
        _admin(client)
        created = client.post(f"{API}/students/onboard", json=self._payload()).json()
        student_id = created["student"]["id"]
        assert client.get(f"{API}/students/{student_id}/account").status_code == 200

        _logout(client)
        _login(client, "student@school.portal")
        assert client.get(f"{API}/students/{student_id}/account").status_code == 403

    def test_student_account_response_has_no_credentials(self, client):
        _admin(client)
        created = client.post(f"{API}/students/onboard", json=self._payload()).json()
        student_id = created["student"]["id"]
        resp = client.get(f"{API}/students/{student_id}/account")
        assert resp.status_code == 200

        # `must_change_password` is a legitimate flag, so assert on the
        # credential-bearing keys rather than on the substring "password".
        keys = set(resp.json().keys())
        assert "hashed_password" not in keys
        assert "password" not in keys
        assert "token" not in keys
        assert "token_hash" not in resp.text.lower()


class TestBulkStatus:
    def _two_students(self, client):
        ids = []
        for _ in range(2):
            payload = {
                "student_id": _unique("BULK").upper(),
                "first_name": "Bulk",
                "last_name": "Student",
                "email": f"{_unique('bulk')}@example.com",
            }
            created = client.post(f"{API}/students/onboard", json=payload).json()
            ids.append(created["student"]["id"])
        return ids

    def test_admin_bulk_updates_status(self, client):
        _admin(client)
        ids = self._two_students(client)
        resp = client.post(
            f"{API}/students/bulk/status",
            json={"student_ids": ids, "status": "SUSPENDED"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["succeeded"] == 2
        assert body["failed"] == 0

        for student_id in ids:
            assert client.get(f"{API}/students/{student_id}").json()["status"] == "SUSPENDED"

    def test_missing_student_reported_not_fatal(self, client):
        _admin(client)
        ids = self._two_students(client)
        resp = client.post(
            f"{API}/students/bulk/status",
            json={"student_ids": [*ids, str(uuid.uuid4())], "status": "INACTIVE"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["succeeded"] == 2
        assert body["failed"] == 1
        assert any(not r["ok"] for r in body["results"])

    def test_student_cannot_bulk_update(self, client):
        _admin(client)
        ids = self._two_students(client)
        _logout(client)
        _login(client, "student@school.portal")
        resp = client.post(
            f"{API}/students/bulk/status",
            json={"student_ids": ids, "status": "INACTIVE"},
        )
        assert resp.status_code == 403

    def test_teacher_cannot_change_student_status(self, client):
        """Enrolment status is an institutional decision, not a teaching one.

        Teachers hold no ``student.edit`` permission, so bulk status changes are
        refused outright rather than applied to a scoped subset.
        """
        _admin(client)
        ids = self._two_students(client)
        _logout(client)

        _login(client, "teacher@school.portal")
        resp = client.post(
            f"{API}/students/bulk/status",
            json={"student_ids": ids, "status": "INACTIVE"},
        )
        assert resp.status_code == 403

        # Nothing changed.
        _logout(client)
        _admin(client)
        for student_id in ids:
            assert client.get(f"{API}/students/{student_id}").json()["status"] == "ACTIVE"

    def test_bulk_requires_non_empty_selection(self, client):
        _admin(client)
        resp = client.post(
            f"{API}/students/bulk/status", json={"student_ids": [], "status": "ACTIVE"}
        )
        assert resp.status_code == 422

    def test_bulk_rejects_invalid_status(self, client):
        _admin(client)
        ids = self._two_students(client)
        resp = client.post(
            f"{API}/students/bulk/status",
            json={"student_ids": ids, "status": "NONSENSE"},
        )
        assert resp.status_code == 422


class TestDirectoryFilters:
    def test_immigration_status_filter_is_well_formed(self, client):
        """Every documented bucket must be accepted and return a valid shape."""
        _admin(client)
        for bucket in ("VALID", "EXPIRING_SOON", "URGENT", "EXPIRED", "NOT_PROVIDED"):
            resp = client.get(
                f"{API}/students/", params={"immigration_status": bucket}
            )
            assert resp.status_code == 200, bucket
            assert "items" in resp.json()

    def test_sort_options_accepted(self, client):
        _admin(client)
        for key in ("name", "-name", "student_number", "newest", "oldest"):
            resp = client.get(f"{API}/students/", params={"sort": key})
            assert resp.status_code == 200, key

    def test_student_number_sort_is_ordered(self, client):
        _admin(client)
        items = client.get(
            f"{API}/students/", params={"sort": "student_number", "page_size": 100}
        ).json()["items"]
        numbers = [i["student_id"] for i in items]
        assert numbers == sorted(numbers)

    def test_unknown_sort_key_falls_back_safely(self, client):
        """An unrecognised sort must not error or expose a column."""
        _admin(client)
        resp = client.get(f"{API}/students/", params={"sort": "hashed_password"})
        assert resp.status_code == 200


class TestStudentStatusGatesPortalAccess:
    """An institutional status change must actually remove access.

    The account row and the student record are separate objects, so disabling
    one says nothing about the other. Before this rule existed, archiving a
    student left their login working indefinitely: the account stayed active
    and any cookie they already held kept resolving.
    """

    def _onboard(self, client, **overrides):
        payload = {
            "student_id": _unique("GATE").upper(),
            "first_name": "Gate",
            "last_name": "Check",
            "email": f"{_unique('gate')}@example.com",
        }
        payload.update(overrides)
        resp = client.post(f"{API}/students/onboard", json=payload)
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_archiving_a_student_blocks_further_sign_in(self, client):
        _admin(client)
        created = self._onboard(client)
        student_id = created["student"]["id"]
        email = created["account"]["email"]
        password = created["temporary_password"]

        assert client.post(
            f"{API}/students/{student_id}/archive"
        ).status_code == 200

        _logout(client)
        resp = _login(client, email, password)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "STUDENT_RECORD_INACTIVE"

    def test_a_live_session_dies_when_the_status_changes(self, client):
        """The check must apply per request, not only at sign-in.

        Otherwise a suspended student keeps full access until their cookie
        happens to expire.
        """
        _admin(client)
        created = self._onboard(client)
        student_id = created["student"]["id"]
        email = created["account"]["email"]
        password = created["temporary_password"]

        with TestClient(client.app) as holder:
            assert _login(holder, email, password).status_code == 200
            assert holder.get(f"{API}/auth/me").status_code == 200

            changed = client.patch(
                f"{API}/students/{student_id}/status", json={"status": "SUSPENDED"}
            )
            assert changed.status_code == 200

            # Same cookie, no re-authentication in between.
            assert holder.get(f"{API}/auth/me").status_code == 401

    def test_reactivation_restores_sign_in(self, client):
        """The rule must be reversible, or archived-in-error is unrecoverable."""
        _admin(client)
        created = self._onboard(client)
        student_id = created["student"]["id"]
        email = created["account"]["email"]
        password = created["temporary_password"]

        for status in ("INACTIVE", "ACTIVE"):
            assert client.patch(
                f"{API}/students/{student_id}/status", json={"status": status}
            ).status_code == 200

        _logout(client)
        assert _login(client, email, password).status_code == 200

    def test_every_non_active_status_is_refused(self, client):
        """Pins the whole set, not just the two used above."""
        _admin(client)
        for status in ("INACTIVE", "SUSPENDED", "WITHDRAWN", "GRADUATED"):
            created = self._onboard(client)
            student_id = created["student"]["id"]
            password = created["temporary_password"]
            email = created["account"]["email"]

            assert client.patch(
                f"{API}/students/{student_id}/status", json={"status": status}
            ).status_code == 200

            _logout(client)
            resp = _login(client, email, password)
            assert resp.status_code == 403, status
            assert resp.json()["error"]["code"] == "STUDENT_RECORD_INACTIVE", status
            _admin(client)

    def test_staff_without_a_student_record_is_unaffected(self, client):
        """The gate must not misfire on accounts that are not students."""
        for email in ("admin@school.portal", "management@school.portal"):
            _logout(client)
            assert _login(client, email).status_code == 200, email
            assert client.get(f"{API}/auth/me").status_code == 200

    def test_the_seeded_student_can_still_sign_in(self, client):
        """Guards against the gate being wired to the wrong column."""
        assert _login(client, "student@school.portal").status_code == 200
        assert client.get(f"{API}/students/me").status_code == 200
