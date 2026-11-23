"""Announcement service.

Responsibilities:

* create/update announcements with per-locale translations;
* resolve the correct translation for a reader's locale with a deterministic
  fallback chain (requested locale -> announcement default locale -> first);
* resolve audience visibility server-side.

Audience is always evaluated on the backend. The frontend may hide a link,
but it can never decide who sees an announcement.
"""

from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session as DBSession

from app.models.academic import Enrollment, EnrollmentStatus
from app.models.identity import Student, User
from app.models.platform import (
    Announcement,
    AnnouncementAudienceType,
    AnnouncementStatus,
    AnnouncementTranslation,
)
from app.schemas.platform import (
    AnnouncementCreate,
    AnnouncementListItem,
    AnnouncementResponse,
    AnnouncementTranslationResponse,
    AnnouncementUpdate,
)
from app.services.student_academic import student_academic_snapshot

MANAGEMENT_ROLES = {"ADMIN", "MANAGEMENT"}


def _role_names(user: User) -> set[str]:
    return {r.name for r in user.roles}


def can_manage_announcements(user: User) -> bool:
    """Whether the user may see drafts and mutate announcements."""
    return bool(MANAGEMENT_ROLES & _role_names(user))


def resolve_translation(
    announcement: Announcement, locale: str | None
) -> tuple[str, str, str | None]:
    """Return `(locale, title, body)` using a deterministic fallback chain.

    Order:
      1. the requested locale, if present;
      2. the announcement's own default locale;
      3. any other translation, chosen alphabetically by locale.

    A missing translation never blanks the announcement and never overwrites
    the original content.
    """
    by_locale = {t.locale: t for t in announcement.translations}

    if locale:
        wanted = locale.strip().lower()
        # Accept both "zh" and "zh-CN" style keys.
        candidate = by_locale.get(wanted)
        if candidate is None and "-" in wanted:
            candidate = by_locale.get(wanted.split("-")[0])
        if candidate is not None:
            return (candidate.locale, candidate.title, candidate.body)

    fallback = by_locale.get(announcement.default_locale)
    if fallback is not None:
        return (fallback.locale, fallback.title, fallback.body)

    if by_locale:
        first = by_locale[sorted(by_locale)[0]]
        return (first.locale, first.title, first.body)

    return (announcement.default_locale, "", None)


def _audience_label(db: DBSession, announcement: Announcement) -> str | None:
    """Human-readable audience reference (a major, program, or class name)."""
    from app.models.academic import ClassSection, Major, Program  # noqa: PLC0415

    if announcement.audience_ref_id is None:
        return None

    match announcement.audience_type:
        case AnnouncementAudienceType.MAJOR:
            model, attr = Major, "name"
        case AnnouncementAudienceType.PROGRAM:
            model, attr = Program, "name"
        case AnnouncementAudienceType.CLASS:
            model, attr = ClassSection, "section_code"
        case _:
            return None

    row = db.query(model).filter(model.id == announcement.audience_ref_id).first()
    return getattr(row, attr) if row else None


def to_response(
    db: DBSession,
    announcement: Announcement,
    locale: str | None = None,
) -> AnnouncementResponse:
    """Full management representation, with the localized variant resolved."""
    resolved_locale, title, body = resolve_translation(announcement, locale)

    return AnnouncementResponse(
        id=announcement.id,
        status=announcement.status,
        priority=announcement.priority,
        is_pinned=announcement.is_pinned,
        default_locale=announcement.default_locale,
        audience_type=announcement.audience_type,
        audience_ref_id=announcement.audience_ref_id,
        audience_label=_audience_label(db, announcement),
        scheduled_at=announcement.scheduled_at,
        published_at=announcement.published_at,
        expires_at=announcement.expires_at,
        author_name=announcement.author.full_name if announcement.author else None,
        created_at=announcement.created_at,
        updated_at=announcement.updated_at,
        translations=[
            AnnouncementTranslationResponse.model_validate(t)
            for t in announcement.translations
        ],
        resolved_title=title,
        resolved_body=body,
        resolved_locale=resolved_locale,
    )


def to_list_item(
    announcement: Announcement, locale: str | None = None
) -> AnnouncementListItem:
    """Compact representation for listings."""
    resolved_locale, title, body = resolve_translation(announcement, locale)
    by_locale = {t.locale: t for t in announcement.translations}
    summary = by_locale.get(resolved_locale).summary if resolved_locale in by_locale else None
    if not summary and body:
        summary = body[:280]

    return AnnouncementListItem(
        id=announcement.id,
        status=announcement.status,
        priority=announcement.priority,
        is_pinned=announcement.is_pinned,
        audience_type=announcement.audience_type,
        title=title,
        summary=summary,
        resolved_locale=resolved_locale,
        published_at=announcement.published_at,
        expires_at=announcement.expires_at,
        created_at=announcement.created_at,
        author_name=announcement.author.full_name if announcement.author else None,
    )


