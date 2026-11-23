"use client";

import { useCallback, type CSSProperties } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  ArrowRight,
  ArrowUpRight,
  BedDouble,
  BookOpenCheck,
  Building2,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileWarning,
  Globe2,
  GraduationCap,
  Layers3,
  ShieldCheck,
  TicketCheck,
  TriangleAlert,
  UserRoundCheck,
  Users,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { auditApi, reportApi } from "@/lib/platform-api";
import { getHousingOverview } from "@/lib/housing-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { AppShell } from "@/components/layout/app-shell";
import { ScuMark } from "@/components/brand/scu-mark";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/ui/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/error-state";
import { StudentDashboard } from "@/components/dashboard/student-dashboard";
import { CountUp } from "@/components/motion/count-up";
import { NAV_SECTIONS } from "@/lib/navigation";
import { cn } from "@/lib/utils";
import type {
  AuditLogListResponse,
  OperationsReport,
} from "@/types/platform";
import type { HousingOverviewResponse } from "@/types/housing";

const MODULE_KEYS = Object.fromEntries(
  NAV_SECTIONS.flatMap((section) => section.items)
    .filter((item) => item.href)
    .map((item) => [item.href as string, item.labelKey]),
);

function percent(value: number, total: number) {
  if (total <= 0 || value <= 0) return 0;
  // A nonzero share is never rendered as 0%: with 1,212 beds, five residents
  // round to zero and the dashboard would falsely look empty.
  return Math.max(1, Math.round((value / total) * 100));
}

