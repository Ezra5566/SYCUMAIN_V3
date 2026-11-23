"use client";

import { useCallback, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { LifeBuoy } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { supportApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { DataTable, type Column } from "@/components/ui/data-table";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { Pagination } from "@/components/ui/pagination";
import { StatCard, StatGrid } from "@/components/ui/stat-card";
import { EmptyState } from "@/components/ui/empty-state";
import { CreateTicketDialog } from "@/components/support/create-ticket-dialog";
import type {
  SupportTicketCategory,
  SupportTicketListItem,
  SupportTicketListResponse,
  SupportTicketStatus,
} from "@/types/platform";

const STATUS_VALUES: SupportTicketStatus[] = [
  "OPEN",
  "IN_PROGRESS",
  "WAITING_FOR_STUDENT",
  "RESOLVED",
  "CLOSED",
];

const CATEGORY_VALUES: SupportTicketCategory[] = [
  "VISA_IMMIGRATION",
  "HOUSING",
  "ACADEMIC",
  "FINANCE",
  "IT",
  "GENERAL",
];

const PAGE_SIZE = 20;

export default function SupportPage() {
  const t = useTranslations("support");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const { hasPermission, hasRole } = useAuth();
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<SupportTicketStatus | "">("");
  const [categoryFilter, setCategoryFilter] = useState<SupportTicketCategory | "">("");
  const [assignedToMe, setAssignedToMe] = useState(false);
  const [page, setPage] = useState(1);
  const [composing, setComposing] = useState(false);

  // Internal notes and assignment are staff-only surfaces. A student holds
  // `support.create` and `support.view` for their own tickets.
  const isStaff = hasRole("ADMIN") || hasRole("MANAGEMENT") || hasRole("TEACHER");
  const canCreate = hasPermission("support.create");
  const canAssign = hasPermission("support.assign");

  const fetchTickets = useCallback(
    () =>
      supportApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        status: (statusFilter as SupportTicketStatus) || undefined,
        category: (categoryFilter as SupportTicketCategory) || undefined,
        assigned_to_me: assignedToMe || undefined,
      }),
    [page, search, statusFilter, categoryFilter, assignedToMe],
  );

  const { data, loading, error, refetch } = useApi<SupportTicketListResponse>(
    fetchTickets,
    [page, search, statusFilter, categoryFilter, assignedToMe],
    "support tickets",
  );

  // The counters are a staff convenience; a failure here must not blank the list.
  const { data: stats } = useApi(
    () => supportApi.stats(),
    [],
    "support stats",
  );

  const statusOptions = useMemo(
    () => [
      { value: "", label: `${tCommon("labels.status")} — ${tCommon("labels.all")}` },
      ...STATUS_VALUES.map((value) => ({ value, label: t(`status.${value}`) })),
    ],
    [t, tCommon],
  );

  const categoryOptions = useMemo(
    () => [
      {
        value: "",
        label: `${tCommon("labels.category")} — ${tCommon("labels.all")}`,
      },
      ...CATEGORY_VALUES.map((value) => ({
        value,
        label: t(`categories.${value}`),
      })),
    ],
    [t, tCommon],
  );

  const localized = localizeError(error);
  const tickets = data?.items ?? [];
  const totalPages =
    data && data.page_size > 0
      ? Math.max(1, Math.ceil(data.total / data.page_size))
      : 1;

  const columns: Column<SupportTicketListItem>[] = [
    {
      key: "subject",
      header: t("subject"),
      cell: (ticket) => (
        <div className="min-w-0">
          <Link
            href={`/app/support/${ticket.id}`}
            className="rounded-sm font-medium hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {ticket.subject}
          </Link>
          <p className="font-mono text-xs text-muted-foreground">
            {ticket.ticket_number}
          </p>
        </div>
      ),
    },
    {
      key: "student",
      header: tCommon("labels.name"),
      hideOnMobile: true,
      cell: (ticket) => ticket.student_name ?? tCommon("states.notSet"),
    },
    {
      key: "category",
      header: tCommon("labels.category"),
      hideOnMobile: true,
      cell: (ticket) => statusLabel(ticket.category, "support.categories"),
    },
    {
      key: "status",
      header: tCommon("labels.status"),
      cell: (ticket) => (
        <StatusBadge tone={toneForStatus(ticket.status)}>
          {t(`status.${ticket.status}`)}
        </StatusBadge>
      ),
    },
    {
      key: "assignee",
      header: t("assignee"),
      hideOnMobile: true,
      cell: (ticket) => ticket.assignee_name ?? t("unassigned"),
    },
    {
      key: "updated",
      header: t("updatedAt"),
      hideOnMobile: true,
      cell: (ticket) => new Date(ticket.updated_at).toLocaleDateString(locale),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={isStaff ? t("allTickets") : t("myTickets")}
        description={t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
        actions={
          canCreate ? (
            <Button size="sm" onClick={() => setComposing(true)}>
              <LifeBuoy className="me-1.5 h-4 w-4" aria-hidden="true" />
              {t("newTicket")}
            </Button>
          ) : undefined
        }
      />

      {!isStaff && (
        <p className="mb-4 text-sm text-muted-foreground">
          {t("studentsOnlyOwnTickets")}
        </p>
      )}

      {isStaff && stats && (
        <StatGrid>
          <StatCard label={tCommon("labels.total")} value={stats.total} />
          <StatCard
            label={t(`status.OPEN`)}
            value={stats.open}
            tone={stats.open > 0 ? "warning" : "default"}
          />
          <StatCard label={t(`status.IN_PROGRESS`)} value={stats.in_progress} />
          <StatCard
            label={t(`status.WAITING_FOR_STUDENT`)}
            value={stats.waiting_for_student}
          />
          <StatCard
            label={t("unassigned")}
            value={stats.unassigned}
            tone={stats.unassigned > 0 ? "warning" : "default"}
          />
        </StatGrid>
      )}

      <Card className="mb-4">
        <CardContent className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setPage(1);
            }}
            placeholder={tCommon("labels.searchPlaceholder")}
            className="lg:max-w-xs lg:flex-1"
          />
          <FilterSelect
            label={tCommon("labels.status")}
            value={statusFilter}
            options={statusOptions}
            onChange={(value) => {
              setStatusFilter(value as SupportTicketStatus | "");
              setPage(1);
            }}
            className="lg:w-52"
          />
          <FilterSelect
            label={tCommon("labels.category")}
            value={categoryFilter}
            options={categoryOptions}
            onChange={(value) => {
              setCategoryFilter(value as SupportTicketCategory | "");
              setPage(1);
            }}
            className="lg:w-52"
          />
          {canAssign && (
            <label className="flex shrink-0 items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={assignedToMe}
                onChange={(event) => {
                  setAssignedToMe(event.target.checked);
                  setPage(1);
                }}
                className="h-4 w-4 rounded border-input"
              />
              {t("assignToMe")}
            </label>
          )}
        </CardContent>
      </Card>

      {error?.kind === "forbidden" ? (
        <EmptyState title={t("noPermission")} />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={tickets}
            rowKey={(ticket) => ticket.id}
            loading={loading}
            error={error ? localized.message : null}
            onRetry={refetch}
            emptyTitle={t("empty")}
            emptyMessage={t("emptyHint")}
            mobileCard={(ticket) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <Link
                    href={`/app/support/${ticket.id}`}
                    className="rounded-sm font-medium hover:underline"
                  >
                    {ticket.subject}
                  </Link>
                  <StatusBadge tone={toneForStatus(ticket.status)}>
                    {t(`status.${ticket.status}`)}
                  </StatusBadge>
                </div>
                <p className="font-mono text-xs text-muted-foreground">
                  {ticket.ticket_number}
                </p>
                <p className="text-sm text-muted-foreground">
                  {statusLabel(ticket.category, "support.categories")} ·{" "}
                  {new Date(ticket.updated_at).toLocaleDateString(locale)}
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
        </>
      )}

      {canCreate && (
        <CreateTicketDialog
          open={composing}
          onOpenChange={setComposing}
          onCreated={() => {
            setComposing(false);
            refetch();
          }}
        />
      )}
    </AppShell>
  );
}