# --- Audience visibility ---------------------------------------------------


def _student_of(db: DBSession, user: User) -> Student | None:
    return db.query(Student).filter(Student.user_id == user.id).first()


def visible_audience_filter(db: DBSession, user: User):
    """Build the SQL predicate describing announcements visible to `user`.

    Returns None when the user may see every audience (management).
    """
    roles = _role_names(user)
    if MANAGEMENT_ROLES & roles:
        return None

    audience_types = [AnnouncementAudienceType.ALL]

    if "STUDENT" in roles:
        audience_types.append(AnnouncementAudienceType.STUDENTS)
        student = _student_of(db, user)
        ref_predicates = []
        if student is not None:
            academic = student_academic_snapshot(db, student.id)
            if academic.major_id is not None:
                ref_predicates.append(
                    (Announcement.audience_type == AnnouncementAudienceType.MAJOR)
                    & (Announcement.audience_ref_id == academic.major_id)
                )
            if academic.program_id is not None:
                ref_predicates.append(
                    (Announcement.audience_type == AnnouncementAudienceType.PROGRAM)
                    & (Announcement.audience_ref_id == academic.program_id)
                )
            class_ids = [
                row[0]
                for row in db.query(Enrollment.class_section_id)
                .filter(
                    Enrollment.student_id == student.id,
                    Enrollment.status == EnrollmentStatus.ENROLLED,
                )
                .all()
            ]
            if class_ids:
                ref_predicates.append(
                    (Announcement.audience_type == AnnouncementAudienceType.CLASS)
                    & (Announcement.audience_ref_id.in_(class_ids))
                )

        base = Announcement.audience_type.in_(audience_types)
        if ref_predicates:
            return or_(base, *ref_predicates)
        return base

    if "TEACHER" in roles:
        audience_types.append(AnnouncementAudienceType.TEACHERS)
        return Announcement.audience_type.in_(audience_types)

    # Unknown / staff-less role: only fully public announcements.
    return Announcement.audience_type.in_(audience_types)


def is_announcement_visible(db: DBSession, user: User, announcement: Announcement) -> bool:
    """Row-level check used for detail views."""
    roles = _role_names(user)
    if MANAGEMENT_ROLES & roles:
        return True

    if announcement.audience_type == AnnouncementAudienceType.ALL:
        return True

    if announcement.audience_type == AnnouncementAudienceType.STUDENTS:
        return "STUDENT" in roles

    if announcement.audience_type == AnnouncementAudienceType.TEACHERS:
        return "TEACHER" in roles

    if announcement.audience_type == AnnouncementAudienceType.STAFF:
        return bool(roles - {"STUDENT"})

    student = _student_of(db, user) if "STUDENT" in roles else None
    if student is None:
        return False

    if announcement.audience_type == AnnouncementAudienceType.MAJOR:
        academic = student_academic_snapshot(db, student.id)
        return (
            academic.major_id is not None
            and academic.major_id == announcement.audience_ref_id
        )

    if announcement.audience_type == AnnouncementAudienceType.PROGRAM:
        academic = student_academic_snapshot(db, student.id)
        return (
            academic.program_id is not None
            and academic.program_id == announcement.audience_ref_id
        )

    if announcement.audience_type == AnnouncementAudienceType.CLASS:
        return (
            db.query(Enrollment.id)
            .filter(
                Enrollment.student_id == student.id,
                Enrollment.class_section_id == announcement.audience_ref_id,
                Enrollment.status == EnrollmentStatus.ENROLLED,
            )
            .first()
            is not None
        )

    return False


