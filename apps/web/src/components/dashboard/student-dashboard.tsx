"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowRight,
  Bell,
  BookOpen,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Clock3,
  DoorOpen,
  FileText,
  Globe2,
  Home,
  LifeBuoy,
  Megaphone,
  UserRound,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { getStudentAcademic } from "@/lib/academic-api";
import { examinationApi } from "@/lib/examination-api";
import { getStudentHousing } from "@/lib/housing-api";
import { getStudentImmigration } from "@/lib/immigration-api";
import {
  announcementApi,
  documentApi,
  notificationApi,
} from "@/lib/platform-api";
import { studentApi } from "@/lib/student-api";
import {
  addMonths,
  calendarCells,
  currentOrNextClass,
  dateLabel,
  durationLabel,
  entriesForDate,
  isoDate,
  monthLabel,
  shortDateLabel,
  shanghaiNow,
  timeRangeLabel,
  todayClasses,
  upcomingClasses,
  weekdayInitials,
  type ClassOccurrence,
  type ShanghaiNow,
} from "@/lib/student-dashboard";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import type { StudentExaminationList } from "@/types/examination";
import { useStatusLabel } from "@/lib/use-status-label";
import { cn } from "@/lib/utils";
import type { AnnouncementListResponse, PortalNotification } from "@/types/platform";
import type { StudentDocumentSummary } from "@/types/platform";
import type {
  AcademicPeriod,
  StudentAcademicOverview,
  TimetableEntry,
} from "@/types/academic";
import type { StudentHousingResponse } from "@/types/housing";
import type { ImmigrationProfile } from "@/types/immigration";
import type { StudentDetail } from "@/types/student";
import type { AuthUser } from "@/types/auth";