function initialsOf(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function OperationsMetric({
  label,
  value,
  hint,
  icon,
  tone = "default",
}: {
  label: string;
  value: number;
  hint: string;
  icon: React.ReactNode;
  tone?: "default" | "success" | "warning" | "info";
}) {
  const toneClass = {
    default: "bg-primary/10 text-primary",
    success: "bg-success-soft text-success",
    warning: "bg-warning-soft text-warning",
    info: "bg-info-soft text-info",
  }[tone];

  return (
    <div className="min-w-0 bg-card px-4 py-4 sm:px-5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[9px] font-semibold uppercase leading-[1.3] tracking-[0.11em] text-muted-foreground">
          {label}
        </p>
        <span className={cn("flex h-7 w-7 shrink-0 items-center justify-center rounded-md", toneClass)}>
          {icon}
        </span>
      </div>
      <p className="mt-2.5 text-2xl font-semibold leading-none tracking-[-0.04em] tabular-nums">
        <CountUp value={value} />
      </p>
      <p className="mt-1.5 truncate text-[11px] text-muted-foreground">{hint}</p>
    </div>
  );
}

export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const tReports = useTranslations("reports");
  const tNav = useTranslations("navigation");
  const tCommon = useTranslations("common");
  const tAudit = useTranslations("audit");
  const locale = useLocale();
  const { user, hasPermission, isLoading } = useAuth();
  const localizeError = useErrorMessage();

  const canViewReports = hasPermission("reports.view");
  const canViewAudit = hasPermission("audit.view");
  const canViewHousing = hasPermission("housing.view_all");

  const fetchReport = useCallback(
    () => (canViewReports ? reportApi.overview() : Promise.resolve(null)),
    [canViewReports],
  );
  const {
    data: report,
    loading: reportLoading,
    error: reportError,
    refetch: refetchReport,
  } = useApi<OperationsReport | null>(
    fetchReport,
    [canViewReports],
    "dashboard overview",
  );

  const fetchActivity = useCallback(
    () =>
      canViewAudit
        ? auditApi.list({ page: 1, page_size: 6 })
        : Promise.resolve(null),
    [canViewAudit],
  );
  const activity = useApi<AuditLogListResponse | null>(
    fetchActivity,
    [canViewAudit],
    "dashboard activity",
  );

  const fetchEstate = useCallback(
    () =>
      canViewHousing
        ? getHousingOverview()
        : Promise.resolve(null),
    [canViewHousing],
  );
  const estate = useApi<HousingOverviewResponse | null>(
    fetchEstate,
    [canViewHousing],
    "dashboard housing estate",
  );

  if (isLoading) {
    return (
      <AppShell>
        <div className="space-y-4">
          <Skeleton className="h-48 w-full rounded-2xl" />
          <Skeleton className="h-28 w-full rounded-xl" />
          <div className="grid gap-4 lg:grid-cols-3">
            <Skeleton className="h-72 rounded-xl lg:col-span-2" />
            <Skeleton className="h-72 rounded-xl" />
          </div>
        </div>
      </AppShell>
    );
  }

  if (!user) {
    return <AppShell>{null}</AppShell>;
  }

  const roles: string[] = user.roles.map((role) => role.name);

  // Students get a personal, timetable-led home rather than the institutional
  // operations dashboard. Staff and teacher roles continue below unchanged.
  if (roles.includes("STUDENT")) {
    return <StudentDashboard user={user} />;
  }

  const modules = NAV_SECTIONS.flatMap((section) => section.items).filter(
    (item) =>
      item.href &&
      !item.comingSoon &&
      item.href !== "/app" &&
      (!item.permission || hasPermission(item.permission)) &&
      !item.hiddenForRoles?.some((role) => roles.includes(role)) &&
      (!item.visibleForRoles ||
        item.visibleForRoles.some((role) => roles.includes(role))),
  );

  const firstName = user.full_name.split(" ")[0] ?? user.full_name;
  const today = new Intl.DateTimeFormat(locale, {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date());

  const statusRows = report
    ? [
        {
          label: tReports("metrics.activeStudents"),
          value: report.students.active,
          color: "hsl(var(--success))",
          className: "bg-success",
        },
        {
          label: tReports("metrics.inactiveStudents"),
          value: report.students.inactive,
          color: "hsl(var(--muted-foreground))",
          className: "bg-muted-foreground/60",
        },
        {
          label: tReports("metrics.graduated"),
          value: report.students.graduated,
          color: "hsl(var(--info))",
          className: "bg-info",
        },
        {
          label: tReports("metrics.withdrawn"),
          value: report.students.withdrawn,
          color: "hsl(var(--warning))",
          className: "bg-warning",
        },
        {
          label: tReports("metrics.suspended"),
          value: report.students.suspended,
          color: "hsl(var(--destructive))",
          className: "bg-destructive",
        },
      ]
    : [];
  const statusTotal = statusRows.reduce((sum, row) => sum + row.value, 0);
  const statusGradient = (() => {
    if (statusTotal <= 0) return "hsl(var(--muted))";
    let cursor = 0;
    return `conic-gradient(${statusRows
      .map((row) => {
        const start = cursor;
        cursor += (row.value / statusTotal) * 100;
        return `${row.color} ${start}% ${cursor}%`;
      })
      .join(", ")})`;
  })();

  const immigration = report?.immigration;
  const immigrationTotal = immigration?.total_students ?? 0;
  const housing = report?.housing;
  const occupancy = housing ? percent(housing.occupied_beds, housing.total_beds) : 0;
  const activeRate = report ? percent(report.students.active, report.students.total) : 0;
  const estateBuildings = (estate.data?.buildings ?? []).slice(0, 8);

  const attentionItems = report
    ? [
        {
          label: t("expired"),
          hint: tReports("sections.immigrationExpiry"),
          value: report.immigration.expired,
          href: hasPermission("immigration.view_all") ? "/app/immigration" : null,
          tone: "danger" as const,
          icon: FileWarning,
        },
        {
          label: t("within30"),
          hint: tReports("metrics.expiring30"),
          value: report.immigration.expiring_30_days,
          href: hasPermission("immigration.view_all") ? "/app/immigration" : null,
          tone: "warning" as const,
          icon: TriangleAlert,
        },
        {
          label: t("pendingRequests"),
          hint: tReports("metrics.pendingChangeRequests"),
          value: report.immigration.pending_change_requests,
          href: hasPermission("immigration.view_all") ? "/app/immigration" : null,
          tone: "info" as const,
          icon: Clock3,
        },
        {
          label: t("missingProfiles"),
          hint: tReports("metrics.missingInformation"),
          value: report.immigration.missing_information,
          href: hasPermission("immigration.view_all") ? "/app/immigration" : null,
          tone: "warning" as const,
          icon: Globe2,
        },
        {
          label: t("supportQueue"),
          hint: tReports("metrics.openTickets"),
          value: report.open_support_tickets,
          href: hasPermission("support.view") ? "/app/support" : null,
          tone: "info" as const,
          icon: TicketCheck,
        },
        {
          label: tReports("metrics.outOfServiceRooms"),
          hint: tReports("sections.housingOccupancy"),
          value: report.housing.rooms_out_of_service,
          href: hasPermission("housing.view_all") ? "/app/housing" : null,
          tone: "warning" as const,
          icon: Building2,
        },
      ].filter((item) => item.value > 0)
    : [];

  const runway = immigration
    ? [
        {
          label: t("expiring90"),
          value: immigration.expiring_90_days,
          color: "bg-info",
        },
        {
          label: t("within30"),
          value: immigration.expiring_30_days,
          color: "bg-warning",
        },
        {
          label: t("expired"),
          value: immigration.expired,
          color: "bg-destructive",
        },
        {
          label: t("missingInformation"),
          value: immigration.missing_information,
          color: "bg-muted-foreground/60",
        },
      ]
    : [];

  const actionLabel = (value: string) =>
    tAudit.has(`actions.${value}`)
      ? tAudit(`actions.${value}`)
      : value.replace(/[._]/g, " ");

  const academicRows = report
    ? [
        { label: t("activePeriods"), value: report.academics.active_periods, Icon: CalendarDays },
        { label: t("enrollments"), value: report.academics.total_enrollments, Icon: UserRoundCheck },
        { label: t("classes"), value: report.academics.total_classes, Icon: Layers3 },
        { label: t("courses"), value: report.academics.total_courses, Icon: BookOpenCheck },
        {
          label: t("teacherAssignments"),
          value: report.academics.total_teacher_assignments,
          Icon: GraduationCap,
        },
        { label: t("programs"), value: report.academics.total_programs, Icon: Layers3 },
        { label: t("majors"), value: report.academics.total_majors, Icon: BookOpenCheck },
      ]
    : [];

  return (
    <AppShell>
      <section className="scu-hero-panel motion-hero relative mb-5 overflow-hidden">
        <div className="institutional-contours absolute inset-0 opacity-80" aria-hidden="true" />
        <div className="institutional-grid absolute inset-0 opacity-40" aria-hidden="true" />
        <div className="motion-ambient" aria-hidden="true">
          <div className="motion-ambient__glow motion-ambient__glow--one" />
          <div className="motion-ambient__glow motion-ambient__glow--two" />
        </div>
        <div
          className="absolute -end-16 -top-28 h-80 w-80 rounded-full border border-white/[0.06]"
          aria-hidden="true"
        />
        <ScuMark className="absolute -end-3 bottom-[-5.2rem] hidden h-72 w-72 opacity-[0.08] brightness-0 invert lg:block" />

        <div className="relative grid gap-7 p-6 sm:p-8 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div className="min-w-0 max-w-3xl">
            <p className="flex items-center gap-2.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-gold">
              <span className="h-px w-7 bg-gold/70" aria-hidden="true" />
              {canViewReports ? t("commandCenter") : t("personalView")}
            </p>
            <h1 className="motion-title mt-3 text-balance text-[1.8rem] font-semibold leading-tight tracking-[-0.03em] sm:text-[2.15rem]">
              {t("welcome", { name: firstName })}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              {canViewReports ? t("operationsHint") : t("noReportHint")}
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-2">
              {user.roles.map((role) => (
                <Badge
                  key={role.id}
                  className="rounded-full border border-border bg-muted/60 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground hover:bg-muted/60"
                >
                  {role.name}
                </Badge>
              ))}
              <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
                {today}
              </span>
              {report && (
                <span className="flex items-center gap-1.5 rounded-full border border-success-bright/25 bg-success-bright/10 px-2.5 py-1 text-[10px] font-medium text-success-bright">
                  <span className="h-1.5 w-1.5 rounded-full bg-success-bright" aria-hidden="true" />
                  {t("operational")}
                </span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 lg:justify-end">
            {hasPermission("reports.view") && (
              <Link
                href="/app/reports"
                className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-4 text-[13px] font-semibold text-primary-foreground shadow-[0_12px_24px_-16px_hsl(var(--primary)/0.9)] transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t("viewReports")}
                <ArrowUpRight className="h-4 w-4 rtl:rotate-90" aria-hidden="true" />
              </Link>
            )}
            <Link
              href={
                hasPermission("student.view") && !roles.includes("STUDENT")
                  ? "/app/students"
                  : "/app/profile"
              }
              className="inline-flex h-10 items-center gap-2 rounded-full border border-border bg-card/60 px-4 text-[13px] font-medium text-foreground backdrop-blur-xl transition-colors hover:bg-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {hasPermission("student.view") && !roles.includes("STUDENT")
                ? t("actions.browseStudents")
                : tNav("myProfile")}
              <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>

      {canViewReports && reportLoading && (
        <div className="mb-5 space-y-4">
          <Skeleton className="h-28 w-full rounded-xl" />
          <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <Skeleton className="h-72 rounded-xl" />
            <Skeleton className="h-72 rounded-xl" />
          </div>
        </div>
      )}

      {canViewReports && reportError && (
        <Card className="mb-5">
          <CardContent className="pt-5">
            <ErrorState
              title={t("dataUnavailable")}
              hint={localizeError(reportError).message}
              onRetry={refetchReport}
            />
          </CardContent>
        </Card>
      )}

      {canViewReports && report && (
        <section aria-labelledby="operations-heading" className="mb-7">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2
                id="operations-heading"
                className="text-lg font-semibold tracking-[-0.02em]"
              >
                {t("operations")}
              </h2>
              <p className="mt-0.5 text-[13px] text-muted-foreground">
                {t("asOf", { date: today })}
              </p>
            </div>
            <span className="text-[11px] text-muted-foreground">
              {t("currentScope")}
            </span>
          </div>

          <div className="motion-kpis mb-4 grid gap-px overflow-hidden rounded-xl border border-border/80 bg-border/80 shadow-card sm:grid-cols-2 xl:grid-cols-5">
            <OperationsMetric
              label={tReports("metrics.totalStudents")}
              value={report.students.total}
              hint={t("ofTotal", { percent: 100 })}
              icon={<Users className="h-3.5 w-3.5" aria-hidden="true" />}
            />
            <OperationsMetric
              label={t("activeCohort")}
              value={report.students.active}
              hint={t("ofTotal", { percent: activeRate })}
              tone="success"
              icon={<UserRoundCheck className="h-3.5 w-3.5" aria-hidden="true" />}
            />
            <OperationsMetric
              label={t("within30")}
              value={report.immigration.expiring_30_days}
              hint={t("ofCohort", {
                percent: percent(report.immigration.expiring_30_days, immigrationTotal),
              })}
              tone="warning"
              icon={<Globe2 className="h-3.5 w-3.5" aria-hidden="true" />}
            />
            <OperationsMetric
              label={t("availableBeds")}
              value={report.housing.available_beds}
              hint={tReports("sections.housingOccupancy")}
              tone="info"
              icon={<BedDouble className="h-3.5 w-3.5" aria-hidden="true" />}
            />
            <OperationsMetric
              label={t("activePeriods")}
              value={report.academics.active_periods}
              hint={t("activePeriodsHint")}
              icon={<BookOpenCheck className="h-3.5 w-3.5" aria-hidden="true" />}
            />
          </div>

          <div className="motion-grid grid gap-4 xl:grid-cols-12">
            <Card className="xl:col-span-5">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">{t("studentMix")}</CardTitle>
                <CardDescription className="text-[13px]">
                  {t("studentMixHint")}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center gap-6 sm:flex-row">
                  <div
                    className="motion-donut relative flex h-40 w-40 shrink-0 items-center justify-center rounded-full"
                    style={{ background: statusGradient }}
                    role="img"
                    aria-label={t("studentMix")}
                  >
                    <div className="flex h-[6.8rem] w-[6.8rem] flex-col items-center justify-center rounded-full bg-card shadow-sm">
                      <span className="text-[1.75rem] font-semibold leading-none tracking-[-0.04em] tabular-nums">
                        <CountUp value={report.students.total} />
                      </span>
                      <span className="mt-1.5 text-[9px] font-medium uppercase tracking-[0.13em] text-muted-foreground">
                        {tCommon("labels.total")}
                      </span>
                    </div>
                  </div>
                  <ul className="w-full min-w-0 flex-1 space-y-2.5">
                    {statusRows.map((row, index) => {
                      const share = percent(row.value, statusTotal);
                      return (
                        <li key={row.label}>
                          <div className="flex items-center justify-between gap-3">
                            <span className="flex min-w-0 items-center gap-2 text-xs">
                              <span
                                className={cn("h-2 w-2 shrink-0 rounded-full", row.className)}
                                aria-hidden="true"
                              />
                              <span className="truncate text-muted-foreground">
                                {row.label}
                              </span>
                            </span>
                            <span
                              dir="ltr"
                              className="inline-flex shrink-0 items-baseline gap-1.5 text-xs font-semibold tabular-nums"
                            >
                              <span>{row.value}</span>
                              <span className="font-normal text-muted-foreground">
                                {share}%
                              </span>
                            </span>
                          </div>
                          <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                            <div
                              className={cn("motion-bar h-full rounded-full", row.className)}
                              style={{ width: `${share}%`, "--i": index } as CSSProperties}
                            />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              </CardContent>
            </Card>

            <Card className="xl:col-span-4">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">{t("immigrationRunway")}</CardTitle>
                    <CardDescription className="mt-1 text-[13px]">
                      {t("immigrationRunwayHint")}
                    </CardDescription>
                  </div>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning-soft text-warning">
                    <Globe2 className="h-4 w-4" aria-hidden="true" />
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {runway.map((item, index) => {
                    const share = percent(item.value, immigrationTotal);
                    return (
                      <div key={item.label}>
                        <div className="flex items-end justify-between gap-3">
                          <span className="text-xs text-muted-foreground">{item.label}</span>
                          <span
                            dir="ltr"
                            className="inline-flex items-baseline gap-1.5 text-sm font-semibold tabular-nums"
                          >
                            <span>{item.value}</span>
                            <span className="text-[10px] font-normal text-muted-foreground">
                              {share}%
                            </span>
                          </span>
                        </div>
                        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-muted">
                          <div
                            className={cn("motion-bar h-full rounded-full", item.color)}
                            style={{ width: `${share}%`, "--i": index } as CSSProperties}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>

                <div className="mt-5 flex items-center justify-between gap-3 border-t border-border/70 pt-3">
                  <div>
                    <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      {t("pendingRequests")}
                    </p>
                    <p className="mt-0.5 text-lg font-semibold tabular-nums">
                      {immigration?.pending_change_requests ?? 0}
                    </p>
                  </div>
                  {hasPermission("immigration.view_all") && (
                    <Link
                      href="/app/immigration"
                      className="scu-linkbtn rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {t("viewQueue")}
                      <ChevronRight className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden="true" />
                    </Link>
                  )}
                </div>
              </CardContent>
            </Card>

            <Card className="xl:col-span-3">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <CardTitle className="text-base">{t("priorityQueue")}</CardTitle>
                    <CardDescription className="mt-1 text-[12px]">
                      {t("priorityQueueHint")}
                    </CardDescription>
                  </div>
                  <StatusBadge tone={attentionItems.length > 0 ? "warning" : "success"}>
                    {attentionItems.length}
                  </StatusBadge>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                {attentionItems.length === 0 ? (
                  <div className="flex items-center gap-2.5 rounded-lg border border-success/20 bg-success-soft/55 px-3 py-3">
                    <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                    <p className="text-xs leading-relaxed text-success">{t("noUrgent")}</p>
                  </div>
                ) : (
                  <ul className="divide-y divide-border/70">
                    {attentionItems.slice(0, 5).map((item) => {
                      const Icon = item.icon;
                      const row = (
                        <div className="flex items-center gap-2.5 py-2.5">
                          <span
                            className={cn(
                              "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                              item.tone === "danger"
                                ? "bg-destructive/10 text-destructive"
                                : item.tone === "warning"
                                  ? "bg-warning-soft text-warning"
                                  : "bg-info-soft text-info",
                            )}
                          >
                            <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                          </span>
                          <span className="min-w-0 flex-1 truncate text-xs font-medium">
                            {item.label}
                          </span>
                          <span className="text-sm font-semibold tabular-nums">
                            {item.value}
                          </span>
                        </div>
                      );
                      return (
                        <li key={item.label}>
                          {item.href ? (
                            <Link
                              href={item.href}
                              className="block rounded-md transition-colors hover:bg-accent/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              {row}
                            </Link>
                          ) : (
                            row
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card className="xl:col-span-4">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">{t("housingOccupancy")}</CardTitle>
                    <CardDescription className="mt-1 text-[13px]">
                      {t("housingOccupancyHint")}
                    </CardDescription>
                  </div>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-info-soft text-info">
                    <Building2 className="h-4 w-4" aria-hidden="true" />
                  </span>
                </div>
              </CardHeader>
              <CardContent>
                <div className="flex items-end justify-between gap-4">
                  <div>
                    <p className="text-4xl font-semibold leading-none tracking-[-0.05em] tabular-nums">
                      <CountUp value={occupancy} />
                      <span className="ms-0.5 text-xl">%</span>
                    </p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {housing?.occupied_beds ?? 0} / {housing?.total_beds ?? 0}{" "}
                      {tCommon("counts.beds", { count: housing?.total_beds ?? 0 })}
                    </p>
                  </div>
                  <p className="text-end text-xs text-muted-foreground">
                    {report.housing.total_buildings}{" "}
                    {t("campuses").toLocaleLowerCase(locale)}
                    <br />
                    {report.housing.total_rooms} {tReports("metrics.totalRooms")}
                  </p>
                </div>

                <div
                  className="mt-5 flex h-4 overflow-hidden rounded-md bg-muted ring-1 ring-inset ring-border/60"
                  role="img"
                  aria-label={t("housingOccupancy")}
                >
                  <span
                    className="motion-bar h-full bg-primary"
                    style={{ width: `${occupancy}%`, "--i": 0 } as CSSProperties}
                  />
                  <span
                    className="motion-bar h-full bg-success/70"
                    style={
                      {
                        width: `${percent(housing?.available_beds ?? 0, housing?.total_beds ?? 0)}%`,
                        "--i": 1,
                      } as CSSProperties
                    }
                  />
                </div>
                <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <dt className="flex items-center gap-1.5 text-muted-foreground">
                      <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
                      {t("occupied")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold tabular-nums">
                      {housing?.occupied_beds ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="flex items-center gap-1.5 text-muted-foreground">
                      <span className="h-1.5 w-1.5 rounded-full bg-success/70" aria-hidden="true" />
                      {t("availableBeds")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold tabular-nums">
                      {housing?.available_beds ?? 0}
                    </dd>
                  </div>
                  <div>
                    <dt className="flex items-center gap-1.5 text-muted-foreground">
                      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" aria-hidden="true" />
                      {t("outOfService")}
                    </dt>
                    <dd className="mt-1 text-sm font-semibold tabular-nums">
                      {housing?.out_of_service_beds ?? 0}
                    </dd>
                  </div>
                </dl>

                {estateBuildings.length > 0 && (
                  <div className="mt-4 border-t border-border/70 pt-3">
                    <div className="flex items-center justify-between gap-2 text-[10px]">
                      <span className="font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                        {t("buildingOccupancy")}
                      </span>
                      <span className="tabular-nums text-muted-foreground">
                        {estate.data?.total_buildings ?? estateBuildings.length}
                      </span>
                    </div>
                    <div
                      className="mt-2 flex h-12 items-end gap-1"
                      role="img"
                      aria-label={estateBuildings
                        .map(
                          (building) =>
                            `${building.name}: ${percent(building.occupied_count, building.bed_count)}%`,
                        )
                        .join(", ")}
                    >
                      {estateBuildings.map((building, index) => {
                        const buildingPct = percent(building.occupied_count, building.bed_count);
                        return (
                          <span
                            key={building.id}
                            className="relative h-full flex-1 overflow-hidden rounded-sm bg-muted/70"
                            title={`${building.name}: ${buildingPct}%`}
                          >
                            <span
                              className={cn(
                                "motion-column absolute inset-x-0 bottom-0 rounded-sm",
                                buildingPct >= 100
                                  ? "bg-destructive"
                                  : buildingPct >= 80
                                    ? "bg-warning"
                                    : "bg-primary/70",
                              )}
                              style={
                                {
                                  height: `${
                                    building.occupied_count > 0
                                      ? Math.max(4, buildingPct)
                                      : 0
                                  }%`,
                                  "--i": index,
                                } as CSSProperties
                              }
                            />
                          </span>
                        );
                      })}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="xl:col-span-4">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">{t("academicOperations")}</CardTitle>
                    <CardDescription className="mt-1 text-[13px]">
                      {t("academicOperationsHint")}
                    </CardDescription>
                  </div>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <GraduationCap className="h-4 w-4" aria-hidden="true" />
                  </span>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <dl className="divide-y divide-border/70">
                  {academicRows.map(({ label, value, Icon }) => (
                    <div key={label} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
                      <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
                      <dt className="flex-1 text-xs text-muted-foreground">{label}</dt>
                      <dd className="text-sm font-semibold tabular-nums">{value}</dd>
                    </div>
                  ))}
                </dl>
                <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border/70 pt-3 text-[10px] text-muted-foreground">
                  <div>
                    <p>{t("documentLibrary")}</p>
                    <p className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">
                      {report.documents_stored}
                    </p>
                  </div>
                  <div>
                    <p>{t("publishedNotices")}</p>
                    <p className="mt-0.5 text-sm font-semibold tabular-nums text-foreground">
                      {report.announcements_published}
                    </p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card className="xl:col-span-4">
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <CardTitle className="text-base">{t("recentActivity")}</CardTitle>
                    <CardDescription className="mt-1 text-[13px]">
                      {t("recentActivityHint")}
                    </CardDescription>
                  </div>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground">
                    <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                  </span>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                {!canViewAudit ? (
                  <div className="rounded-lg border border-border/70 bg-muted/25 p-3">
                    <p className="text-xs text-muted-foreground">{t("scopeNotice")}</p>
                  </div>
                ) : activity.loading ? (
                  <div className="space-y-3">
                    {Array.from({ length: 4 }).map((_, index) => (
                      <Skeleton key={index} className="h-9 w-full" />
                    ))}
                  </div>
                ) : (activity.data?.items.length ?? 0) === 0 ? (
                  <p className="text-xs text-muted-foreground">{t("noActivity")}</p>
                ) : (
                  <ol className="space-y-3">
                    {activity.data?.items.slice(0, 5).map((entry) => (
                      <li key={entry.id} className="relative ps-4">
                        <span
                          className="absolute start-0 top-1.5 h-1.5 w-1.5 rounded-full bg-primary"
                          aria-hidden="true"
                        />
                        <span
                          className="absolute start-[2.5px] top-4 h-[calc(100%-0.5rem)] w-px bg-border last:hidden"
                          aria-hidden="true"
                        />
                        <p className="text-xs font-medium leading-snug">
                          {actionLabel(entry.action)}
                        </p>
                        <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                          {entry.actor_email ?? tCommon("states.unknown")}
                          {" · "}
                          {new Intl.DateTimeFormat(locale, {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          }).format(new Date(entry.created_at))}
                        </p>
                      </li>
                    ))}
                  </ol>
                )}
                {canViewAudit && (
                  <Link
                    href="/app/audit"
                    className="mt-4 flex items-center justify-between rounded-lg border border-border/70 px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-accent"
                  >
                    {t("openAudit")}
                    <ChevronRight className="h-3.5 w-3.5 rtl:rotate-180" aria-hidden="true" />
                  </Link>
                )}
              </CardContent>
            </Card>
          </div>
        </section>
      )}

      {!canViewReports && (
        <Card className="mb-7 overflow-hidden">
          <div className="grid md:grid-cols-[1fr_auto]">
            <CardContent className="p-6">
              <div className="flex items-center gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                  {initialsOf(user.full_name) || <Users className="h-5 w-5" />}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold">{user.full_name}</p>
                  <p className="truncate text-xs text-muted-foreground" dir="ltr">
                    {user.email}
                  </p>
                </div>
              </div>
              <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted-foreground">
                {t("scopeNotice")}
              </p>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {user.roles.map((role) => (
                  <Badge key={role.id} variant="secondary" className="text-[10px]">
                    {role.name}
                  </Badge>
                ))}
                <Badge variant="outline" className="text-[10px] tabular-nums">
                  {user.permissions.length} {t("permissions")}
                </Badge>
              </div>
            </CardContent>
            <div className="hidden w-44 items-center justify-center border-s border-border/70 bg-muted/30 md:flex">
              <ScuMark className="h-20 w-20 opacity-70" />
            </div>
          </div>
        </Card>
      )}

      <section aria-labelledby="modules-heading" data-reveal>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="modules-heading" className="text-lg font-semibold tracking-[-0.02em]">
              {t("yourModules")}
            </h2>
            <p className="mt-0.5 text-[13px] text-muted-foreground">{t("modulesHint")}</p>
          </div>
          <span className="text-xs font-medium tabular-nums text-muted-foreground">
            {modules.length}
          </span>
        </div>

        {modules.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-sm text-muted-foreground">
              {t("emptyModules")}
            </CardContent>
          </Card>
        ) : (
          <div className="motion-grid grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {modules.map((item) => {
              const Icon = item.icon;
              const href = item.href as string;
              return (
                <Link
                  key={item.labelKey}
                  href={href}
                  className="scu-lift group flex items-center gap-3.5 rounded-xl border border-border/80 bg-card p-4 shadow-card focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/[0.08] text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                    <Icon className="h-[18px] w-[18px]" aria-hidden="true" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold">
                      {tNav(MODULE_KEYS[href] ?? item.labelKey)}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-muted-foreground">
                      {t("openModule")}
                    </span>
                  </span>
                  <ArrowRight
                    className="h-4 w-4 shrink-0 text-muted-foreground/50 transition-all group-hover:translate-x-0.5 group-hover:text-primary rtl:rotate-180 rtl:group-hover:-translate-x-0.5"
                    aria-hidden="true"
                  />
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </AppShell>
  );
}
