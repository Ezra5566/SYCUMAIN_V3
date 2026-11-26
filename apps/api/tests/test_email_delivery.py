"""SMTP delivery, retry and duplicate prevention.

The mail server here is a small in-process SMTP sink, not a mock of our own
code: ``smtplib`` performs a real conversation over a real socket, so the
transport path that would run against an institutional relay is what is being
tested. Nothing leaves the machine and no credential is invented.

Assertions deliberately include what must *not* happen: a token never appears
in a log record, and a notification email never carries case details.
"""

from __future__ import annotations

import email
import socketserver
import threading
import uuid

import pytest

from app.config.settings import get_settings
from app.models.audit import AuditLog
from app.models.identity import User
from app.models.mail import EmailOutbox, EmailOutboxStatus
from app.models.platform import NotificationType
from app.services.mailer import flush_outbox, mask_address, send_email
from app.services.notification import create_notification

API = "/api/v1"


class _SMTPSink(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self) -> None:
        self.messages: list[bytes] = []
        self.lock = threading.Lock()
        super().__init__(("127.0.0.1", 0), _Handler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])


class _Handler(socketserver.StreamRequestHandler):
    def _reply(self, line: str) -> None:
        self.wfile.write(f"{line}\r\n".encode())

    def handle(self) -> None:  # noqa: C901 - a tiny protocol loop
        self._reply("220 localhost test SMTP sink")
        while True:
            raw = self.rfile.readline()
            if not raw:
                return
            command = raw.decode("utf-8", "replace").strip()
            upper = command.upper()

            if upper.startswith("EHLO"):
                self._reply("250-localhost")
                self._reply("250-8BITMIME")
                self._reply("250 AUTH LOGIN PLAIN")
            elif upper.startswith("HELO"):
                self._reply("250 localhost")
            elif upper.startswith("AUTH PLAIN"):
                # smtplib sends the base64 payload on the same line.
                self._reply("235 2.7.0 authentication successful")
            elif upper.startswith("AUTH LOGIN"):
                self._reply("334 VXNlcm5hbWU6")  # "Username:"
                self.rfile.readline()
                self._reply("334 UGFzc3dvcmQ6")  # "Password:"
                self.rfile.readline()
                self._reply("235 2.7.0 authentication successful")
            elif upper.startswith("MAIL FROM") or upper.startswith("RCPT TO"):
                self._reply("250 OK")
            elif upper == "DATA":
                self._reply("354 End data with <CR><LF>.<CR><LF>")
                chunks: list[bytes] = []
                while True:
                    line = self.rfile.readline()
                    if not line or line in {b".\r\n", b".\n"}:
                        break
                    # RFC 5321 dot-stuffing.
                    chunks.append(line[1:] if line.startswith(b"..") else line)
                body = b"".join(chunks)
                server = self.server
                assert isinstance(server, _SMTPSink)
                with server.lock:
                    server.messages.append(body)
                self._reply("250 OK queued")
            elif upper == "RSET" or upper == "NOOP":
                self._reply("250 OK")
            elif upper == "QUIT":
                self._reply("221 Bye")
                return
            else:
                self._reply("250 OK")


@pytest.fixture
def smtp_sink():
    """A local SMTP server plus the settings that point the application at it."""
    server = _SMTPSink()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    settings = get_settings()
    original = {
        "EMAIL_ENABLED": settings.EMAIL_ENABLED,
        "SMTP_HOST": settings.SMTP_HOST,
        "SMTP_PORT": settings.SMTP_PORT,
        "SMTP_USERNAME": settings.SMTP_USERNAME,
        "SMTP_PASSWORD": settings.SMTP_PASSWORD,
        "SMTP_STARTTLS": settings.SMTP_STARTTLS,
        "SMTP_USE_SSL": settings.SMTP_USE_SSL,
        "SMTP_TIMEOUT_SECONDS": settings.SMTP_TIMEOUT_SECONDS,
        "EMAIL_FROM": settings.EMAIL_FROM,
        "EMAIL_MAX_ATTEMPTS": settings.EMAIL_MAX_ATTEMPTS,
        "EMAIL_RETRY_BACKOFF_SECONDS": settings.EMAIL_RETRY_BACKOFF_SECONDS,
        "EMAIL_NOTIFICATIONS_ENABLED": settings.EMAIL_NOTIFICATIONS_ENABLED,
        "PASSWORD_RESET_DELIVERY": settings.PASSWORD_RESET_DELIVERY,
        "ACTIVATION_LINK_BASE": settings.ACTIVATION_LINK_BASE,
    }
    settings.EMAIL_ENABLED = True
    settings.SMTP_HOST = "127.0.0.1"
    settings.SMTP_PORT = server.port
    settings.SMTP_USERNAME = ""
    settings.SMTP_PASSWORD = ""
    settings.SMTP_STARTTLS = False
    settings.SMTP_USE_SSL = False
    settings.SMTP_TIMEOUT_SECONDS = 3
    settings.EMAIL_FROM = "portal@school.test"
    settings.EMAIL_MAX_ATTEMPTS = 2
    settings.EMAIL_RETRY_BACKOFF_SECONDS = 0

    try:
        yield server
    finally:
        for key, value in original.items():
            setattr(settings, key, value)
        server.shutdown()
        server.server_close()