function useShanghaiNow(): ShanghaiNow | null {
  const [now, setNow] = useState<ShanghaiNow | null>(null);

  useEffect(() => {
    const update = () => setNow(shanghaiNow());
    update();
    const timer = window.setInterval(update, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  return now;
}

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

function classTitle(entry: TimetableEntry): string {
  return entry.course_name ?? entry.course_code ?? "—";
}

function classSection(entry: TimetableEntry): string {
  return [entry.course_code, entry.section_code ?? entry.source_label]
    .filter(Boolean)
    .join(" · ");
}

function classDurationLabel(
  t: ReturnType<typeof useTranslations>,
  minutes: number,
): string {
  const duration = durationLabel(minutes);
  return t(duration.key, duration.values);
}

const EMPTY_TIMETABLE: TimetableEntry[] = [];

function StudentClassRow({
  occurrence,
  locale,
  now,
  onOpen,
}: {
  occurrence: ClassOccurrence;
  locale: string;
  now: ShanghaiNow;
  onOpen: (entry: TimetableEntry) => void;
}) {
  const t = useTranslations("dashboard.student");
  const finished = occurrence.isToday && occurrence.endMinutes <= now.minutes;
  const state = occurrence.isCurrent
    ? t("currentStatus")
    : finished
      ? t("past")
      : t("upcomingStatus");
  const tone = occurrence.isCurrent ? "success" : finished ? "neutral" : "info";

  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(occurrence.entry)}
        className="group flex w-full items-start gap-3 rounded-lg border border-transparent px-2.5 py-3 text-start transition-colors hover:border-border/80 hover:bg-muted/35 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="mt-0.5 flex w-[5.3rem] shrink-0 flex-col gap-0.5">
          <span className="text-[12px] font-semibold tabular-nums">
            {timeRangeLabel(
              locale,
              occurrence.dateIso,
              occurrence.entry.start_time,
              occurrence.entry.end_time,
            )}
          </span>
          <span className="text-[10px] text-muted-foreground">
            {classSection(occurrence.entry)}
          </span>
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">
            {classTitle(occurrence.entry)}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
            {occurrence.entry.classroom_name && (
              <span className="inline-flex items-center gap-1">
                <DoorOpen className="h-3 w-3" aria-hidden="true" />
                {occurrence.entry.classroom_name}
              </span>
            )}
            {occurrence.entry.teacher_names.length > 0 && (
              <span className="truncate">{occurrence.entry.teacher_names.join(", ")}</span>
            )}
          </span>
        </span>
        <StatusBadge tone={tone} className="shrink-0 px-1.5 py-0.5 text-[9px]">
          {state}
        </StatusBadge>
      </button>
    </li>
  );
}

function ClassDetailsDialog({
  entry,
  locale,
  period,
  onOpenChange,
}: {
  entry: TimetableEntry | null;
  locale: string;
  period: AcademicPeriod | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("dashboard.student");
  const tCommon = useTranslations("common");
  const tAcademics = useTranslations("academics");

  return (
    <Dialog open={Boolean(entry)} onOpenChange={onOpenChange}>
      <DialogContent>
        {entry && (
          <>
            <DialogHeader>
              <DialogTitle>{classTitle(entry)}</DialogTitle>
              <DialogDescription>
                {classSection(entry) || t("classDetails")}
              </DialogDescription>
            </DialogHeader>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {t("time")}
                </dt>
                <dd className="mt-1 tabular-nums">
                  {timeRangeLabel(locale, "2024-01-01", entry.start_time, entry.end_time)}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {t("day")}
                </dt>
                <dd className="mt-1">
                  {tAcademics(`days.${["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][entry.day_of_week] ?? "monday"}`)}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {t("classroom")}
                </dt>
                <dd className="mt-1">{entry.classroom_name ?? tCommon("states.notSet")}</dd>
              </div>
              <div>
                <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {t("teacher")}
                </dt>
                <dd className="mt-1">
                  {entry.teacher_names.length > 0
                    ? entry.teacher_names.join(", ")
                    : tCommon("states.notSet")}
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                  {t("period")}
                </dt>
                <dd className="mt-1">
                  {period?.name ?? entry.period_code ?? tCommon("states.notSet")}
                </dd>
              </div>
            </dl>
            <div className="flex justify-end">
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                {tCommon("actions.close")}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function StudentCalendar({
  entries,
  period,
  now,
  onOpen,
}: {
  entries: TimetableEntry[];
  period: AcademicPeriod | null;
  now: ShanghaiNow;
  onOpen: (entry: TimetableEntry) => void;
}) {
  const t = useTranslations("dashboard.student");
  const locale = useLocale();
  const [month, setMonth] = useState(() => {
    const [year, monthIndex] = now.dateIso.split("-").map(Number);
    return { year, monthIndex: monthIndex - 1 };
  });
  const [selectedDate, setSelectedDate] = useState(now.dateIso);

  const cells = useMemo(
    () =>
      calendarCells(
        entries,
        period,
        month.year,
        month.monthIndex,
        now.dateIso,
      ),
    [entries, period, month, now.dateIso],
  );
  const selectedEntries = entriesForDate(entries, selectedDate, period);
  const weekdays = weekdayInitials(locale);

  const changeMonth = (delta: number) => {
    const next = addMonths(month.year, month.monthIndex, delta);
    setMonth(next);
    setSelectedDate(isoDate(next.year, next.monthIndex, 1));
  };

  return (
    <Card className="min-w-0">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">{t("calendar")}</CardTitle>
            <CardDescription className="mt-1 text-[12px]">
              {t("calendarHint")}
            </CardDescription>
          </div>
          <CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        </div>
        <div className="flex items-center justify-between gap-2 pt-2">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => changeMonth(-1)}
            aria-label={t("previousMonth")}
          >
            <ChevronLeft className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          </Button>
          <p className="text-[13px] font-semibold capitalize tabular-nums">
            {monthLabel(locale, month.year, month.monthIndex)}
          </p>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => changeMonth(1)}
            aria-label={t("nextMonth")}
          >
            <ChevronRight className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="grid grid-cols-7 gap-1 text-center text-[10px] font-medium text-muted-foreground">
          {weekdays.map((weekday, index) => (
            <span key={`${weekday}-${index}`} className="py-1">
              {weekday}
            </span>
          ))}
        </div>
        <div className="mt-1 grid grid-cols-7 gap-1" role="grid" aria-label={t("calendar")}>
          {cells.map((cell) => {
            const selected = selectedDate === cell.dateIso;
            const count = entriesForDate(entries, cell.dateIso, period).length;
            return (
              <button
                key={cell.dateIso}
                type="button"
                role="gridcell"
                aria-selected={selected}
                aria-current={cell.isToday ? "date" : undefined}
                aria-label={`${dateLabel(locale, cell.dateIso)} — ${
                  count > 0 ? t("classCount", { count }) : t("noClassesOnDay")
                }`}
                onClick={() => setSelectedDate(cell.dateIso)}
                className={cn(
                  "relative flex h-8 items-center justify-center rounded-md text-[11px] tabular-nums transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  !cell.inMonth && "text-muted-foreground/40",
                  selected
                    ? "bg-primary font-semibold text-primary-foreground"
                    : "hover:bg-accent",
                  cell.isToday && !selected && "font-semibold text-primary ring-1 ring-inset ring-primary/35",
                )}
              >
                {cell.day}
                {cell.hasClass && (
                  <span
                    className={cn(
                      "absolute bottom-1 h-1 w-1 rounded-full",
                      selected ? "bg-primary-foreground" : "bg-primary",
                    )}
                    aria-hidden="true"
                  />
                )}
              </button>
            );
          })}
        </div>
        <div className="mt-2 flex items-center gap-3 text-[10px] text-muted-foreground">
          <span className="inline-flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
            {t("classDayLegend")}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="h-2.5 w-2.5 rounded-sm ring-1 ring-primary/40" aria-hidden="true" />
            {t("todayLegend")}
          </span>
        </div>

        <div className="mt-4 border-t border-border/70 pt-3">
          <p className="text-[12px] font-semibold">
            {t("selectedDay", { date: dateLabel(locale, selectedDate) })}
          </p>
          {selectedEntries.length === 0 ? (
            <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
              {t("noClassesOnDay")}
            </p>
          ) : (
            <ul className="mt-1.5 space-y-1">
              {selectedEntries.map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => onOpen(entry)}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1.5 text-start transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-[11px] font-medium">
                        {classTitle(entry)}
                      </span>
                      <span className="block text-[10px] text-muted-foreground">
                        {entry.start_time.slice(0, 5)}–{entry.end_time.slice(0, 5)}
                        {entry.classroom_name ? ` · ${entry.classroom_name}` : ""}
                      </span>
                    </span>
                    <ArrowRight className="h-3 w-3 shrink-0 text-muted-foreground/60 rtl:rotate-180" aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Essentials({
  studentId,
  canViewAnnouncements,
  canViewNotifications,
  canViewDocuments,
  canViewImmigration,
  canViewHousing,
}: {
  studentId: string | null;
  canViewAnnouncements: boolean;
  canViewNotifications: boolean;
  canViewDocuments: boolean;
  canViewImmigration: boolean;
  canViewHousing: boolean;
}) {
  const t = useTranslations("dashboard.student");
  const locale = useLocale();
  const localizeError = useErrorMessage();

  const announcements = useApi<AnnouncementListResponse | null>(
    () =>
      canViewAnnouncements
        ? announcementApi.list({ locale, page: 1, page_size: 2 })
        : Promise.resolve(null),
    [canViewAnnouncements, locale],
    "student announcements",
  );
  const notifications = useApi<{
    items: PortalNotification[];
    unread_count: number;
  } | null>(
    () =>
      canViewNotifications
        ? notificationApi.list({ page: 1, page_size: 4 })
        : Promise.resolve(null),
    [canViewNotifications],
    "student notifications",
  );
  const documents = useApi<StudentDocumentSummary | null>(
    () =>
      canViewDocuments && studentId
        ? documentApi.summary(studentId)
        : Promise.resolve(null),
    [canViewDocuments, studentId],
    "student documents",
  );
  const immigration = useApi<ImmigrationProfile | null>(
    () =>
      canViewImmigration && studentId
        ? getStudentImmigration(studentId)
        : Promise.resolve(null),
    [canViewImmigration, studentId],
    "student immigration",
  );
  const housing = useApi<StudentHousingResponse | null>(
    () =>
      canViewHousing && studentId
        ? getStudentHousing(studentId)
        : Promise.resolve(null),
    [canViewHousing, studentId],
    "student housing",
  );

  const nearestExpiry = useMemo(() => {
    const profile = immigration.data;
    if (!profile) return null;
    return [
      {
        key: "passport" as const,
        label: t("passport"),
        days: profile.passport_days_remaining,
      },
      {
        key: "visa" as const,
        label: t("visa"),
        days: profile.visa_days_remaining,
      },
      {
        key: "permit" as const,
        label: t("residencePermit"),
        days: profile.residence_permit_days_remaining,
      },
    ]
      .filter((item) => item.days !== null && item.days !== undefined)
      .sort((a, b) => (a.days ?? 0) - (b.days ?? 0))[0] ?? null;
  }, [immigration.data, t]);

  const announcementError = localizeError(announcements.error);
  const notificationError = localizeError(notifications.error);
  const documentError = localizeError(documents.error);
  const immigrationError = localizeError(immigration.error);
  const housingError = localizeError(housing.error);

  const missingDocuments = documents.data?.missing_count ?? null;
  const unread = notifications.data?.unread_count ?? null;
  const assignment = housing.data?.has_assignment ? housing.data.assignment : null;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">{t("essentials")}</CardTitle>
        <CardDescription className="mt-1 text-[12px]">
          {t("essentialsHint")}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-x-6 gap-y-5 pt-0 sm:grid-cols-2">
        <section aria-labelledby="student-announcements">
          <div className="flex items-center justify-between gap-2">
            <h3 id="student-announcements" className="flex items-center gap-1.5 text-[12px] font-semibold">
              <Megaphone className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {t("announcements")}
            </h3>
            <Link href="/app/announcements" className="text-[10px] font-medium text-primary hover:underline">
              {t("openAnnouncements")}
            </Link>
          </div>
          {announcements.loading ? (
            <Skeleton className="mt-2 h-9 w-full" />
          ) : announcements.error ? (
            <p className="mt-2 text-[11px] text-muted-foreground">{announcementError.message}</p>
          ) : (announcements.data?.items.length ?? 0) === 0 ? (
            <p className="mt-2 text-[11px] text-muted-foreground">{t("noAnnouncements")}</p>
          ) : (
            <ul className="mt-2 space-y-1.5">
              {announcements.data?.items.map((item) => (
                <li key={item.id}>
                  <Link
                    href={`/app/announcements/${item.id}`}
                    className="line-clamp-2 text-[11px] leading-snug text-muted-foreground hover:text-primary hover:underline"
                  >
                    {item.title}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section aria-labelledby="student-notifications">
          <div className="flex items-center justify-between gap-2">
            <h3 id="student-notifications" className="flex items-center gap-1.5 text-[12px] font-semibold">
              <Bell className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {t("notifications")}
            </h3>
            <Link href="/app/notifications" className="text-[10px] font-medium text-primary hover:underline">
              {t("openNotifications")}
            </Link>
          </div>
          {notifications.loading ? (
            <Skeleton className="mt-2 h-5 w-24" />
          ) : notifications.error ? (
            <p className="mt-2 text-[11px] text-muted-foreground">{notificationError.message}</p>
          ) : unread && unread > 0 ? (
            <p className="mt-2 text-sm font-semibold tabular-nums">
              {t("unread", { count: unread })}
            </p>
          ) : (
            <p className="mt-2 text-[11px] text-muted-foreground">{t("noNotifications")}</p>
          )}
        </section>

        <section aria-labelledby="student-documents">
          <div className="flex items-center justify-between gap-2">
            <h3 id="student-documents" className="flex items-center gap-1.5 text-[12px] font-semibold">
              <FileText className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {t("documents")}
            </h3>
            <Link href="/app/documents" className="text-[10px] font-medium text-primary hover:underline">
              {t("openDocuments")}
            </Link>
          </div>
          {documents.loading ? (
            <Skeleton className="mt-2 h-5 w-28" />
          ) : documents.error ? (
            <p className="mt-2 text-[11px] text-muted-foreground">{documentError.message}</p>
          ) : missingDocuments && missingDocuments > 0 ? (
            <p className="mt-2 text-[11px] leading-snug text-warning">
              {t("documentsMissing", { count: missingDocuments })}
            </p>
          ) : (
            <p className="mt-2 text-[11px] text-muted-foreground">{t("documentsComplete")}</p>
          )}
        </section>

        <section aria-labelledby="student-immigration">
          <div className="flex items-center justify-between gap-2">
            <h3 id="student-immigration" className="flex items-center gap-1.5 text-[12px] font-semibold">
              <Globe2 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {t("immigration")}
            </h3>
            <Link href="/app/profile" className="text-[10px] font-medium text-primary hover:underline">
              {t("viewProfile")}
            </Link>
          </div>
          {immigration.loading ? (
            <Skeleton className="mt-2 h-5 w-32" />
          ) : immigration.error ? (
            <p className="mt-2 text-[11px] text-muted-foreground">{immigrationError.message}</p>
          ) : nearestExpiry ? (
            <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
              {nearestExpiry.label}:{" "}
              <span className={cn("font-medium", (nearestExpiry.days ?? 0) < 0 ? "text-destructive" : (nearestExpiry.days ?? 0) <= 30 ? "text-warning" : "text-foreground")}>
                {nearestExpiry.days !== null && nearestExpiry.days !== undefined
                  ? nearestExpiry.days >= 0
                    ? t("daysRemaining", { count: nearestExpiry.days })
                    : t("expired")
                  : t("noImmigration")}
              </span>
            </p>
          ) : (
            <p className="mt-2 text-[11px] text-muted-foreground">{t("noImmigration")}</p>
          )}
        </section>

        <section aria-labelledby="student-housing">
          <div className="flex items-center justify-between gap-2">
            <h3 id="student-housing" className="flex items-center gap-1.5 text-[12px] font-semibold">
              <Home className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {t("housing")}
            </h3>
            <Link href="/app/profile" className="text-[10px] font-medium text-primary hover:underline">
              {t("viewProfile")}
            </Link>
          </div>
          {housing.loading ? (
            <Skeleton className="mt-2 h-5 w-32" />
          ) : housing.error ? (
            <p className="mt-2 text-[11px] text-muted-foreground">{housingError.message}</p>
          ) : assignment ? (
            <p className="mt-2 text-[11px] leading-snug text-muted-foreground">
              {[assignment.building_name, assignment.room_number].filter(Boolean).join(" · ")}
            </p>
          ) : (
            <p className="mt-2 text-[11px] text-muted-foreground">{t("noHousing")}</p>
          )}
        </section>

        <section aria-labelledby="student-support">
          <div className="flex items-center justify-between gap-2">
            <h3 id="student-support" className="flex items-center gap-1.5 text-[12px] font-semibold">
              <LifeBuoy className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
              {t("support")}
            </h3>
            <Link href="/app/support" className="text-[10px] font-medium text-primary hover:underline">
              {t("openSupport")}
            </Link>
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
            {t("supportHint")}
          </p>
        </section>
      </CardContent>
    </Card>
  );
}

function DashboardError({
  kind,
  refetch,
}: {
  kind: string;
  refetch: () => void;
}) {
  const t = useTranslations("errors");
  return (
    <div className="space-y-4">
      <ErrorState
        title={
          kind === "unauthorized"
            ? t("unauthorized")
            : kind === "forbidden"
              ? t("forbidden")
              : t("serverError")
        }
        hint={
          kind === "unauthorized"
            ? t("unauthorizedHint")
            : kind === "forbidden"
              ? t("forbiddenHint")
              : t("serverErrorHint")
        }
        onRetry={kind === "forbidden" || kind === "unauthorized" ? undefined : refetch}
      />
      <div className="flex justify-center gap-2">
        {kind === "unauthorized" ? (
          <Button asChild size="sm">
            <Link href="/login">{t("retry")}</Link>
          </Button>
        ) : (
          <Button asChild variant="outline" size="sm">
            <Link href="/app">{t("backToDashboard")}</Link>
          </Button>
        )}
      </div>
    </div>
  );
}

export function StudentDashboard({ user }: { user: AuthUser }) {
  const t = useTranslations("dashboard.student");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const { hasPermission } = useAuth();
  const statusLabel = useStatusLabel();
  const now = useShanghaiNow();
  const [selectedEntry, setSelectedEntry] = useState<TimetableEntry | null>(null);

  const student = useApi<StudentDetail>(
    () => studentApi.getMyStudent(),
    [],
    "student dashboard identity",
  );
  const academic = useApi<StudentAcademicOverview | null>(
    () =>
      student.data
        ? getStudentAcademic(student.data.id)
        : Promise.resolve(null),
    [student.data?.id],
    "student dashboard timetable",
  );
  // The examination schedule is part of the student's academic week, so it is
  // surfaced here rather than only behind a separate page. The server decides
  // what is visible; an unpublished result simply does not arrive.
  const canViewExams = hasPermission("exams.view");
  const tExams = useTranslations("examinations");
  const exams = useApi<StudentExaminationList | null>(
    () => (canViewExams ? examinationApi.mine() : Promise.resolve(null)),
    [canViewExams],
    "student dashboard examinations",
  );
  const upcomingExams = (exams.data?.items ?? [])
    .filter((item) => !item.is_past && item.status !== "CANCELLED")
    .slice(0, 3);

  const period = academic.data?.selected_period ?? academic.data?.current_period ?? null;
  const entries = academic.data?.timetable ?? EMPTY_TIMETABLE;
  const firstName = student.data?.preferred_name || student.data?.first_name || user.full_name.split(" ")[0] || user.full_name;
  const fullName = student.data
    ? `${student.data.first_name} ${student.data.last_name}`
    : user.full_name;
  const programOfferingName = academic.data?.program_offering?.name
    ?? student.data?.program_offering_name
    ?? null;
  const program = academic.data?.program?.name ?? student.data?.program_name ?? null;
  const major = academic.data?.major?.name ?? student.data?.major_name ?? null;
  const academicLine = [programOfferingName, program, major].filter(Boolean).join(" · ");
  const studentStatusLabel = student.data?.status
    ? statusLabel(student.data.status, "students.status")
    : tCommon("states.notSet");

  const next = useMemo(
    () => (now ? currentOrNextClass(entries, period, now) : null),
    [entries, period, now],
  );
  const today = useMemo(
    () => (now ? todayClasses(entries, period, now) : []),
    [entries, period, now],
  );
  const upcoming = useMemo(
    () => (now ? upcomingClasses(entries, period, now, 5) : []),
    [entries, period, now],
  );

  if (student.loading || !now) {
    return (
      <AppShell>
        <div className="space-y-4" aria-busy="true" aria-live="polite">
          <span className="sr-only">{t("loading")}</span>
          <Skeleton className="h-36 w-full rounded-2xl" />
          <div className="grid gap-4 lg:grid-cols-[1.15fr_0.85fr]">
            <Skeleton className="h-60 rounded-xl" />
            <Skeleton className="h-60 rounded-xl" />
          </div>
          <Skeleton className="h-48 w-full rounded-xl" />
        </div>
      </AppShell>
    );
  }

  if (student.error || !student.data) {
    return (
      <AppShell>
        <DashboardError kind={student.error?.kind ?? "unknown"} refetch={student.refetch} />
      </AppShell>
    );
  }

  const studentRecord = student.data;
  const timetableHref = `/app/students/${studentRecord.id}?tab=timetable`;
  const profileHref = `/app/profile`;
  const noMoreToday = next === null || next.dateIso > now.dateIso;

  return (
    <AppShell>
      <section className="scu-hero-panel motion-hero relative mb-4 overflow-hidden px-5 py-5 sm:px-7 sm:py-6">
        <div className="institutional-grid absolute inset-0 opacity-50" aria-hidden="true" />
        <div className="motion-ambient" aria-hidden="true">
          <div className="motion-ambient__glow motion-ambient__glow--one" />
          <div className="motion-ambient__glow motion-ambient__glow--two" />
        </div>
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-3.5">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-white/20 bg-white/10 text-sm font-semibold tracking-wide text-white">
              {initialsOf(fullName) || <UserRound className="h-5 w-5" />}
            </span>
            <div className="min-w-0">
              <h1 className="motion-title text-[1.55rem] font-semibold leading-tight tracking-[-0.03em] sm:text-[1.8rem]">
                {t("welcome", { name: firstName })}
              </h1>
              <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                {t("welcomeHint")}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
                <span className="font-mono text-foreground/80">{studentRecord.student_id}</span>
                {academicLine && <span className="truncate">{academicLine}</span>}
                {period && <span className="truncate">{t("intake")}: {period.name}</span>}
                <Badge className="border-border bg-muted/60 text-[9px] uppercase tracking-wide text-muted-foreground hover:bg-muted/60">
                  {studentStatusLabel}
                </Badge>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={timetableHref}
              className="inline-flex h-9 items-center gap-2 rounded-full bg-primary px-3.5 text-[12px] font-semibold text-primary-foreground shadow-[0_12px_24px_-16px_hsl(var(--primary)/0.9)] transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("fullTimetable")}
              <ArrowRight className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden="true" />
            </Link>
            <Link
              href={profileHref}
              className="inline-flex h-9 items-center gap-2 rounded-full border border-border bg-card/60 px-3.5 text-[12px] font-medium text-foreground backdrop-blur-xl transition-colors hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("viewProfile")}
            </Link>
          </div>
        </div>
      </section>

      <div className="motion-grid mb-4 grid gap-4 lg:grid-cols-[1.15fr_0.85fr] lg:items-start">
        <Card className="min-w-0 overflow-hidden border-primary/20 lg:col-start-1 lg:row-start-1">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                  {t("nextClass")}
                </p>
                <CardTitle className="mt-1 text-xl">
                  {next ? classTitle(next.entry) : t("noClassesToday")}
                </CardTitle>
              </div>
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Clock3 className="h-5 w-5" aria-hidden="true" />
              </span>
            </div>
          </CardHeader>
          <CardContent className="pt-1">
            {next ? (
              <>
                <p className="text-[12px] text-muted-foreground">
                  {next.isCurrent
                    ? t("endsIn", {
                        duration: classDurationLabel(t, Math.max(0, next.minutesUntilEnd)),
                      })
                    : next.isToday
                      ? t("startsIn", {
                          duration: classDurationLabel(t, Math.max(0, next.minutesUntilStart)),
                        })
                      : t("nextClassOn", { date: shortDateLabel(locale, next.dateIso) })}
                  {next.isCurrent && ` · ${t("inProgress")}`}
                </p>
                <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[12px] sm:grid-cols-4">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">{t("time")}</p>
                    <p className="mt-0.5 font-medium tabular-nums" dir="ltr">
                      {timeRangeLabel(locale, next.dateIso, next.entry.start_time, next.entry.end_time)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">{t("classroom")}</p>
                    <p className="mt-0.5 font-medium">{next.entry.classroom_name ?? tCommon("states.notSet")}</p>
                  </div>
                  <div className="col-span-2">
                    <p className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">{t("teacher")}</p>
                    <p className="mt-0.5 truncate font-medium">
                      {next.entry.teacher_names.join(", ") || tCommon("states.notSet")}
                    </p>
                  </div>
                </div>
              </>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">{t("noClassesTodayHint")}</p>
            )}
            <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border/70 pt-3">
              <p className="text-[10px] text-muted-foreground">{t("timezoneHint")}</p>
              <div className="flex items-center gap-2">
                {noMoreToday && next && (
                  <span className="text-[10px] font-medium text-muted-foreground">{t("noMoreToday")}</span>
                )}
                <Button variant="ghost" size="sm" asChild className="h-8 px-2 text-[11px]">
                  <Link href={timetableHref}>
                    {t("fullTimetable")}
                    <ArrowRight className="ms-1 h-3 w-3 rtl:rotate-180" aria-hidden="true" />
                  </Link>
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="min-w-0 lg:col-start-2 lg:row-span-3 lg:row-start-1">
          <StudentCalendar
            entries={entries}
            period={period}
            now={now}
            onOpen={setSelectedEntry}
          />
        </div>

        <Card className="min-w-0 lg:col-start-1 lg:row-start-2">
          <CardHeader className="pb-1">
            <div className="flex items-start justify-between gap-2">
              <div>
                <CardTitle className="text-base">{t("todayClasses")}</CardTitle>
                <CardDescription className="mt-1 text-[12px]">
                  {t("todayHint", { date: dateLabel(locale, now.dateIso) })}
                </CardDescription>
              </div>
              <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium tabular-nums text-muted-foreground">
                {t("classCount", { count: today.length })}
              </span>
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            {today.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border/80 bg-muted/15 px-4 py-6 text-center">
                <BookOpen className="mx-auto h-5 w-5 text-muted-foreground" aria-hidden="true" />
                <p className="mt-2 text-[12px] font-medium">{t("noClassesToday")}</p>
                <p className="mt-1 text-[11px] text-muted-foreground">{t("noClassesTodayHint")}</p>
              </div>
            ) : (
              <ul className="divide-y divide-border/60">
                {today.map((occurrence) => (
                  <StudentClassRow
                    key={occurrence.entry.id}
                    occurrence={occurrence}
                    locale={locale}
                    now={now}
                    onOpen={setSelectedEntry}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card className="min-w-0 lg:col-start-1 lg:row-start-3">
          <CardHeader className="pb-1">
            <div className="flex items-start justify-between gap-2">
              <div>
                <CardTitle className="text-base">{t("upcoming")}</CardTitle>
                <CardDescription className="mt-1 text-[12px]">{t("upcomingHint")}</CardDescription>
              </div>
              <Button variant="ghost" size="sm" asChild className="h-8 px-2 text-[11px]">
                <Link href={timetableHref}>
                  {t("fullTimetable")}
                  <ArrowRight className="ms-1 h-3 w-3 rtl:rotate-180" aria-hidden="true" />
                </Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            {upcoming.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border/80 bg-muted/15 px-3 py-5 text-center text-[11px] text-muted-foreground">
                {t("noUpcoming")}
              </p>
            ) : (
              <ol className="space-y-1.5">
                {upcoming.map((occurrence) => (
                  <li key={`${occurrence.entry.id}-${occurrence.dateIso}`}>
                    <button
                      type="button"
                      onClick={() => setSelectedEntry(occurrence.entry)}
                      className="group flex w-full items-start gap-2.5 rounded-lg px-1.5 py-2 text-start transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <span className="mt-0.5 w-[4.6rem] shrink-0 text-[10px] font-medium tabular-nums text-muted-foreground">
                        {shortDateLabel(locale, occurrence.dateIso)}
                        <span className="mt-0.5 block text-[10px]">
                          {occurrence.entry.start_time.slice(0, 5)}
                        </span>
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12px] font-medium">
                          {classTitle(occurrence.entry)}
                        </span>
                        <span className="mt-0.5 block truncate text-[10px] text-muted-foreground">
                          {occurrence.entry.classroom_name ?? tCommon("states.notSet")}
                          {occurrence.entry.teacher_names.length > 0
                            ? ` · ${occurrence.entry.teacher_names.join(", ")}`
                            : ""}
                        </span>
                      </span>
                      <ArrowRight className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-transform group-hover:translate-x-0.5 rtl:rotate-180 rtl:group-hover:-translate-x-0.5" aria-hidden="true" />
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>

      {canViewExams && (
        <Card className="mb-4">
          <CardHeader className="pb-1">
            <div className="flex items-start justify-between gap-2">
              <div>
                <CardTitle className="text-base">
                  {tExams("dashboardTitle")}
                </CardTitle>
                <CardDescription className="mt-1 text-[12px]">
                  {tExams("dashboardHint")}
                </CardDescription>
              </div>
              <Button variant="ghost" size="sm" asChild className="h-8 px-2 text-[11px]">
                <Link href="/app/examinations">
                  {tExams("myTitle")}
                  <ArrowRight className="ms-1 h-3 w-3 rtl:rotate-180" aria-hidden="true" />
                </Link>
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-2">
            {exams.loading ? (
              <p className="px-1 py-4 text-[11px] text-muted-foreground">
                {tCommon("states.loading")}
              </p>
            ) : upcomingExams.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border/80 bg-muted/15 px-3 py-5 text-center text-[11px] text-muted-foreground">
                {tExams("dashboardEmpty")}
              </p>
            ) : (
              <ul className="divide-y divide-border/60">
                {upcomingExams.map((item) => (
                  <li
                    key={item.id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1 py-2.5 text-[12px]"
                  >
                    <span className="w-[4.6rem] shrink-0 text-[10px] font-medium tabular-nums text-muted-foreground">
                      {shortDateLabel(locale, item.exam_date)}
                      <span className="mt-0.5 block">{item.start_time.slice(0, 5)}</span>
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">
                        {item.course_code
                          ? `${item.course_code} · ${item.title}`
                          : item.title}
                      </span>
                      <span className="mt-0.5 block truncate text-[10px] text-muted-foreground">
                        {item.location ?? tExams("noLocation")}
                      </span>
                    </span>
                    {item.result && (
                      <StatusBadge tone="success">{tExams("published")}</StatusBadge>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      {academic.error && (
        <Card className="mb-4">
          <CardContent className="pt-5">
            <ErrorState
              title={t("academicUnavailable")}
              hint={t("academicUnavailableHint")}
              onRetry={academic.refetch}
            />
          </CardContent>
        </Card>
      )}

      <Essentials
        studentId={studentRecord.id}
        canViewAnnouncements={hasPermission("announcement.view")}
        canViewNotifications={hasPermission("notifications.view")}
        canViewDocuments={hasPermission("documents.view")}
        canViewImmigration={hasPermission("immigration.view")}
        canViewHousing={hasPermission("housing.view")}
      />

      <ClassDetailsDialog
        entry={selectedEntry}
        locale={locale}
        period={period}
        onOpenChange={(open) => {
          if (!open) setSelectedEntry(null);
        }}
      />
    </AppShell>
  );
}
