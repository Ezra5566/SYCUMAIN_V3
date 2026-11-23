"use client";

import { useCallback, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Download,
  FileClock,
  FileWarning,
  ShieldCheck,
  Users,
  XCircle,
} from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import {
  exportImmigrationOverview,
  getImmigrationOverview,
} from "@/lib/immigration-api";
import { listPeriods } from "@/lib/academic-api";
import { downloadBlob } from "@/lib/download";
import { ImmigrationReviewPanel } from "@/components/immigration/review-panel";
import { ImmigrationImportDialog } from "@/components/immigration/import-dialog";
import { NationalityMap } from "@/components/immigration/nationality-map";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { DataTable, type Column } from "@/components/ui/data-table";
import { FilterSelect } from "@/components/ui/filter-select";
import { Pagination } from "@/components/ui/pagination";
import { toast } from "@/components/ui/toast";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { cn } from "@/lib/utils";
import { normalizeApiError } from "@/lib/api-error";
import type {
  ImmigrationOverviewItem,
  ImmigrationOverviewResponse,
} from "@/types/immigration";

/** Filter buckets, mirroring the statuses the backend derives from dates. */
const FILTER_VALUES = [
  null,
  "VALID",
  "EXPIRING_SOON",
  "URGENT",
  "EXPIRED",
  "NOT_PROVIDED",
] as const;

function ExpiryCell({
  status,
  days,
  date,
}: {
  status: string | null;
  days: number | null;
  date: string | null;
}) {
  const t = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const statusLabel = useStatusLabel();

  return (
    <div className="flex flex-col gap-1">
      <StatusBadge tone={toneForStatus(status)}>
        {status
          ? statusLabel(status, "immigration.statusLabel")
          : tCommon("states.notProvided")}
      </StatusBadge>
      {days !== null && (
        <span className="text-xs text-muted-foreground">
          {days >= 0
            ? t("daysRemaining", { count: days })
            : t("daysExpired", { count: Math.abs(days) })}
        </span>
      )}
      {date && (
        <span className="text-xs tabular-nums text-muted-foreground">
          {format.dateTime(new Date(date), { dateStyle: "medium" })}
        </span>
      )}
    </div>
  );
}

function TrustBadge({ status }: { status: string | null }) {
  const t = useTranslations("immigration");
  const tone =
    status === "VERIFIED"
      ? "border-success/30 bg-success-soft text-success"
      : status && status !== "NO_ADMISSION"
        ? "border-destructive/30 bg-destructive/10 text-destructive"
        : "border-border bg-muted text-muted-foreground";
  return (
    <Badge variant="outline" className={tone}>
      {status
        ? t(`cohort.trust.${status}`)
        : t("cohort.trustUnavailable")}
    </Badge>
  );
}

interface ExpiryWatch {
  key: string;
  studentId: string;
  studentName: string;
  studentNumber: string;
  documentLabel: string;
  status: string | null;
  days: number;
  date: string;
}

