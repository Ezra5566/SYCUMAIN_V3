"use client";

import { useCallback, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { CalendarDays, Plus } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { useAuth } from "@/lib/auth-context";
import { calendarApi } from "@/lib/calendar-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { DataTable, type Column } from "@/components/ui/data-table";
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
  CalendarCoverage,
  CalendarVacationRange,
  VacationRangeListResponse,
} from "@/types/calendar";

const MIN_REASON_LENGTH = 10;

/**
 * The reporting window is a *view*, not calendar data: it decides which dates
 * the page asks about. Winter and summer vacations are never generated — the
 * institution enters every range, and this page only reflects what it entered.
 */
function defaultWindow(): { start: string; end: string } {
  const year = new Date().getUTCFullYear();
  return { start: `${year}-01-01`, end: `${year}-12-31` };
}

interface CreateForm {
  start_date: string;
  end_date: string;
  title: string;
  reason: string;
}

interface AdjustForm {
  start_date: string;
  end_date: string;
  change_reason: string;
}

interface CancelForm {
  reason: string;
}

export default function UniversityCalendarPage() {
  const t = useTranslations("calendar");
  const tCommon = useTranslations("common");
  const tNav = useTranslations("navigation");
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const { hasPermission } = useAuth();

  const allowed = hasPermission("attendance.manage_calendar");

  const [window, setWindow] = useState(defaultWindow);
  const [includeCancelled, setIncludeCancelled] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<CreateForm>({
    start_date: "",
    end_date: "",
    title: "",
    reason: "",
  });

  const [adjusting, setAdjusting] = useState<CalendarVacationRange | null>(null);
  const [adjustForm, setAdjustForm] = useState<AdjustForm | null>(null);

  const [cancelling, setCancelling] = useState<CalendarVacationRange | null>(null);
  const [cancelForm, setCancelForm] = useState<CancelForm | null>(null);

  const [saving, setSaving] = useState(false);

  const fetchCoverage = useCallback(() => {
    if (!allowed) return Promise.resolve(null);
    return calendarApi.coverage(window.start, window.end);
  }, [allowed, window.start, window.end]);
  const coverage = useApi<CalendarCoverage | null>(
    fetchCoverage,
    [allowed, window.start, window.end],
    "university calendar coverage",
  );

  const fetchRanges = useCallback(() => {
    if (!allowed) return Promise.resolve(null);
    return calendarApi.listRanges({
      startDate: window.start,
      endDate: window.end,
      includeCancelled,
    });
  }, [allowed, window.start, window.end, includeCancelled]);
  const ranges = useApi<VacationRangeListResponse | null>(
    fetchRanges,
    [allowed, window.start, window.end, includeCancelled],
    "vacation ranges",
  );

  const localizedError = localizeError(ranges.error);
  const coverageError = coverage.error ? localizeError(coverage.error) : null;

  const formatDay = (value: string | null) =>
    value
      ? format.dateTime(new Date(`${value}T00:00:00Z`), {
          dateStyle: "medium",
          timeZone: "UTC",
        })
      : "—";

  const validateRange = (start: string, end: string, reason: string) => {
    if (!start || !end) {
      toast.error(t("validation.datesRequired"));
      return false;
    }
    if (end < start) {
      toast.error(t("validation.order"));
      return false;
    }
    if (reason.trim().length < MIN_REASON_LENGTH) {
      toast.error(t("validation.reasonRequired"));
      return false;
    }
    return true;
  };

  const submitCreate = async () => {
    if (!createForm.title.trim()) {
      toast.error(t("validation.titleRequired"));
      return;
    }
    if (
      !validateRange(createForm.start_date, createForm.end_date, createForm.reason)
    ) {
      return;
    }
    setSaving(true);
    try {
      await calendarApi.createRange({
        start_date: createForm.start_date,
        end_date: createForm.end_date,
        title: createForm.title.trim(),
        reason: createForm.reason.trim(),
      });
      toast.success(t("create.success"));
      setCreateOpen(false);
      setCreateForm({ start_date: "", end_date: "", title: "", reason: "" });
      ranges.refetch();
      coverage.refetch();
    } catch (error) {
      const localized = localizeError(
        normalizeApiError(error, "vacation range create"),
      );
      toast.error(localized.message);
    } finally {
      setSaving(false);
    }
  };

  const openAdjust = (range: CalendarVacationRange) => {
    setAdjusting(range);
    setAdjustForm({
      start_date: range.start_date,
      end_date: range.end_date,
      change_reason: "",
    });
  };

  const submitAdjust = async () => {
    if (!adjusting || !adjustForm) return;
    if (
      !validateRange(
        adjustForm.start_date,
        adjustForm.end_date,
        adjustForm.change_reason,
      )
    ) {
      return;
    }
    setSaving(true);
    try {
      await calendarApi.adjustRange(adjusting.id, {
        start_date: adjustForm.start_date,
        end_date: adjustForm.end_date,
        change_reason: adjustForm.change_reason.trim(),
      });
      toast.success(t("adjust.success"));
      setAdjusting(null);
      setAdjustForm(null);
      ranges.refetch();
      coverage.refetch();
    } catch (error) {
      const localized = localizeError(
        normalizeApiError(error, "vacation range adjust"),
      );
      toast.error(localized.message);
    } finally {
      setSaving(false);
    }
  };

  const submitCancel = async () => {
    if (!cancelling || !cancelForm) return;
    if (cancelForm.reason.trim().length < MIN_REASON_LENGTH) {
      toast.error(t("validation.reasonRequired"));
      return;
    }
    setSaving(true);
    try {
      await calendarApi.cancelRange(cancelling.id, cancelForm.reason.trim());
      toast.success(t("cancel.success"));
      setCancelling(null);
      setCancelForm(null);
      ranges.refetch();
      coverage.refetch();
    } catch (error) {
      const localized = localizeError(
        normalizeApiError(error, "vacation range cancel"),
      );
      toast.error(localized.message);
    } finally {
      setSaving(false);
    }
  };

  const stats = useMemo(() => {
    const data = coverage.data;
    if (!data) return [];
    return [
      { key: "totalDays", value: data.total_days },
      { key: "workingDays", value: data.working_days },
      { key: "vacationDays", value: data.vacations.length },
      { key: "holidays", value: data.holidays.length },
      { key: "closures", value: data.closures.length },
      {
        key: "exceptionalWorkingDays",
        value: data.exceptional_working_days.length,
      },
    ] as const;
  }, [coverage.data]);

  const columns: Column<CalendarVacationRange>[] = [
    {
      key: "vacation",
      header: t("columns.vacation"),
      cell: (item) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{item.title}</p>
          <p className="truncate text-xs text-muted-foreground">{item.reason}</p>
        </div>
      ),
    },
    {
      key: "start",
      header: t("columns.start"),
      cell: (item) => <span className="text-sm">{formatDay(item.start_date)}</span>,
    },
    {
      key: "end",
      header: t("columns.end"),
      hideOnMobile: true,
      cell: (item) => <span className="text-sm">{formatDay(item.end_date)}</span>,
    },
    {
      key: "status",
      header: t("columns.status"),
      cell: (item) => (
        <StatusBadge tone={item.is_cancelled ? "muted" : "success"}>
          {t(item.is_cancelled ? "status.CANCELLED" : "status.ACTIVE")}
        </StatusBadge>
      ),
    },
    {
      key: "dates",
      header: t("columns.dates"),
      hideOnMobile: true,
      cell: (item) => (
        <div className="min-w-0 text-xs text-muted-foreground">
          <p>{t("history.days", { count: item.dates.length })}</p>
          {item.detached_dates.length > 0 && (
            <p className="text-amber-600 dark:text-amber-400">
              {t("history.detached", { count: item.detached_dates.length })}
            </p>
          )}
          {item.voided_date_count > 0 && (
            <p>{t("history.voided", { count: item.voided_date_count })}</p>
          )}
        </div>
      ),
    },
    {
      key: "actions",
      header: t("columns.actions"),
      className: "text-end",
      cell: (item) => (
        <div className="flex flex-wrap justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={item.is_cancelled}
            onClick={() => openAdjust(item)}
          >
            {t("actions.adjust")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={item.is_cancelled}
            onClick={() => {
              setCancelling(item);
              setCancelForm({ reason: "" });
            }}
          >
            {t("actions.cancel")}
          </Button>
        </div>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: tNav("academics"), href: "/app/academics" },
          { label: t("title") },
        ]}
      />

      {!allowed ? (
        <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />
      ) : (
        <>
          <Card className="mb-4">
            <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
              <CalendarDays className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <CardTitle className="text-sm">{t("window.title")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <div>
                <label
                  htmlFor="calendar-window-start"
                  className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                >
                  {t("window.start")}
                </label>
                <Input
                  id="calendar-window-start"
                  type="date"
                  dir="ltr"
                  value={window.start}
                  onChange={(event) => setWindow({ ...window, start: event.target.value })}
                  className="mt-1"
                />
              </div>
              <div>
                <label
                  htmlFor="calendar-window-end"
                  className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                >
                  {t("window.end")}
                </label>
                <Input
                  id="calendar-window-end"
                  type="date"
                  dir="ltr"
                  value={window.end}
                  onChange={(event) => setWindow({ ...window, end: event.target.value })}
                  className="mt-1"
                />
              </div>
              <label className="flex items-end gap-2 pb-2 text-sm">
                <input
                  type="checkbox"
                  checked={includeCancelled}
                  onChange={(event) => setIncludeCancelled(event.target.checked)}
                  className="h-4 w-4 rounded border-input accent-primary"
                />
                {t("ranges.includeCancelled")}
              </label>
            </CardContent>
          </Card>

          <Card className="mb-4">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">{t("coverage.title")}</CardTitle>
            </CardHeader>
            <CardContent>
              {coverageError ? (
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <p>{coverageError.message}</p>
                  <Button variant="outline" size="sm" onClick={coverage.refetch}>
                    {tCommon("actions.retry")}
                  </Button>
                </div>
              ) : coverage.data ? (
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                  {stats.map((stat) => (
                    <div key={stat.key}>
                      <dt className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t(`coverage.${stat.key}`)}
                      </dt>
                      <dd className="font-mono text-lg">{stat.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {tCommon("states.loading")}
                </p>
              )}
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                {t("limitation")}
              </p>
            </CardContent>
          </Card>

          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold">{t("ranges.title")}</h2>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus className="me-1 h-4 w-4" aria-hidden="true" />
              {t("ranges.create")}
            </Button>
          </div>

          <DataTable
            columns={columns}
            rows={ranges.data?.items ?? []}
            rowKey={(item) => item.id}
            loading={ranges.loading}
            error={ranges.error ? localizedError.message : null}
            onRetry={ranges.refetch}
            emptyTitle={t("ranges.emptyTitle")}
            emptyMessage={t("ranges.emptyMessage")}
          />
        </>
      )}

      {/* Create */}
      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("create.title")}</DialogTitle>
            <DialogDescription>{t("create.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label
                  htmlFor="vacation-start"
                  className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                >
                  {t("create.start")}
                </label>
                <Input
                  id="vacation-start"
                  type="date"
                  dir="ltr"
                  value={createForm.start_date}
                  onChange={(event) =>
                    setCreateForm({ ...createForm, start_date: event.target.value })
                  }
                  className="mt-1"
                />
              </div>
              <div>
                <label
                  htmlFor="vacation-end"
                  className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                >
                  {t("create.end")}
                </label>
                <Input
                  id="vacation-end"
                  type="date"
                  dir="ltr"
                  value={createForm.end_date}
                  onChange={(event) =>
                    setCreateForm({ ...createForm, end_date: event.target.value })
                  }
                  className="mt-1"
                />
              </div>
            </div>
            <div>
              <label
                htmlFor="vacation-title"
                className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
              >
                {t("create.name")}
              </label>
              <Input
                id="vacation-title"
                value={createForm.title}
                onChange={(event) =>
                  setCreateForm({ ...createForm, title: event.target.value })
                }
                className="mt-1"
              />
            </div>
            <div>
              <label
                htmlFor="vacation-reason"
                className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
              >
                {t("create.reason")}
              </label>
              <Textarea
                id="vacation-reason"
                value={createForm.reason}
                onChange={(event) =>
                  setCreateForm({ ...createForm, reason: event.target.value })
                }
                className="mt-1"
                rows={3}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {t("create.reasonHint")}
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              {tCommon("actions.cancel")}
            </Button>
            <Button onClick={submitCreate} disabled={saving}>
              {saving ? tCommon("states.saving") : t("create.submit")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Adjust */}
      <Dialog
        open={!!adjusting}
        onOpenChange={(open) => {
          if (!open) {
            setAdjusting(null);
            setAdjustForm(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          {adjusting && adjustForm && (
            <>
              <DialogHeader>
                <DialogTitle>{t("adjust.title")}</DialogTitle>
                <DialogDescription>
                  {t("adjust.description", { title: adjusting.title })}
                </DialogDescription>
              </DialogHeader>
              <div className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label
                      htmlFor="adjust-start"
                      className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                    >
                      {t("adjust.start")}
                    </label>
                    <Input
                      id="adjust-start"
                      type="date"
                      dir="ltr"
                      value={adjustForm.start_date}
                      onChange={(event) =>
                        setAdjustForm({ ...adjustForm, start_date: event.target.value })
                      }
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <label
                      htmlFor="adjust-end"
                      className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                    >
                      {t("adjust.end")}
                    </label>
                    <Input
                      id="adjust-end"
                      type="date"
                      dir="ltr"
                      value={adjustForm.end_date}
                      onChange={(event) =>
                        setAdjustForm({ ...adjustForm, end_date: event.target.value })
                      }
                      className="mt-1"
                    />
                  </div>
                </div>
                <div>
                  <label
                    htmlFor="adjust-reason"
                    className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                  >
                    {t("adjust.changeReason")}
                  </label>
                  <Textarea
                    id="adjust-reason"
                    value={adjustForm.change_reason}
                    onChange={(event) =>
                      setAdjustForm({
                        ...adjustForm,
                        change_reason: event.target.value,
                      })
                    }
                    className="mt-1"
                    rows={3}
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("adjust.changeReasonHint")}
                  </p>
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setAdjusting(null)}>
                  {tCommon("actions.cancel")}
                </Button>
                <Button onClick={submitAdjust} disabled={saving}>
                  {saving ? tCommon("states.saving") : t("adjust.submit")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Cancel */}
      <Dialog
        open={!!cancelling}
        onOpenChange={(open) => {
          if (!open) {
            setCancelling(null);
            setCancelForm(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          {cancelling && cancelForm && (
            <>
              <DialogHeader>
                <DialogTitle>{t("cancel.title")}</DialogTitle>
                <DialogDescription>
                  {t("cancel.description", { title: cancelling.title })}
                </DialogDescription>
              </DialogHeader>
              <div>
                <label
                  htmlFor="cancel-reason"
                  className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                >
                  {t("cancel.reason")}
                </label>
                <Textarea
                  id="cancel-reason"
                  value={cancelForm.reason}
                  onChange={(event) =>
                    setCancelForm({ reason: event.target.value })
                  }
                  className="mt-1"
                  rows={3}
                />
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("cancel.reasonHint")}
                </p>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setCancelling(null)}>
                  {tCommon("actions.cancel")}
                </Button>
                <Button onClick={submitCancel} disabled={saving}>
                  {saving ? tCommon("states.saving") : t("cancel.submit")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