def list_announcements(
    db: DBSession,
    *,
    user: User,
    locale: str | None = None,
    status_filter: AnnouncementStatus | None = None,
    audience_filter: AnnouncementAudienceType | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Announcement], int]:
    """List announcements the user is allowed to see."""
    query = db.query(Announcement)
    managing = can_manage_announcements(user)

    if managing:
        # Managers may look at drafts and archives, optionally narrowed.
        if status_filter is not None:
            query = query.filter(Announcement.status == status_filter)
    else:
        # Everyone else only ever sees live, non-expired publications.
        now = datetime.now(UTC)
        query = query.filter(
            Announcement.status == AnnouncementStatus.PUBLISHED,
            Announcement.published_at.is_not(None),
            Announcement.published_at <= now,
            or_(Announcement.expires_at.is_(None), Announcement.expires_at > now),
        )

    audience_filter_predicate = visible_audience_filter(db, user)
    if audience_filter_predicate is not None:
        query = query.filter(audience_filter_predicate)

    if audience_filter is not None:
        query = query.filter(Announcement.audience_type == audience_filter)

    if search:
        from app.models.platform import AnnouncementTranslation  # noqa: PLC0415

        pattern = f"%{search.strip()}%"
        query = query.join(
            AnnouncementTranslation,
            AnnouncementTranslation.announcement_id == Announcement.id,
        ).filter(
            or_(
                AnnouncementTranslation.title.ilike(pattern),
                AnnouncementTranslation.body.ilike(pattern),
            )
        )

    total = query.distinct().count()
    items = (
        query.distinct()
        .order_by(
            Announcement.is_pinned.desc(),
            Announcement.published_at.desc().nullslast(),
            Announcement.created_at.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


# --- Mutations -------------------------------------------------------------


def _apply_translations(
    db: DBSession,
    announcement: Announcement,
    translations: list,
) -> None:
    """Replace the translation set, keeping existing rows where possible."""
    existing = {t.locale: t for t in announcement.translations}
    seen: set[str] = set()

    for payload in translations:
        locale = payload.locale.strip().lower()
        seen.add(locale)
        row = existing.get(locale)
        if row is None:
            db.add(
                AnnouncementTranslation(
                    announcement_id=announcement.id,
                    locale=locale,
                    title=payload.title,
                    body=payload.body,
                    summary=payload.summary,
                )
            )
        else:
            row.title = payload.title
            row.body = payload.body
            row.summary = payload.summary

    for locale, row in existing.items():
        if locale not in seen:
            db.delete(row)


def create_announcement(
    db: DBSession,
    *,
    payload: AnnouncementCreate,
    actor: User,
) -> Announcement:
    """Create a draft announcement with its translations."""
    default_locale = payload.default_locale
    if not any(t.locale == default_locale for t in payload.translations):
        default_locale = payload.translations[0].locale

    announcement = Announcement(
        default_locale=default_locale,
        status=AnnouncementStatus.DRAFT,
        priority=payload.priority,
        is_pinned=payload.is_pinned,
        audience_type=payload.audience_type,
        audience_ref_id=payload.audience_ref_id,
        scheduled_at=payload.scheduled_at,
        expires_at=payload.expires_at,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(announcement)
    db.flush()

    _apply_translations(db, announcement, payload.translations)
    db.commit()
    db.refresh(announcement)
    return announcement


def update_announcement(
    db: DBSession,
    *,
    announcement: Announcement,
    payload: AnnouncementUpdate,
    actor: User,
) -> Announcement:
    """Partially update an announcement."""
    data = payload.model_dump(exclude_unset=True)
    translations = data.pop("translations", None)

    for field, value in data.items():
        setattr(announcement, field, value)

    if translations is not None:
        from app.schemas.platform import AnnouncementTranslationInput  # noqa: PLC0415

        _apply_translations(
            db,
            announcement,
            [AnnouncementTranslationInput(**t) for t in translations],
        )

    announcement.updated_by = actor.id
    db.commit()
    db.refresh(announcement)
    return announcement


def publish_announcement(
    db: DBSession, *, announcement: Announcement, actor: User
) -> Announcement:
    """Publish immediately (or validate a scheduled publication)."""
    now = datetime.now(UTC)

    if announcement.scheduled_at and announcement.scheduled_at > now:
        announcement.status = AnnouncementStatus.SCHEDULED
    else:
        announcement.status = AnnouncementStatus.PUBLISHED
        announcement.published_at = now

    announcement.updated_by = actor.id
    db.commit()
    db.refresh(announcement)
    return announcement


def archive_announcement(
    db: DBSession, *, announcement: Announcement, actor: User
) -> Announcement:
    """Archive an announcement. Never hard-deletes institutional content."""
    announcement.status = AnnouncementStatus.ARCHIVED
    announcement.updated_by = actor.id
    db.commit()
    db.refresh(announcement)
    return announcement


def activate_due_scheduled(db: DBSession) -> int:
    """Publish scheduled announcements whose time has arrived.

    Called on the notification/announcement list path so the portal corrects
    itself without needing a background worker.
    """
    now = datetime.now(UTC)
    due = (
        db.query(Announcement)
        .filter(
            Announcement.status == AnnouncementStatus.SCHEDULED,
            Announcement.scheduled_at.is_not(None),
            Announcement.scheduled_at <= now,
        )
        .all()
    )
    for announcement in due:
        announcement.status = AnnouncementStatus.PUBLISHED
        announcement.published_at = now

    if due:
        db.commit()
    return len(due)


__all__ = [
    "activate_due_scheduled",
    "archive_announcement",
    "can_manage_announcements",
    "create_announcement",
    "is_announcement_visible",
    "list_announcements",
    "publish_announcement",
    "resolve_translation",
    "to_list_item",
    "to_response",
    "update_announcement",
    "visible_audience_filter",
]