export default function ImmigrationDashboardPage() {
  const t = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const tStudents = useTranslations("students");
  const format = useFormatter();
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();
  const [filter, setFilter] = useState<string | null>(null);
  const [intakeFilter, setIntakeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const periods = useApi(() => listPeriods(1, 100), [], "intake filter");

  const fetchOverview = useCallback(
    () =>
      getImmigrationOverview({
        status: filter || undefined,
        intakeId: intakeFilter || undefined,
        page,
        pageSize: 25,
      }),
    [filter, intakeFilter, page],
  );

  const { data, loading, error, refetch } = useApi<ImmigrationOverviewResponse>(
    fetchOverview,
    [filter, intakeFilter, page],
    "immigration overview",
  );

  const localized = localizeError(error);

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportImmigrationOverview({
        status: filter || undefined,
        intakeId: intakeFilter || undefined,
      });
      downloadBlob(
        blob,
        `immigration-overview-${new Date().toISOString().slice(0, 10)}.csv`,
      );
    } catch (err) {
      toast.error(localizeError(normalizeApiError(err, "immigration export")).message);
    } finally {
      setExporting(false);
    }
  };

  const columns: Column<ImmigrationOverviewItem>[] = [
    {
      key: "student",
      header: tStudents("title"),
      cell: (item) => (
        <div className="min-w-0">
          <Link
            href={`/app/students/${item.student_id}`}
            className="rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {item.student_name}
          </Link>
          <p className="font-mono text-xs text-muted-foreground">{item.student_number}</p>
        </div>
      ),
    },
    {
      key: "cohort",
      header: t("cohort.originalIntake"),
      cell: (item) => (
        <div className="flex min-w-0 flex-col gap-1">
          <span className="truncate text-sm">
            {item.original_admission_intake_name ??
              (item.verification_status === "NO_ADMISSION"
                ? t("cohort.trust.NO_ADMISSION")
                : "—")}
          </span>
          <TrustBadge status={item.verification_status ?? null} />
        </div>
      ),
    },
    {
      key: "placement",
      header: t("cohort.placementIntake"),
      hideOnMobile: true,
      cell: (item) => (
        <div className="min-w-0">
          <span className="block truncate text-sm">
            {item.placement_intake_name ?? "—"}
          </span>
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            {t("cohort.academicOnly")}
          </span>
        </div>
      ),
    },
    {
      key: "visa",
      header: t("visa"),
      cell: (item) => (
        <ExpiryCell
          status={item.visa_status ?? null}
          days={item.visa_days_remaining ?? null}
          date={item.visa_expiry_date ?? null}
        />
      ),
    },
    {
      key: "permit",
      header: t("residencePermit"),
      cell: (item) => (
        <ExpiryCell
          status={item.residence_permit_status ?? null}
          days={item.residence_permit_days_remaining ?? null}
          date={item.residence_permit_expiry_date ?? null}
        />
      ),
    },
    {
      key: "passport",
      header: t("passport"),
      hideOnMobile: true,
      cell: (item) => (
        <ExpiryCell
          status={item.passport_status ?? null}
          days={item.passport_days_remaining ?? null}
          date={item.passport_expiry_date ?? null}
        />
      ),
    },
    {
      key: "requests",
      header: t("changeRequests"),
      cell: (item) =>
        item.pending_requests_count > 0 ? (
          <Badge variant="secondary">
            {t("pendingReviewCount", { count: item.pending_requests_count })}
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "actions",
      header: tCommon("labels.actions"),
      className: "text-end",
      cell: (item) => (
        <Button asChild variant="outline" size="sm">
          <Link href={`/app/students/${item.student_id}`}>{tCommon("actions.view")}</Link>
        </Button>
      ),
    },
  ];

  if (!hasPermission("immigration.view_all")) {
    return (
      <AppShell>
        <EmptyState title={t("sensitiveNotice")} message={tCommon("labels.noResultsHint")} />
      </AppShell>
    );
  }

  const counts = [
    {
      key: "total",
      label: tStudents("title"),
      value: data?.total_students ?? 0,
      icon: Users,
      tone: "bg-primary/10 text-primary",
    },
    {
      key: "valid",
      label: t("valid"),
      value: data?.valid_count ?? 0,
      icon: ShieldCheck,
      tone: "bg-success-soft text-success",
    },
    {
      key: "expiring",
      label: t("expiringSoon"),
      value: data?.expiring_count ?? 0,
      icon: Clock3,
      tone: "bg-warning-soft text-warning",
    },
    {
      key: "urgent",
      label: t("urgent"),
      value: data?.urgent_count ?? 0,
      icon: AlertTriangle,
      tone: "bg-warning-soft text-warning",
    },
    {
      key: "expired",
      label: t("expired"),
      value: data?.expired_count ?? 0,
      icon: XCircle,
      tone: "bg-destructive/10 text-destructive",
    },
    {
      key: "missing",
      label: t("missingInformation"),
      value: data?.no_data_count ?? 0,
      icon: FileWarning,
      tone: "bg-muted text-muted-foreground",
    },
  ];
  const cohortTotal = data?.total_students ?? 0;

  const distribution = [
    {
      label: t("valid"),
      value: data?.valid_count ?? 0,
      className: "bg-success",
      color: "hsl(var(--success))",
    },
    {
      label: t("expiringSoon"),
      value: data?.expiring_count ?? 0,
      className: "bg-warning",
      color: "hsl(var(--warning))",
    },
    {
      label: t("expired"),
      value: data?.expired_count ?? 0,
      className: "bg-destructive",
      color: "hsl(var(--destructive))",
    },
    {
      label: t("missingInformation"),
      value: data?.no_data_count ?? 0,
      className: "bg-muted-foreground/50",
      color: "hsl(var(--muted-foreground))",
    },
  ];
  const distributionGradient = (() => {
    if (cohortTotal <= 0) return "hsl(var(--muted))";
    let cursor = 0;
    return `conic-gradient(${distribution
      .map((item) => {
        const start = cursor;
        cursor += (item.value / cohortTotal) * 100;
        return `${item.color} ${start}% ${cursor}%`;
      })
      .join(", ")})`;
  })();

  const watches: ExpiryWatch[] = (data?.items ?? [])
    .flatMap((item) => {
      const rows: ExpiryWatch[] = [];
      const add = (
        kind: string,
        label: string,
        days: number | null | undefined,
        date: string | null | undefined,
        status: string | null | undefined,
      ) => {
        if (days === null || days === undefined || !date || days > 90) return;
        rows.push({
          key: `${item.student_id}-${kind}`,
          studentId: item.student_id,
          studentName: item.student_name,
          studentNumber: item.student_number,
          documentLabel: label,
          status: status ?? null,
          days,
          date,
        });
      };
      add("visa", t("visa"), item.visa_days_remaining, item.visa_expiry_date, item.visa_status);
      add(
        "permit",
        t("residencePermit"),
        item.residence_permit_days_remaining,
        item.residence_permit_expiry_date,
        item.residence_permit_status,
      );
      add(
        "passport",
        t("passport"),
        item.passport_days_remaining,
        item.passport_expiry_date,
        item.passport_status,
      );
      return rows;
    })
    .sort((a, b) => a.days - b.days)
    .slice(0, 5);

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={exporting}
            >
              <Download className="me-1.5 h-4 w-4" aria-hidden="true" />
              {exporting ? t("cohort.exporting") : t("cohort.export")}
            </Button>
            {hasPermission("immigration.edit") && (
              <ImmigrationImportDialog onImported={refetch} />
            )}
          </div>
        }
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
      />

      <ImmigrationReviewPanel onReviewed={refetch} />

      {error ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState message={localized.message} hint={localized.hint} onRetry={refetch} />
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="mb-4 overflow-hidden">
            <CardHeader className="flex flex-col gap-3 border-b border-border/70 bg-muted/25 pb-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <CardTitle className="text-base">{t("portfolio")}</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">{t("portfolioHint")}</p>
              </div>
              {data && data.pending_requests_count > 0 && (
                <Badge variant="secondary" className="w-fit">
                  {t("pendingReviewCount", { count: data.pending_requests_count })}
                </Badge>
              )}
            </CardHeader>
            <div className="grid grid-cols-2 gap-px bg-border/80 sm:grid-cols-3 xl:grid-cols-6">
              {counts.map(({ key, label, value, icon: Icon, tone }) => (
                <div key={key} className="min-w-0 bg-card px-4 py-4">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                      {label}
                    </p>
                    <span className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-md", tone)}>
                      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
                    </span>
                  </div>
                  <p className="mt-2.5 text-xl font-semibold leading-none tabular-nums">
                    {loading ? "—" : value}
                  </p>
                </div>
              ))}
            </div>
          </Card>

          <NationalityMap
            intakeFilter={intakeFilter}
            onIntakeFilterChange={(value) => {
              setIntakeFilter(value);
              setPage(1);
            }}
            periods={periods.data?.items ?? []}
          />

          <Card className="mb-4">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">{t("cohort.title")}</CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {t("cohort.hint")}
              </p>
            </CardHeader>
            <CardContent className="grid gap-4 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {t("cohort.namedCohorts")}
                </p>
                {(data?.cohorts ?? []).length > 0 ? (
                  <ul className="flex flex-wrap gap-2">
                    {(data?.cohorts ?? []).map((cohort) => (
                      <li
                        key={cohort.intake_id}
                        className="rounded-lg border border-border/70 bg-muted/30 px-3 py-2"
                      >
                        <span className="block text-sm font-medium">
                          {cohort.intake_name}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {t("cohort.count", { count: cohort.count })}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {t("cohort.noNamedCohorts")}
                  </p>
                )}
              </div>
              <div className="rounded-lg border border-warning/25 bg-warning-soft/40 p-3">
                <p className="flex items-center justify-between gap-3 text-sm font-medium">
                  <span>{t("cohort.untrusted")}</span>
                  <span className="tabular-nums">
                    {data?.untrusted.total ?? 0}
                  </span>
                </p>
                <ul className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  {(
                    [
                      "UNVERIFIED",
                      "REVOKED",
                      "DISPUTED",
                      "NO_ADMISSION",
                    ] as const
                  ).map((reason) => (
                    <li key={reason} className="flex justify-between gap-2">
                      <span>{t(`cohort.trust.${reason}`)}</span>
                      <span className="tabular-nums">
                        {reason === "UNVERIFIED"
                          ? (data?.untrusted.unverified ?? 0)
                          : reason === "REVOKED"
                            ? (data?.untrusted.revoked ?? 0)
                            : reason === "DISPUTED"
                              ? (data?.untrusted.disputed ?? 0)
                              : (data?.untrusted.no_admission ?? 0)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            </CardContent>
          </Card>

          <div className="mb-4 grid gap-4 xl:grid-cols-12">
            <Card className="flex flex-col xl:col-span-7">
              <CardHeader className="flex-row items-start justify-between gap-3 space-y-0 pb-3">
                <div>
                  <CardTitle className="text-base">{t("expiryWatch")}</CardTitle>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("expiryWatchHint")}
                  </p>
                </div>
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-warning-soft text-warning">
                  <CalendarClock className="h-4 w-4" aria-hidden="true" />
                </span>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col justify-center">
                {loading ? (
                  <div className="space-y-3">
                    {[0, 1, 2].map((item) => (
                      <div key={item} className="h-14 animate-pulse rounded-lg bg-muted" />
                    ))}
                  </div>
                ) : watches.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-10 text-center">
                    <span className="flex h-12 w-12 items-center justify-center rounded-full bg-success-soft text-success">
                      <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
                    </span>
                    <p className="mt-3 text-sm font-medium text-foreground">{t("noUpcoming")}</p>
                    <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground">
                      {t("noUpcomingHint")}
                    </p>
                  </div>
                ) : (
                  <ol className="divide-y divide-border/70">
                    {watches.map((watch) => {
                      const position = watch.days <= 0
                        ? 0
                        : Math.min(100, Math.max(2, (watch.days / 90) * 100));
                      const critical = watch.days < 0;
                      const warning = watch.days >= 0 && watch.days <= 30;
                      return (
                        <li key={watch.key} className="py-3 first:pt-0 last:pb-0">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <Link
                                href={`/app/students/${watch.studentId}`}
                                className="truncate text-sm font-medium hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                              >
                                {watch.studentName}
                              </Link>
                              <p className="truncate text-[11px] text-muted-foreground">
                                {watch.documentLabel}
                                {" · "}
                                <span className="font-mono">{watch.studentNumber}</span>
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <span
                                className={cn(
                                  "text-[11px] font-semibold tabular-nums",
                                  critical
                                    ? "text-destructive"
                                    : warning
                                      ? "text-warning"
                                      : "text-muted-foreground",
                                )}
                              >
                                {watch.days < 0
                                  ? t("daysExpired", { count: Math.abs(watch.days) })
                                  : t("daysRemaining", { count: watch.days })}
                              </span>
                              <StatusBadge tone={toneForStatus(watch.status)}>
                                {watch.status
                                  ? statusLabel(watch.status, "immigration.statusLabel")
                                  : tCommon("states.notProvided")}
                              </StatusBadge>
                            </div>
                          </div>
                          <div className="mt-2 flex items-center gap-2">
                            <span className="text-[9px] text-muted-foreground">
                              {t("expiryWatchStart")}
                            </span>
                            <div className="relative h-1 flex-1 rounded-full bg-muted">
                              <span
                                className={cn(
                                  "absolute top-1/2 h-2 w-2 -translate-y-1/2 rounded-full ring-2 ring-card",
                                  critical ? "bg-destructive" : warning ? "bg-warning" : "bg-info",
                                )}
                                style={{
                                  insetInlineStart: `${position}%`,
                                  transform: "translate(-50%, -50%)",
                                }}
                                aria-hidden="true"
                              />
                            </div>
                            <span className="text-[9px] text-muted-foreground">
                              {t("expiryWatchEnd")}
                            </span>
                            <span className="text-[9px] tabular-nums text-muted-foreground">
                              {format.dateTime(new Date(watch.date), { dateStyle: "medium" })}
                            </span>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </CardContent>
            </Card>

            <Card className="xl:col-span-5">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">{t("compliancePosture")}</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("complianceHint")}
                </p>
              </CardHeader>
              <CardContent>
                <div className="flex flex-col items-center gap-5 sm:flex-row">
                  <div
                    className="relative flex h-36 w-36 shrink-0 items-center justify-center rounded-full"
                    style={{ background: distributionGradient }}
                    role="img"
                    aria-label={t("compliancePosture")}
                  >
                    <div className="flex h-[6.2rem] w-[6.2rem] flex-col items-center justify-center rounded-full bg-card shadow-sm">
                      <span className="text-2xl font-semibold leading-none tabular-nums">
                        {data?.valid_count ?? 0}
                      </span>
                      <span className="mt-1 text-[9px] uppercase tracking-[0.12em] text-muted-foreground">
                        {t("valid")}
                      </span>
                    </div>
                  </div>
                  <ul className="w-full min-w-0 flex-1 space-y-2.5">
                    {distribution.map((item) => (
                      <li key={item.label} className="flex items-center justify-between gap-3">
                        <span className="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
                          <span
                            className={cn("h-2 w-2 shrink-0 rounded-full", item.className)}
                            aria-hidden="true"
                          />
                          <span className="truncate">{item.label}</span>
                        </span>
                        <span className="text-xs font-semibold tabular-nums">{item.value}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="mt-5 grid grid-cols-2 gap-2 border-t border-border/70 pt-4">
                  <div className="rounded-lg border border-info/20 bg-info-soft/60 p-3">
                    <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-info">
                      <FileClock className="h-3 w-3" aria-hidden="true" />
                      {t("pendingReview")}
                    </p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {data?.pending_requests_count ?? 0}
                    </p>
                  </div>
                  <div className="rounded-lg border border-warning/20 bg-warning-soft/60 p-3">
                    <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-warning">
                      <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                      {t("urgent")}
                    </p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {data?.urgent_count ?? 0}
                    </p>
                  </div>
                </div>

                <Link
                  href="/app/reports"
                  className="mt-3 flex items-center justify-between rounded-lg border border-border/70 px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-accent"
                >
                  {t("openComplianceReport")}
                  <ArrowUpRight className="h-3.5 w-3.5 rtl:-scale-x-100" aria-hidden="true" />
                </Link>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="flex flex-col gap-3 pb-4 sm:flex-row sm:items-center sm:justify-between">
              <CardTitle className="text-base">{tStudents("title")}</CardTitle>
              <div className="flex flex-wrap items-end gap-2">
                <FilterSelect
                  label={t("cohort.filterIntake")}
                  value={intakeFilter}
                  options={[
                    { value: "", label: t("cohort.allIntakes") },
                    ...(periods.data?.items ?? []).map((period) => ({
                      value: period.id,
                      label: period.name,
                    })),
                  ]}
                  onChange={(value) => {
                    setIntakeFilter(value);
                    setPage(1);
                  }}
                  className="w-52"
                />
              <div
                className="flex flex-wrap gap-2"
                role="group"
                aria-label={t("overview")}
              >
                {FILTER_VALUES.map((value) => (
                  <Button
                    key={value ?? "all"}
                    variant={filter === value ? "default" : "outline"}
                    size="sm"
                    className="rounded-full"
                    aria-pressed={filter === value}
                    onClick={() => {
                      setFilter(value);
                      setPage(1);
                    }}
                  >
                    {value === null
                      ? t("filters.all")
                      : value === "VALID"
                        ? t("filters.valid")
                        : value === "EXPIRING_SOON"
                          ? t("filters.expiring", { days: 90 })
                          : value === "URGENT"
                            ? t("filters.urgent", { days: 30 })
                            : value === "NOT_PROVIDED"
                              ? t("filters.missing")
                              : t("filters.expired")}
                  </Button>
                ))}
              </div>
              </div>
            </CardHeader>
            <CardContent className="pt-0">
              <DataTable
                columns={columns}
                rows={data?.items ?? []}
                rowKey={(item) => item.student_id}
                loading={loading}
                onRetry={refetch}
                emptyTitle={tCommon("labels.noResults")}
                emptyMessage={tCommon("labels.noResultsHint")}
              />
              <Pagination
                page={data?.page ?? page}
                pageSize={data?.page_size ?? 25}
                total={data?.total ?? 0}
                totalPages={data?.total_pages ?? 0}
                onPageChange={setPage}
              />
            </CardContent>
          </Card>
        </>
      )}
    </AppShell>
  );
}
