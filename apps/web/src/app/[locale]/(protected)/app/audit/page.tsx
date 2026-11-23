"use client";

import { useCallback, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { auditApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import type { AuditLogEntry, AuditLogListResponse } from "@/types/platform";

const PAGE_SIZE = 50;

/**
 * Audit action codes the UI can name.
 *
 * This list mirrors the `record_audit` call sites in the backend exactly. A
 * code that is not listed still renders (humanized, e.g. "housing assignment
 * updated") so a newly added backend action degrades readably rather than
 * printing a raw token.
 */
const ACTION_KEYS = [
  "auth.login_succeeded",
  "auth.login_failed",
  "auth.logout",
  "student.created",
  "student.updated",
  "student.archived",
  "student.status_changed",
  "immigration.change_request.created",
  "immigration.change_request.approved",
  "immigration.change_request.rejected",
  "immigration.import.applied",
  "immigration.overview_exported",
  "housing.assignment.created",
  "housing.assignment.transferred",
  "housing.assignment.updated",
  "housing.assignment.ended",
  "announcement.created",
  "announcement.updated",
  "announcement.published",
  "announcement.archived",
  "support.ticket.created",
  "support.ticket.updated",
  "document.uploaded",
  "document.downloaded",
  "document.previewed",
  "document.archived",
  "document.deleted",
  "academic.enrollment.created",
  "academic.enrollment.dropped",
  "academic.attendance.updated",
  "academic.grade.updated",
  "academic.placement.created",
  "academic.placement.superseded",
  "academic.placement.earlier_intake_authorized",
  "academic.admission.pointer_corrected",
  "academic.admission.status_corrected",
  "academic.admission.change_requested",
  "academic.admission.change_approved",
  "academic.admission.change_rejected",
  "academic.calendar.exception_created",
  "academic.calendar.exception_corrected",
  "academic.calendar.exception_voided",
  "academic.commencement.approved",
  "academic.commencement.corrected",
  "attendance.absence.recorded",
  "attendance.absence.corrected",
  "attendance.absence.cancelled",
];

export default function AuditPage() {
  const t = useTranslations("audit");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();

  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(1);

  const canView = hasPermission("audit.view");

  const fetchLogs = useCallback(
    () =>
      auditApi.list({
        page,
        page_size: PAGE_SIZE,
        action: action || undefined,
        entity_type: entityType || undefined,
      }),
    [page, action, entityType],
  );

  const { data, loading, error, refetch } = useApi<AuditLogListResponse>(
    canView ? fetchLogs : () => Promise.resolve(null as never),
    [canView, page, action, entityType],
    "audit log",
  );

  const actionOptions = useMemo(
    () => [
      { value: "", label: `${t("action")} — ${tCommon("labels.all")}` },
      ...ACTION_KEYS.map((value) => ({ value, label: t(`actions.${value}`) })),
    ],
    [t, tCommon],
  );

  const entityOptions = useMemo(() => {
    const types = [
      "student",
      "immigration_change_request",
      "housing_assignment",
      "announcement",
      "support_ticket",
      "document",
      "user",
    ];
    return [
      { value: "", label: `${t("entity")} — ${tCommon("labels.all")}` },
      ...types.map((value) => ({
        value,
        label: value.replace(/_/g, " "),
      })),
    ];
  }, [t, tCommon]);

  const localized = localizeError(error);
  const entries = data?.items ?? [];
  const totalPages =
    data && data.page_size > 0
      ? Math.max(1, Math.ceil(data.total / data.page_size))
      : 1;

  const actionLabel = (value: string) =>
    t.has(`actions.${value}`)
      ? t(`actions.${value}`)
      : value.replace(/[._]/g, " ");

  const columns: Column<AuditLogEntry>[] = [
    {
      key: "time",
      header: t("timestamp"),
      cell: (entry) => (
        <span className="whitespace-nowrap tabular-nums text-xs">
          {new Date(entry.created_at).toLocaleString(locale)}
        </span>
      ),
    },
    {
      key: "action",
      header: t("action"),
      cell: (entry) => <span className="font-medium">{actionLabel(entry.action)}</span>,
    },
    {
      key: "actor",
      header: t("actor"),
      hideOnMobile: true,
      cell: (entry) => (
        <span dir="ltr">{entry.actor_email ?? tCommon("states.unknown")}</span>
      ),
    },
    {
      key: "entity",
      header: t("entity"),
      hideOnMobile: true,
      cell: (entry) =>
        entry.entity_type ? (
          <span className="text-sm">{entry.entity_type.replace(/_/g, " ")}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ];

  if (!canView) {
    return (
      <AppShell>
        <PageHeader title={t("title")} description={t("subtitle")} />
        <EmptyState title={t("noPermission")} />
      </AppShell>
    );
  }

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
      />

      <p className="mb-4 flex items-start gap-2 text-sm text-muted-foreground">
        <ShieldCheck
          className="mt-0.5 h-4 w-4 shrink-0 text-green-600"
          aria-hidden="true"
        />
        {t("sensitiveNotice")}
      </p>

      <Card className="mb-4">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
          <FilterSelect
            label={t("action")}
            value={action}
            options={actionOptions}
            showLabel
            onChange={(value) => {
              setAction(value);
              setPage(1);
            }}
            className="sm:w-72"
          />
          <FilterSelect
            label={t("entity")}
            value={entityType}
            options={entityOptions}
            showLabel
            onChange={(value) => {
              setEntityType(value);
              setPage(1);
            }}
            className="sm:w-64"
          />
        </CardContent>
      </Card>

      <DataTable
        columns={columns}
        rows={entries}
        rowKey={(entry) => entry.id}
        loading={loading}
        error={error ? localized.message : null}
        onRetry={refetch}
        emptyTitle={t("empty")}
        mobileCard={(entry) => (
          <div className="space-y-1">
            <p className="font-medium">{actionLabel(entry.action)}</p>
            <p className="text-xs text-muted-foreground">
              {new Date(entry.created_at).toLocaleString(locale)}
            </p>
            <p className="text-xs text-muted-foreground" dir="ltr">
              {entry.actor_email ?? tCommon("states.unknown")}
            </p>
          </div>
        )}
      />

      {data && data.total > PAGE_SIZE && (
        <Pagination
          page={data.page}
          pageSize={data.page_size}
          total={data.total}
          totalPages={totalPages}
          onPageChange={setPage}
        />
      )}
    </AppShell>
  );
}
