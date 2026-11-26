"""SMTP delivery for account and notification email.

Design decisions that matter operationally
------------------------------------------
* **Configuration, not a provider.** Any SMTP endpoint works: a campus relay, a
  transactional provider, or a local test sink. No provider SDK is bundled and
  no credentials are invented.
* **Failures are values, not exceptions.** A mail outage must not roll back an
  admission change or a reminder reconciliation. Callers decide what a failed
  delivery means for their workflow.
* **Bounded retries.** A transient refusal is retried a few times with
  exponential backoff; a persistent failure stops and is recorded. There is no
  unbounded retry loop behind a request.
* **Nothing sensitive is logged.** The recipient is masked, and the subject and
  body are never logged: a password-reset body contains a working token.

Delivery paths
--------------
* Password reset and account activation links are sent *inline*, by the request
  that minted the token. They are never written to the outbox.
* Operational notifications are queued in ``email_outbox`` and sent by
  ``python -m app.cli send-emails`` (cron or a platform scheduler). The unique
  dedupe key makes a repeated flush safe.
"""

from __future__ import annotations

import logging
import smtplib
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from typing import TYPE_CHECKING

from app.config.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger("app.email")


def mask_address(value: str) -> str:
    """Return an address safe to write to a log line."""
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def email_configured() -> bool:
    """Whether a message can actually be handed to a mail server."""
    settings = get_settings()
    return bool(settings.EMAIL_ENABLED and settings.SMTP_HOST.strip())


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of one send attempt sequence."""

    sent: bool
    detail: str
    attempts: int = 0


def _build_message(*, to: str, subject: str, body: str, purpose: str) -> EmailMessage:
    settings = get_settings()
    message = EmailMessage()
    sender = settings.EMAIL_FROM.strip() or "no-reply@localhost"
    message["From"] = (
        formataddr((settings.EMAIL_FROM_NAME.strip(), sender))
        if settings.EMAIL_FROM_NAME.strip()
        else sender
    )
    message["To"] = to
    message["Subject"] = subject
    # Automatic mail must not trigger vacation responders or out-of-office
    # replies, and its provenance should be obvious to the receiving system.
    message["Auto-Submitted"] = "auto-generated"
    message["X-Portal-Purpose"] = purpose
    message.set_content(body)
    return message


def _attempt(*, to: str, message: EmailMessage) -> None:
    settings = get_settings()
    host = settings.SMTP_HOST.strip()
    timeout = settings.SMTP_TIMEOUT_SECONDS

    if settings.SMTP_USE_SSL:
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, settings.SMTP_PORT, timeout=timeout)
    else:
        server = smtplib.SMTP(host, settings.SMTP_PORT, timeout=timeout)

    with server:
        server.ehlo()
        if settings.SMTP_STARTTLS and not settings.SMTP_USE_SSL:
            server.starttls()
            server.ehlo()
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)


def send_email(
    *,
    to: str,
    subject: str,
    body: str,
    purpose: str,
    max_attempts: int | None = None,
) -> DeliveryResult:
    """Send one message, retrying a bounded number of times.

    ``max_attempts`` lets the outbox make exactly one attempt per flush cycle;
    the cycle count, not the SMTP call count, is what its ``attempts`` column
    records. Inline sends (reset, activation) use the configured retry budget.
    """
    settings = get_settings()

    if not email_configured():
        logger.warning(
            "email_not_configured",
            extra={"purpose": purpose, "recipient": mask_address(to)},
        )
        return DeliveryResult(False, "not_configured", 0)

    message = _build_message(to=to, subject=subject, body=body, purpose=purpose)
    attempts = max(
        1, max_attempts if max_attempts is not None else settings.EMAIL_MAX_ATTEMPTS
    )
    last_detail = "unknown"

    for attempt in range(1, attempts + 1):
        try:
            _attempt(to=to, message=message)
        except (smtplib.SMTPException, OSError) as exc:
            # The exception *class* is the useful, non-sensitive part. SMTP
            # responses can echo the recipient or a body fragment.
            last_detail = type(exc).__name__
            logger.warning(
                "email_delivery_failed",
                extra={
                    "purpose": purpose,
                    "recipient": mask_address(to),
                    "attempt": attempt,
                    "error": last_detail,
                },
            )
            if attempt < attempts:
                delay = settings.EMAIL_RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
                if delay > 0:
                    time.sleep(delay)
            continue

        logger.info(
            "email_delivered",
            extra={
                "purpose": purpose,
                "recipient": mask_address(to),
                "attempt": attempt,
            },
        )
        return DeliveryResult(True, "smtp", attempt)

    return DeliveryResult(False, last_detail, attempts)


def reset_email_body(link: str, expires_in_minutes: int) -> str:
    """Plain-text body for a reset link. Contains the link by necessity."""
    return (
        "A password reset was requested for your Student Portal account.\n\n"
        f"Choose a new password here (valid for {expires_in_minutes} minutes):\n"
        f"{link}\n\n"
        "If you did not request this, you can ignore this message; your current "
        "password remains unchanged.\n\n"
        "This message was generated automatically. Do not reply.\n"
    )


def activation_email_body(link: str, expires_in_hours: int) -> str:
    """Plain-text body for an activation link."""
    return (
        "Your Student Portal account has been created.\n\n"
        f"Set your password here (valid for {expires_in_hours} hours):\n"
        f"{link}\n\n"
        "This link can be used once. If it has expired, contact the "
        "international office for a new one.\n\n"
        "This message was generated automatically. Do not reply.\n"
    )


def notification_email_body(link: str) -> str:
    """Body for an operational notification. Deliberately detail-free."""
    return (
        "You have a new notification in the Student Portal.\n\n"
        f"Sign in to view it: {link}\n\n"
        "This message contains no personal or case details on purpose.\n"
        "This message was generated automatically. Do not reply.\n"
    )


def flush_outbox(db: DBSession, *, limit: int = 100) -> dict[str, int]:
    """Attempt every message that is due. Safe to run concurrently.

    ``FOR UPDATE SKIP LOCKED`` lets two schedulers run at once without sending
    the same row twice; the unique ``dedupe_key`` is the second line of
    defence.
    """
    from app.models.mail import EmailOutbox, EmailOutboxStatus  # noqa: PLC0415

    if not email_configured():
        return {"due": 0, "sent": 0, "retrying": 0, "failed": 0, "skipped": 1}

    now = datetime.now(UTC)
    rows = (
        db.query(EmailOutbox)
        .filter(
            EmailOutbox.status == EmailOutboxStatus.PENDING,
            EmailOutbox.next_attempt_at <= now,
        )
        .order_by(EmailOutbox.created_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
        .all()
    )

    sent = retrying = failed = 0
    for row in rows:
        row.attempts += 1
        result = send_email(
            to=row.to_email,
            subject=row.subject,
            body=row.body_text,
            purpose=row.purpose,
            max_attempts=1,
        )
        if result.sent:
            row.status = EmailOutboxStatus.SENT
            row.sent_at = datetime.now(UTC)
            row.last_error = None
            sent += 1
            continue

        row.last_error = result.detail[:200]
        if row.attempts >= max(1, get_settings().EMAIL_MAX_ATTEMPTS):
            row.status = EmailOutboxStatus.FAILED
            failed += 1
        else:
            delay = get_settings().EMAIL_RETRY_BACKOFF_SECONDS * (2 ** (row.attempts - 1))
            row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=max(delay, 0))
            retrying += 1

    db.commit()
    return {
        "due": len(rows),
        "sent": sent,
        "retrying": retrying,
        "failed": failed,
        "skipped": 0,
    }


__all__ = [
    "DeliveryResult",
    "activation_email_body",
    "email_configured",
    "flush_outbox",
    "mask_address",
    "notification_email_body",
    "reset_email_body",
    "send_email",
]
