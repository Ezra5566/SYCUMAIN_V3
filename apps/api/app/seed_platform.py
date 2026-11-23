"""Deterministic development seed for the Stage 7 platform modules.

Everything created here is **demo data**, clearly labelled as such. It exists
so the announcements, support, and notifications surfaces are not empty on a
fresh development database. No real student data, no passport/visa values, and
no document bytes are ever created here.

The seed is idempotent: running it repeatedly produces no duplicates.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.identity import Student, User
from app.models.platform import (
    Announcement,
    AnnouncementAudienceType,
    AnnouncementPriority,
    AnnouncementStatus,
    AnnouncementTranslation,
    SupportTicket,
    SupportTicketCategory,
    SupportTicketMessage,
    SupportTicketStatus,
)

# Marker so demo rows can be recognised (and never mistaken for real notices).
DEMO_TAG = "[DEMO]"


def _demo_announcements() -> list[dict]:
    return [
        {
            "key": "demo-welcome",
            "default_locale": "en",
            "priority": AnnouncementPriority.NORMAL,
            "is_pinned": True,
            "audience_type": AnnouncementAudienceType.ALL,
            "translations": {
                "en": (
                    f"{DEMO_TAG} Welcome to the International Student Portal",
                    "This is demonstration content used during development. "
                    "It will be replaced by real institutional notices.",
                ),
                "zh": (
                    f"{DEMO_TAG} 欢迎使用国际学生门户",
                    "这是开发期间使用的演示内容，正式通知发布后将予以替换。",
                ),
                "fr": (
                    f"{DEMO_TAG} Bienvenue sur le portail des étudiants internationaux",
                    "Ceci est un contenu de démonstration utilisé pendant le "
                    "développement. Il sera remplacé par de véritables avis.",
                ),
                "ar": (
                    f"{DEMO_TAG} مرحبًا بك في بوابة الطلاب الدوليين",
                    "هذا محتوى توضيحي يُستخدم أثناء التطوير، وسيُستبدل بإشعارات "
                    "رسمية حقيقية.",
                ),
            },
        },
        {
            "key": "demo-immigration-reminder",
            "default_locale": "en",
            "priority": AnnouncementPriority.HIGH,
            "is_pinned": False,
            "audience_type": AnnouncementAudienceType.STUDENTS,
            "translations": {
                "en": (
                    f"{DEMO_TAG} Check your visa and residence permit expiry dates",
                    "Please review the Immigration tab on your profile and "
                    "submit an update request if any expiry date is incorrect.",
                ),
                "zh": (
                    f"{DEMO_TAG} 请检查您的签证与居留许可到期日",
                    "请查看个人资料中的出入境信息，如到期日有误请提交更新申请。",
                ),
                "fr": (
                    f"{DEMO_TAG} Vérifiez vos dates d'expiration",
                    "Consultez l'onglet Immigration de votre profil et soumettez "
                    "une demande de mise à jour si une date est incorrecte.",
                ),
                "ar": (
                    f"{DEMO_TAG} تحقق من تواريخ انتهاء التأشيرة وتصريح الإقامة",
                    "يرجى مراجعة قسم الهجرة في ملفك الشخصي وتقديم طلب تحديث إذا "
                    "كان أي تاريخ غير صحيح.",
                ),
            },
        },
        {
            "key": "demo-housing-notice",
            "default_locale": "en",
            "priority": AnnouncementPriority.NORMAL,
            "is_pinned": False,
            "audience_type": AnnouncementAudienceType.STUDENTS,
            "expires_in_days": 60,
            "translations": {
                "en": (
                    f"{DEMO_TAG} Dormitory maintenance schedule",
                    "Routine maintenance will take place across the dormitory "
                    "blocks. Affected students will be contacted directly.",
                ),
                "zh": (
                    f"{DEMO_TAG} 宿舍维护安排",
                    "宿舍楼将进行例行维护，受影响的同学将收到单独通知。",
                ),
            },
        },
        {
            "key": "demo-staff-briefing",
            "default_locale": "en",
            "priority": AnnouncementPriority.LOW,
            "is_pinned": False,
            "audience_type": AnnouncementAudienceType.STAFF,
            "translations": {
                "en": (
                    f"{DEMO_TAG} Staff briefing: semester reporting",
                    "Operational reports for the current semester are available "
                    "under Reports.",
                ),
                "zh": (
                    f"{DEMO_TAG} 教工简报：学期报告",
                    "本学期运营报告已在“报告”页面发布。",
                ),
            },
        },
    ]


def seed_platform(db: Session) -> None:
    """Seed demo announcements and a demo support ticket (idempotent)."""
    _seed_announcements(db)
    _seed_support_ticket(db)
    db.commit()


def _seed_announcements(db: Session) -> None:
    admin = db.query(User).filter(User.email == "admin@school.portal").first()
    now = datetime.now(UTC)

    for spec in _demo_announcements():
        exists = (
            db.query(Announcement)
            .join(AnnouncementTranslation)
            .filter(AnnouncementTranslation.title.like(f"{DEMO_TAG}%"))
            .filter(AnnouncementTranslation.locale == spec["default_locale"])
            .filter(
                AnnouncementTranslation.title
                == spec["translations"][spec["default_locale"]][0]
            )
            .first()
        )
        if exists:
            continue

        expires_in = spec.get("expires_in_days")
        announcement = Announcement(
            default_locale=spec["default_locale"],
            status=AnnouncementStatus.PUBLISHED,
            priority=spec["priority"],
            is_pinned=spec["is_pinned"],
            audience_type=spec["audience_type"],
            published_at=now,
            expires_at=(now + timedelta(days=expires_in)) if expires_in else None,
            created_by=admin.id if admin else None,
            updated_by=admin.id if admin else None,
        )
        db.add(announcement)
        db.flush()

        for locale, (title, body) in spec["translations"].items():
            db.add(
                AnnouncementTranslation(
                    announcement_id=announcement.id,
                    locale=locale,
                    title=title,
                    body=body,
                )
            )

    db.flush()


def _seed_support_ticket(db: Session) -> None:
    student = db.query(Student).filter(Student.student_id == "STU-001").first()
    if student is None:
        return

    subject = f"{DEMO_TAG} How do I update my phone number?"

    existing = (
        db.query(SupportTicket).filter(SupportTicket.subject == subject).first()
    )
    if existing:
        return

    ticket = SupportTicket(
        ticket_number="SUP-0001",
        student_id=student.id,
        created_by=student.user_id,
        category=SupportTicketCategory.GENERAL,
        subject=subject,
        description=(
            "Demonstration ticket. I would like to change the phone number on "
            "my student profile."
        ),
        status=SupportTicketStatus.OPEN,
    )
    db.add(ticket)
    db.flush()

    db.add(
        SupportTicketMessage(
            ticket_id=ticket.id,
            author_id=student.user_id,
            body="Demonstration follow-up message.",
            is_internal=False,
        )
    )
    db.flush()


__all__ = ["seed_platform", "DEMO_TAG"]