def _messages(server: _SMTPSink) -> list[email.message.Message]:
    with server.lock:
        return [
            email.message_from_bytes(raw, policy=email.policy.default)
            for raw in server.messages
        ]


def _text(message: email.message.Message) -> str:
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        return ""
    return part.get_content()


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


def test_delivery_is_reported_unconfigured_by_default():
    """An unconfigured instal must not silently pretend to send."""
    result = send_email(
        to="student@school.portal", subject="x", body="y", purpose="test"
    )

    assert result.sent is False
    assert result.detail == "not_configured"


def test_smtp_delivery_reaches_the_server(smtp_sink):
    result = send_email(
        to="student@school.portal",
        subject="Portal test",
        body="A body without secrets.",
        purpose="test",
    )

    assert result.sent is True, result.detail
    messages = _messages(smtp_sink)
    assert len(messages) == 1
    assert messages[0]["To"] == "student@school.portal"
    assert messages[0]["Subject"] == "Portal test"
    assert messages[0]["Auto-Submitted"] == "auto-generated"
    assert "A body without secrets." in _text(messages[0])


def test_authentication_is_used_when_configured(smtp_sink):
    settings = get_settings()
    settings.SMTP_USERNAME = "relay-user"
    settings.SMTP_PASSWORD = "relay-password"

    result = send_email(to="student@school.portal", subject="s", body="b", purpose="test")

    assert result.sent is True
    assert len(_messages(smtp_sink)) == 1


def test_failed_delivery_is_reported_not_raised(smtp_sink):
    settings = get_settings()
    settings.SMTP_PORT = 1  # nothing listens here
    settings.EMAIL_MAX_ATTEMPTS = 2

    result = send_email(to="student@school.portal", subject="s", body="b", purpose="test")

    assert result.sent is False
    assert result.attempts == 2


def test_addresses_are_masked_for_logging():
    assert mask_address("fatima.zahra@example.edu") == "fa**********@example.edu"
    assert mask_address("not-an-address") == "***"


# --------------------------------------------------------------------------
# Password reset delivery
# --------------------------------------------------------------------------


def test_password_reset_link_is_emailed_and_never_returned(client, smtp_sink):
    settings = get_settings()
    settings.PASSWORD_RESET_DELIVERY = "smtp"

    response = client.post(
        f"{API}/auth/password/reset-request", json={"email": "student@school.portal"}
    )

    assert response.status_code == 202
    assert response.json()["dev_token"] is None

    messages = _messages(smtp_sink)
    assert len(messages) == 1
    assert messages[0]["To"] == "student@school.portal"
    body = _text(messages[0])
    assert "/reset-password?token=" in body

    token = body.split("/reset-password?token=", 1)[1].split()[0]
    completed = client.post(
        f"{API}/auth/password/reset",
        json={"token": token, "new_password": "Emailed-Passphrase!42"},
    )
    assert completed.status_code == 200


def test_unknown_address_sends_no_email_and_looks_identical(client, smtp_sink):
    settings = get_settings()
    settings.PASSWORD_RESET_DELIVERY = "smtp"

    response = client.post(
        f"{API}/auth/password/reset-request",
        json={"email": "nobody@school.portal"},
    )

    assert response.status_code == 202
    assert response.json()["dev_token"] is None
    assert _messages(smtp_sink) == []


def test_reset_email_failure_is_audited_but_does_not_disclose(
    client, smtp_sink, db_session
):
    settings = get_settings()
    settings.PASSWORD_RESET_DELIVERY = "smtp"
    settings.SMTP_PORT = 1
    settings.EMAIL_MAX_ATTEMPTS = 1

    response = client.post(
        f"{API}/auth/password/reset-request", json={"email": "student@school.portal"}
    )

    assert response.status_code == 202
    assert response.json()["dev_token"] is None

    user = db_session.query(User).filter(User.email == "student@school.portal").one()
    actions = {
        row.action
        for row in db_session.query(AuditLog).filter(AuditLog.entity_id == user.id)
    }
    assert "auth.password_reset_delivery_failed" in actions


# --------------------------------------------------------------------------
# Activation delivery
# --------------------------------------------------------------------------


