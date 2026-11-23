"use client";

import { useCallback, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CalendarCheck, Eye, SlidersHorizontal } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { useAuth } from "@/lib/auth-context";
import { commencementApi } from "@/lib/commencement-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import type {
  CommencementListResponse,
  CommencementStatusFilter,
  CommencementSummary,
  CommencementType,
} from "@/types/commencement";

const PAGE_SIZE = 25;
const MIN_REASON_LENGTH = 10;

type FormMode = "approve" | "correct";

interface FormState {
  mode: FormMode;
  date: string;
  type: CommencementType;
  reason: string;
  confirmed: boolean;
}

/**
 * The completion date is an institutional decision, so the page never computes
 * one. It shows the server's suggestion, and submitting sends back the exact
 * suggestion the approver ticked — if it has moved, the server refuses.
 */
export default function AttendanceCommencementPage() {
  const t = useTranslations("attendanceCommencement");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const { hasPermission } = useAuth();

  const allowed = hasPermission("attendance.manage_commencement");
  const [statusFilter, setStatusFilter] =
    useState<CommencementStatusFilter>("MISSING");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<CommencementSummary | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchQueue = useCallback(() => {
    if (!allowed) return Promise.resolve(null);
    return commencementApi.list({
      status: statusFilter,
      search: search.trim() || undefined,
      page,
      page_size: PAGE_SIZE,
    });
  }, [allowed, statusFilter, search, page]);
  const queue = useApi<CommencementListResponse | null>(
    fetchQueue,
    [allowed, statusFilter, search, page],
    "attendance commencement queue",
  );

  const fetchSummary = useCallback(
    () =>
      selected
        ? commencementApi.summary(selected.student_id, selected.admission_id)
        : Promise.resolve(null),
    [selected],
  );
  const summary = useApi<CommencementSummary | null>(
    fetchSummary,
    [selected?.admission_id],
    "attendance commencement detail",
  );

  const localizedError = localizeError(queue.error);
  const detail = summary.data;
  const detailError = summary.error ? localizeError(summary.error) : null;

  const formatDay = (value: string | null) =>
    value
      ? format.dateTime(new Date(`${value}T00:00:00Z`), {
          dateStyle: "medium",
          timeZone: "UTC",
        })
      : "—";

  const formatStamp = (value: string | null) =>
    value
      ? format.dateTime(new Date(value), {
          dateStyle: "medium",
          timeStyle: "short",
        })
      : "—";

  const typeOptions = useMemo(
    () =>
      (["SCHEDULED", "LATE_JOIN", "MANUAL"] as CommencementType[]).map((value) => ({
        value,
        label: t(
          value === "SCHEDULED"
            ? "types.SCHEDULED"
            : value === "LATE_JOIN"
              ? "types.LATE_JOIN"
              : "types.MANUAL",
        ),
      })),
    [t],
  );

  const statusOptions = useMemo(
    () => [
      { value: "MISSING", label: t("status.MISSING") },
      { value: "RECORDED", label: t("status.RECORDED") },
      { value: "ALL", label: t("status.ALL") },
    ],
    [t],
  );

  const openForm = (item: CommencementSummary, mode: FormMode) => {
    setForm({
      mode,
      date: mode === "correct" ? (item.current?.commencement_date ?? item.suggested_date) : item.suggested_date,
      type: mode === "correct" ? (item.current?.commencement_type ?? "SCHEDULED") : "SCHEDULED",
      reason: "",
      confirmed: false,
    });
  };

  const onDateChange = (value: string) => {
    if (!form || !selected) return;
    const suggested = selected.suggested_date;
    const nextType: CommencementType =
      value === suggested ? "SCHEDULED" : value > suggested ? "LATE_JOIN" : "MANUAL";
    setForm({ ...form, date: value, type: nextType });
  };

  const submit = async () => {
    if (!form || !selected) return;
    if (!selected.current && form.mode !== "approve") return;
    if (!form.confirmed) {
      toast.error(t("form.confirmRequired"));
      return;
    }
    if (!form.date) {
      toast.error(t("form.dateRequired"));
      return;
    }
    if (form.reason.trim().length < MIN_REASON_LENGTH) {
      toast.error(t("form.reasonRequired"));
      return;
    }

    setSaving(true);
    const payload = {
      commencement_date: form.date,
      commencement_type: form.type,
      reason: form.reason.trim(),
      confirmed_suggested_date: selected.suggested_date,
    };
    try {
      if (form.mode === "approve") {
        await commencementApi.approve(selected.student_id, selected.admission_id, payload);
        toast.success(t("approve.success"));
      } else {
        await commencementApi.correct(selected.student_id, selected.admission_id, payload);
        toast.success(t("correct.success"));
      }
      setForm(null);
      summary.refetch();
      queue.refetch();
    } catch (error) {
      const localized = localizeError(
        normalizeApiError(error, "attendance commencement submit"),
      );
      toast.error(localized.message);
    } finally {
      setSaving(false);
    }
  };

  const columns: Column<CommencementSummary>[] = [
    {
      key: "student",
      header: t("columns.student"),
      cell: (item) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{item.student_name}</p>
          <p className="font-mono text-xs text-muted-foreground" dir="ltr">
            {item.student_number}
          </p>
        </div>
      ),
    },
    {
      key: "intake",
      header: t("columns.intake"),
      hideOnMobile: true,
      cell: (item) => (
        <div className="min-w-0">
          <p className="truncate text-sm">{item.intake_name}</p>
          <p className="text-xs text-muted-foreground">
            {formatDay(item.intake_start_date)}
          </p>
        </div>
      ),
    },
    {
      key: "suggested",
      header: t("columns.suggested"),
      cell: (item) => (
        <div className="min-w-0">
          <p className="text-sm">{formatDay(item.suggested_date)}</p>
          <p className="text-xs text-muted-foreground">
            {t(
              item.suggestion_basis === "ACTIVATION"
                ? "basis.ACTIVATION"
                : "basis.INTAKE_START",
            )}
          </p>
        </div>
      ),
    },
    {
      key: "commencement",
      header: t("columns.commencement"),
      cell: (item) =>
        item.current ? (
          <StatusBadge tone="success">
            {t(
              item.current.commencement_type === "SCHEDULED"
                ? "types.SCHEDULED"
                : item.current.commencement_type === "LATE_JOIN"
                  ? "types.LATE_JOIN"
                  : "types.MANUAL",
            )}
            {" · "}
            {formatDay(item.current.commencement_date)}
          </StatusBadge>
        ) : (
          <StatusBadge tone="muted">{t("notCommenced")}</StatusBadge>
        ),
    },
    {
      key: "actions",
      header: t("columns.actions"),
      className: "text-end",
      cell: (item) => (
        <Button variant="outline" size="sm" onClick={() => setSelected(item)}>
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          {t("actions.review")}
        </Button>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={
          queue.data ? t("subtitleCount", { count: queue.data.total }) : t("subtitle")
        }
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
      />

      {!allowed ? (
        <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />
      ) : (
        <>
          <Card className="mb-4">
            <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
              <SlidersHorizontal
                className="h-4 w-4 text-muted-foreground"
                aria-hidden="true"
              />
              <CardTitle className="text-sm">{tCommon("labels.filters")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SearchInput
                value={search}
                onChange={(value) => {
                  setSearch(value);
                  setPage(1);
                }}
                placeholder={t("filters.searchPlaceholder")}
                className="sm:col-span-2 lg:col-span-1"
              />
              <FilterSelect
                label={t("filters.status")}
                value={statusFilter}
                showLabel
                options={statusOptions}
                onChange={(value) => {
                  setStatusFilter(value as CommencementStatusFilter);
                  setPage(1);
                }}
              />
              <div className="flex items-end">
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {t("filters.hint")}
                </p>
              </div>
            </CardContent>
          </Card>

          <DataTable
            columns={columns}
            rows={queue.data?.items ?? []}
            rowKey={(item) => item.admission_id}
            loading={queue.loading}
            error={queue.error ? localizedError.message : null}
            onRetry={queue.refetch}
            emptyTitle={t("emptyTitle")}
            emptyMessage={t("emptyMessage")}
          />

          {queue.data && (
            <Pagination
              page={queue.data.page}
              pageSize={queue.data.page_size}
              total={queue.data.total}
              totalPages={Math.max(1, Math.ceil(queue.data.total / queue.data.page_size))}
              onPageChange={setPage}
            />
          )}
        </>
      )}

      <Dialog
        open={!!selected}
        onOpenChange={(open) => {
          if (!open) {
            setSelected(null);
            setForm(null);
          }
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle>{selected.student_name}</DialogTitle>
                <DialogDescription>
                  {selected.student_number} · {selected.intake_name}
                </DialogDescription>
              </DialogHeader>

              {detailError ? (
                <div className="rounded-lg border border-destructive/40 p-3">
                  <p className="text-sm">{t("detail.loadError")}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {detailError.message}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-2"
                    onClick={() => summary.refetch()}
                  >
                    {t("detail.retry")}
                  </Button>
                </div>
              ) : detail ? (
                <>
                  <dl className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t("detail.admissionStatus")}
                      </dt>
                      <dd className="text-sm">{detail.admission_status}</dd>
                    </div>
                    <div>
                      <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t("detail.activated")}
                      </dt>
                      <dd className="text-sm">{formatDay(detail.activated_on)}</dd>
                    </div>
                    <div>
                      <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t("detail.suggested")}
                      </dt>
                      <dd className="text-sm">
                        {formatDay(detail.suggested_date)} ·{" "}
                        {t(
                          detail.suggestion_basis === "ACTIVATION"
                            ? "basis.ACTIVATION"
                            : "basis.INTAKE_START",
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t("detail.current")}
                      </dt>
                      <dd className="text-sm">
                        {detail.current
                          ? `${formatDay(detail.current.commencement_date)} · ${t(
                              detail.current.commencement_type === "SCHEDULED"
                                ? "types.SCHEDULED"
                                : detail.current.commencement_type === "LATE_JOIN"
                                  ? "types.LATE_JOIN"
                                  : "types.MANUAL",
                            )}`
                          : t("notCommenced")}
                      </dd>
                    </div>
                  </dl>

                  {detail.admission_status !== "ACTIVE" ? (
                    <p className="rounded-lg border border-border/70 bg-muted/40 p-3 text-sm">
                      {t("detail.ineligible", {
                        status: detail.admission_status,
                      })}
                    </p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {!detail.current && (
                        <Button onClick={() => openForm(selected, "approve")}>
                          <CalendarCheck className="me-1 h-4 w-4" aria-hidden="true" />
                          {t("actions.approve")}
                        </Button>
                      )}
                      {detail.current && (
                        <Button
                          variant="outline"
                          onClick={() => openForm(selected, "correct")}
                        >
                          {t("actions.correct")}
                        </Button>
                      )}
                    </div>
                  )}

                  <div>
                    <p className="mb-2 text-sm font-semibold">{t("detail.history")}</p>
                    {detail.history.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {t("detail.noHistory")}
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {detail.history.map((record) => (
                      <li
                        key={record.id}
                        className="rounded-lg border border-border/70 p-3 text-sm"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">
                            {formatDay(record.commencement_date)}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {t(
                              record.commencement_type === "SCHEDULED"
                                ? "types.SCHEDULED"
                                : record.commencement_type === "LATE_JOIN"
                                  ? "types.LATE_JOIN"
                                  : "types.MANUAL",
                            )}
                          </span>
                          {record.superseded_at && (
                            <StatusBadge tone="muted">
                              {t("detail.superseded")}
                            </StatusBadge>
                          )}
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t("detail.reason")}: {record.reason}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {t("detail.approvedBy", {
                            name: record.approved_by_name ?? "—",
                            date: formatStamp(record.approved_at),
                          })}
                        </p>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {tCommon("states.loading")}
                </p>
              )}

              <DialogFooter>
                <Button variant="outline" onClick={() => setSelected(null)}>
                  {tCommon("actions.close")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={!!form} onOpenChange={(open) => !open && setForm(null)}>
        <DialogContent className="sm:max-w-lg">
          {form && selected && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {form.mode === "approve" ? t("approve.title") : t("correct.title")}
                </DialogTitle>
                <DialogDescription>
                  {form.mode === "approve"
                    ? t("approve.description")
                    : t("correct.description")}
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-3">
                <div>
                  <label
                    htmlFor="commencement-date"
                    className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                  >
                    {t("form.date")}
                  </label>
                  <Input
                    id="commencement-date"
                    type="date"
                    dir="ltr"
                    value={form.date}
                    onChange={(event) => onDateChange(event.target.value)}
                    className="mt-1"
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("form.suggestedHint", {
                      date: formatDay(selected.suggested_date),
                    })}
                  </p>
                </div>

                <FilterSelect
                  label={t("form.type")}
                  value={form.type}
                  showLabel
                  options={typeOptions}
                  onChange={(value) =>
                    setForm({ ...form, type: value as CommencementType })
                  }
                />

                <div>
                  <label
                    htmlFor="commencement-reason"
                    className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                  >
                    {t("form.reason")}
                  </label>
                  <Textarea
                    id="commencement-reason"
                    value={form.reason}
                    onChange={(event) => setForm({ ...form, reason: event.target.value })}
                    className="mt-1"
                    rows={3}
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("form.reasonHint")}
                  </p>
                </div>

                <label className="flex items-start gap-2 rounded-lg border border-border/70 p-3 text-sm">
                  <input
                    type="checkbox"
                    checked={form.confirmed}
                    onChange={(event) =>
                      setForm({ ...form, confirmed: event.target.checked })
                    }
                    className="mt-0.5 h-4 w-4 rounded border-input accent-primary"
                  />
                  <span>
                    <span className="font-medium">{t("form.confirm")}</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {t("form.confirmHint", {
                        date: formatDay(selected.suggested_date),
                      })}
                    </span>
                  </span>
                </label>
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setForm(null)}>
                  {tCommon("actions.cancel")}
                </Button>
                <Button onClick={submit} disabled={saving}>
                  {saving
                    ? tCommon("states.saving")
                    : form.mode === "approve"
                      ? t("approve.submit")
                      : t("correct.submit")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