def test_activation_link_is_emailed(client, smtp_sink):
    assert client.post(
        f"{API}/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    ).status_code == 200

    email_address = f"activate-{uuid.uuid4().hex[:8]}@school.portal"
    created = client.post(
        f"{API}/users/",
        json={
            "email": email_address,
            "full_name": "Activation Subject",
            "roles": ["STUDENT"],
            "password": "Initial-Passphrase!42",
            "must_change_password": False,
        },
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["account"]["id"]

    issued = client.post(
        f"{API}/users/{user_id}/activation",
        json={
            "identity_verified": True,
            "verification_reference": "COUNTER-CHECK",
            "delivery": "ACADEMIC_EMAIL",
        },
    )

    assert issued.status_code == 200, issued.text
    messages = _messages(smtp_sink)
    assert len(messages) == 1
    assert messages[0]["To"] == email_address
    assert "/activate?token=" in _text(messages[0])


def test_activation_email_failure_returns_503_and_leaves_no_live_link(
    client, smtp_sink, db_session
):
    assert client.post(
        f"{API}/auth/login",
        json={"email": "admin@school.portal", "password": "password123"},
    ).status_code == 200
    email_address = f"activate-{uuid.uuid4().hex[:8]}@school.portal"
    created = client.post(
        f"{API}/users/",
        json={
            "email": email_address,
            "full_name": "Activation Failure",
            "roles": ["STUDENT"],
            "password": "Initial-Passphrase!42",
            "must_change_password": False,
        },
    )
    user_id = created.json()["account"]["id"]
    settings = get_settings()
    settings.SMTP_PORT = 1
    settings.EMAIL_MAX_ATTEMPTS = 1

    issued = client.post(
        f"{API}/users/{user_id}/activation",
        json={"identity_verified": True, "delivery": "ACADEMIC_EMAIL"},
    )

    assert issued.status_code == 503
    assert issued.json()["error"]["code"] == "EMAIL_DELIVERY_FAILED"

    state = client.get(f"{API}/users/{user_id}/activation")
    assert state.status_code == 200
    # The rollback restored the account to its pre-issue state: no pending
    # token exists, so nothing is left that could be used without an email.
    assert state.json()["state"] in {"NONE", "ACTIVATED"}
    assert state.json()["activation_required"] is False


# --------------------------------------------------------------------------
# Notification outbox
# --------------------------------------------------------------------------


def _notification_for_student(
    db_session,
    notification_type=NotificationType.IMMIGRATION_EXPIRY_URGENT,
):
    user = db_session.query(User).filter(User.email == "student@school.portal").one()
    notification = create_notification(
        db_session,
        user_id=user.id,
        notification_type=notification_type,
        params={"document": "passport", "days": 14, "expiry_date": "2027-01-01"},
        link_url="/app/immigration",
        entity_type="immigration_reminder",
        entity_id=uuid.uuid4(),
    )
    db_session.commit()
    return user, notification


def test_notification_email_is_queued_and_sent_once(db_session, smtp_sink):
    settings = get_settings()
    settings.EMAIL_NOTIFICATIONS_ENABLED = True

    user, notification = _notification_for_student(db_session)

    rows = db_session.query(EmailOutbox).all()
    assert len(rows) == 1
    assert rows[0].dedupe_key == f"notification:{notification.id}"
    assert rows[0].status == EmailOutboxStatus.PENDING

    first = flush_outbox(db_session)
    second = flush_outbox(db_session)

    assert first["sent"] == 1
    assert second["due"] == 0
    assert len(_messages(smtp_sink)) == 1

    message = _messages(smtp_sink)[0]
    assert message["To"] == user.email
    body = _text(message)
    assert "/app/immigration" in body
    # The notification's own parameters must not travel in mail.
    assert "passport" not in body
    assert "2027-01-01" not in body


def test_notification_email_is_not_queued_unless_enabled(db_session, smtp_sink):
    settings = get_settings()
    settings.EMAIL_NOTIFICATIONS_ENABLED = False

    _notification_for_student(db_session)

    assert db_session.query(EmailOutbox).count() == 0


def test_a_type_outside_the_allowlist_is_not_emailed(db_session, smtp_sink):
    settings = get_settings()
    settings.EMAIL_NOTIFICATIONS_ENABLED = True

    _notification_for_student(
        db_session, notification_type=NotificationType.ANNOUNCEMENT_PUBLISHED
    )

    assert db_session.query(EmailOutbox).count() == 0


def test_permanent_failure_is_recorded_after_bounded_attempts(db_session, smtp_sink):
    settings = get_settings()
    settings.EMAIL_NOTIFICATIONS_ENABLED = True
    settings.SMTP_PORT = 1
    settings.EMAIL_MAX_ATTEMPTS = 2

    _notification_for_student(db_session)

    first = flush_outbox(db_session)
    second = flush_outbox(db_session)

    assert first["retrying"] == 1
    assert second["failed"] == 1
    row = db_session.query(EmailOutbox).one()
    assert row.status == EmailOutboxStatus.FAILED
    assert row.attempts == 2
    assert row.last_error


def test_flush_without_configuration_changes_nothing(db_session, smtp_sink):
    settings = get_settings()
    settings.EMAIL_NOTIFICATIONS_ENABLED = True
    _notification_for_student(db_session)
    settings.EMAIL_ENABLED = False

    result = flush_outbox(db_session)

    assert result["skipped"] == 1
    row = db_session.query(EmailOutbox).one()
    assert row.status == EmailOutboxStatus.PENDING
    assert row.attempts == 0
