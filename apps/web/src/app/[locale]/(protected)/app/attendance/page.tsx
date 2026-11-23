"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Link, useRouter } from "@/i18n/navigation";
import {
  CalendarPlus,
  ClipboardCheck,
  Eye,
  PencilLine,
  SlidersHorizontal,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { useAuth } from "@/lib/auth-context";
import { attendanceApi } from "@/lib/attendance-absence-api";
import { listPeriods } from "@/lib/academic-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DormitoryAttendancePanel } from "./dormitory-panel";
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
  Absence,
  StudentAttendanceDetail,
  StudentAttendanceList,
  StudentAttendanceRow,
} from "@/types/attendance-absence";

const PAGE_SIZE = 25;
const MIN_CORRECTION_REASON_LENGTH = 10;
const MIN_CANCELLATION_REASON_LENGTH = 10;

type FormMode = "record" | "correct" | "cancel";

interface FormState {
  mode: FormMode;
  date: string;
  reason: string;
  absenceId?: string;
}

/**
 * Attendance is a student-level figure: a percentage derived from university
 * working days and recorded absences. Nothing here computes it — the server owns
 * the calendar and the approved commencement, so it owns the number too. The
 * page only asks for a date and a reason and shows the server's answer.
 */
export default function AttendancePage() {
  const t = useTranslations("attendanceAbsence");
  const { hasRole, hasPermission } = useAuth();

  if (hasRole("STUDENT") && !hasPermission("attendance.record_absence")) {
    return <MyAttendanceView />;
  }
  return <StaffAttendanceView />;
}

// ── Student self-view ──

function MyAttendanceView() {
  const t = useTranslations("attendanceAbsence");
  const tDorm = useTranslations("dormitoryAttendance");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();
  const allowed = hasPermission("attendance.view");
  const [tab, setTab] = useState<"academic" | "dormitory">("academic");

  const fetchMine = useCallback(
    () => (allowed ? attendanceApi.me() : Promise.resolve(null)),
    [allowed],
  );
  const mine = useApi(fetchMine, [allowed], "my attendance");

  const formatDay = (value: string | null) =>
    value
      ? format.dateTime(new Date(`${value}T00:00:00Z`), {
          dateStyle: "medium",
          timeZone: "UTC",
        })
      : "—";

  const localizedError = localizeError(mine.error);

  return (
    <AppShell>
      <PageHeader
        title={tab === "dormitory" ? tDorm("myTitle") : t("myTitle")}
        description={tab === "dormitory" ? tDorm("mySubtitle") : t("mySubtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
      />

      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as "academic" | "dormitory")}
      >
        <TabsList>
          <TabsTrigger value="academic">{t("tabsAcademic")}</TabsTrigger>
          <TabsTrigger value="dormitory">{t("tabsDormitory")}</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === "dormitory" ? (
        <DormitoryAttendancePanel mode="self" />
      ) : !allowed ? (
        <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />
      ) : mine.error ? (
        <EmptyState
          title={tCommon("states.error")}
          message={localizedError.message}
        />
      ) : mine.loading ? (
        <p className="text-sm text-muted-foreground">{tCommon("states.loading")}</p>
      ) : !mine.data || mine.data.episodes.length === 0 ? (
        <EmptyState title={t("myEmptyTitle")} message={t("myEmpty")} />
      ) : (
        <div className="space-y-4">
          {mine.data.episodes.map((episode) => (
            <Card key={episode.admission_id}>
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <CardTitle className="text-base">{episode.period_name}</CardTitle>
                  <StatusBadge tone={episode.eligible ? "success" : "muted"}>
                    {episode.eligible
                      ? episode.admission_status
                      : t("notEligible")}
                  </StatusBadge>
                </div>
                <p className="text-xs text-muted-foreground">
                  {t("status")}: {episode.admission_status}
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border border-border/70 p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      {t("myPercentage")}
                    </p>
                    <p className="mt-1 text-2xl font-semibold tabular-nums">
                      {episode.percentage === null
                        ? t("noFigure")
                        : t("percentValue", { value: episode.percentage })}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/70 p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      {t("myEligibleDays")}
                    </p>
                    <p className="mt-1 text-2xl font-semibold tabular-nums">
                      {episode.eligible_days}
                    </p>
                  </div>
                  <div className="rounded-lg border border-border/70 p-3">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      {t("myAbsences")}
                    </p>
                    <p className="mt-1 text-2xl font-semibold tabular-nums">
                      {episode.absence_count}
                    </p>
                  </div>
                </div>

                {episode.excluded_absence_count > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {t("excludedAbsences", {
                      count: episode.excluded_absence_count,
                    })}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>
                    {t("columnsCommencement")}: {formatDay(episode.commencement_date)}
                  </span>
                  <span aria-hidden="true">·</span>
                  <span>
                    {t("columnsIntake")}: {episode.period_name}
                  </span>
                </div>

                <div>
                  <p className="mb-2 text-sm font-semibold">{t("historyTitle")}</p>
                  {episode.absences.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      {t("historyEmpty")}
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {episode.absences.map((absence) => (
                        <li
                          key={absence.id}
                          className="rounded-lg border border-border/70 p-3 text-sm"
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium">
                              {formatDay(absence.absence_date)}
                            </span>
                            {absence.cancelled_at && (
                              <StatusBadge tone="danger">
                                {t("cancelled")}
                              </StatusBadge>
                            )}
                          </div>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {absence.reason}
                          </p>
                          {absence.cancelled_at && (
                            <p className="mt-1 text-xs text-muted-foreground">
                              {t("cancellationReason")}:{" "}
                              {absence.cancellation_reason}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </AppShell>
  );
}

// ── Staff view ──

function StaffAttendanceView() {
  const t = useTranslations("attendanceAbsence");
  const tDorm = useTranslations("dormitoryAttendance");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const { hasPermission } = useAuth();

  const canView = hasPermission("attendance.view");
  const canRecord = hasPermission("attendance.record_absence");
  const canManageCommencement = hasPermission(
    "attendance.manage_commencement",
  );
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedStudent = searchParams.get("student");

  const [search, setSearch] = useState("");
  const [periodId, setPeriodId] = useState("");
  const [page, setPage] = useState(1);
  // A student-profile link opens that student directly; the list stays behind
  // so closing the dialog leaves the user in the attendance workspace.
  const [selectedId, setSelectedId] = useState<string | null>(requestedStudent);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<"academic" | "dormitory">("academic");

  useEffect(() => {
    if (requestedStudent) setSelectedId(requestedStudent);
  }, [requestedStudent]);

  const fetchStudents = useCallback(() => {
    if (!canView) return Promise.resolve(null);
    return attendanceApi.listStudents({
      search: search.trim() || undefined,
      periodId: periodId || undefined,
      page,
      pageSize: PAGE_SIZE,
    });
  }, [canView, search, periodId, page]);
  const students = useApi<StudentAttendanceList | null>(
    fetchStudents,
    [canView, search, periodId, page],
    "attendance students",
  );

  const fetchPeriods = useCallback(
    () => (canView ? listPeriods(1, 50) : Promise.resolve(null)),
    [canView],
  );
  const periods = useApi(fetchPeriods, [canView], "attendance periods");

  const fetchDetail = useCallback(
    () => (selectedId ? attendanceApi.detail(selectedId) : Promise.resolve(null)),
    [selectedId],
  );
  const detail = useApi<StudentAttendanceDetail | null>(
    fetchDetail,
    [selectedId],
    "attendance detail",
  );

  const localizedError = localizeError(students.error);
  const detailError = detail.error ? localizeError(detail.error) : null;
  const record = detail.data;

  const formatDay = (value: string | null) =>
    value
      ? format.dateTime(new Date(`${value}T00:00:00Z`), {
          dateStyle: "medium",
          timeZone: "UTC",
        })
      : "—";

  const formatStamp = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });

  const periodOptions = useMemo(
    () => [
      { value: "", label: t("allIntakes") },
      ...(periods.data?.items ?? []).map((period) => ({
        value: period.id,
        label: period.name,
      })),
    ],
    [periods.data, t],
  );

  const today = new Date().toISOString().slice(0, 10);

  const openDetail = (item: StudentAttendanceRow) => {
    setSelectedId(item.student_id);
    setForm(null);
  };

  const closeDetail = () => {
    setSelectedId(null);
    setForm(null);
    // Drop the deep-link parameter so a refresh does not reopen the dialog.
    if (requestedStudent) router.replace("/app/attendance");
  };

  const startRecord = () => {
    if (!record) return;
    setForm({ mode: "record", date: today, reason: "" });
  };

  const startCorrect = (absence: Absence) => {
    setForm({
      mode: "correct",
      date: absence.absence_date,
      reason: "",
      absenceId: absence.id,
    });
  };

  const startCancel = (absence: Absence) => {
    setForm({
      mode: "cancel",
      date: absence.absence_date,
      reason: "",
      absenceId: absence.id,
    });
  };

  const submit = async () => {
    if (!form || !record) return;
    if (!form.date) {
      toast.error(t("recordDate"));
      return;
    }
    const reason = form.reason.trim();
    if (form.mode === "record" && reason.length === 0) {
      toast.error(t("recordReason"));
      return;
    }
    if (
      form.mode === "correct" &&
      reason.length < MIN_CORRECTION_REASON_LENGTH
    ) {
      toast.error(t("correctReasonHint"));
      return;
    }
    if (
      form.mode === "cancel" &&
      reason.length < MIN_CANCELLATION_REASON_LENGTH
    ) {
      toast.error(t("cancelReasonHint"));
      return;
    }

    setSaving(true);
    try {
      if (form.mode === "record") {
        await attendanceApi.record(record.student_id, {
          admission_id: record.admission_id,
          absence_date: form.date,
          reason,
        });
        toast.success(t("recordSuccess"));
      } else if (form.mode === "cancel" && form.absenceId) {
        await attendanceApi.cancel(record.student_id, form.absenceId, {
          reason,
        });
        toast.success(t("cancelSuccess"));
      } else if (form.absenceId) {
        await attendanceApi.correct(record.student_id, form.absenceId, {
          absence_date: form.date,
          reason,
        });
        toast.success(t("correctSuccess"));
      }
      setForm(null);
      detail.refetch();
      students.refetch();
    } catch (error) {
      toast.error(
        localizeError(normalizeApiError(error, "attendance submit")).message,
      );
    } finally {
      setSaving(false);
    }
  };

  const columns: Column<StudentAttendanceRow>[] = [
    {
      key: "student",
      header: t("columnsStudent"),
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
      header: t("columnsIntake"),
      hideOnMobile: true,
      cell: (item) => <span className="text-sm">{item.period_name}</span>,
    },
    {
      key: "commencement",
      header: t("columnsCommencement"),
      hideOnMobile: true,
      cell: (item) =>
        item.commencement_date ? (
          <span className="text-sm">{formatDay(item.commencement_date)}</span>
        ) : (
          <StatusBadge tone="muted">{t("notEligible")}</StatusBadge>
        ),
    },
    {
      key: "eligibleDays",
      header: t("columnsEligibleDays"),
      className: "text-end",
      cell: (item) => (
        <span className="tabular-nums text-sm">{item.eligible_days}</span>
      ),
    },
    {
      key: "absences",
      header: t("columnsAbsences"),
      className: "text-end",
      cell: (item) => (
        <span className="tabular-nums text-sm">{item.absence_count}</span>
      ),
    },
    {
      key: "percentage",
      header: t("columnsPercentage"),
      className: "text-end",
      cell: (item) =>
        item.percentage === null ? (
          <span className="text-sm text-muted-foreground">{t("noFigure")}</span>
        ) : (
          <span className="tabular-nums text-sm font-semibold">
            {t("percentValue", { value: item.percentage })}
          </span>
        ),
    },
    {
      key: "actions",
      header: "",
      className: "text-end",
      cell: (item) => (
        <Button variant="outline" size="sm" onClick={() => openDetail(item)}>
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          {tCommon("actions.view")}
        </Button>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={tab === "dormitory" ? tDorm("title") : t("title")}
        description={tab === "dormitory" ? tDorm("subtitle") : t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
      />

      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as "academic" | "dormitory")}
      >
        <TabsList>
          <TabsTrigger value="academic">{t("tabsAcademic")}</TabsTrigger>
          <TabsTrigger value="dormitory">{t("tabsDormitory")}</TabsTrigger>
        </TabsList>
      </Tabs>

      {tab === "dormitory" ? (
        <DormitoryAttendancePanel mode="staff" />
      ) : !canView ? (
        <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />
      ) : (
        <>
          <Card className="mb-4">
            <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
              <SlidersHorizontal
                className="h-4 w-4 text-muted-foreground"
                aria-hidden="true"
              />
              <CardTitle className="text-sm">{t("filtersTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SearchInput
                value={search}
                onChange={(value) => {
                  setSearch(value);
                  setPage(1);
                }}
                placeholder={t("searchPlaceholder")}
                className="sm:col-span-2 lg:col-span-2"
              />
              <FilterSelect
                label={t("intakeLabel")}
                value={periodId}
                showLabel
                options={periodOptions}
                onChange={(value) => {
                  setPeriodId(value);
                  setPage(1);
                }}
              />
              <div className="flex items-end">
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {t("subtitle")}
                </p>
              </div>
            </CardContent>
          </Card>

          <DataTable
            columns={columns}
            rows={students.data?.items ?? []}
            rowKey={(item) => `${item.student_id}:${item.admission_id}`}
            loading={students.loading}
            error={students.error ? localizedError.message : null}
            onRetry={students.refetch}
            emptyTitle={t("emptyTitle")}
            emptyMessage={t("emptyMessage")}
            mobileCard={(item) => (
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <p className="font-medium">{item.student_name}</p>
                  <span className="tabular-nums text-sm font-semibold">
                    {item.percentage === null
                      ? t("noFigure")
                      : t("percentValue", { value: item.percentage })}
                  </span>
                </div>
                <p className="font-mono text-xs text-muted-foreground" dir="ltr">
                  {item.student_number}
                </p>
                <div className="flex flex-wrap gap-2 pt-1 text-xs text-muted-foreground">
                  <span>{item.period_name}</span>
                  <span>·</span>
                  <span>
                    {t("columnsAbsences")}: {item.absence_count}
                  </span>
                  <span>·</span>
                  <span>
                    {t("columnsEligibleDays")}: {item.eligible_days}
                  </span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={() => openDetail(item)}
                >
                  {tCommon("actions.view")}
                </Button>
              </div>
            )}
          />

          {students.data && (
            <Pagination
              page={students.data.page}
              pageSize={students.data.page_size}
              total={students.data.total}
              totalPages={Math.max(
                1,
                Math.ceil(students.data.total / students.data.page_size),
              )}
              onPageChange={setPage}
            />
          )}
        </>
      )}

      <Dialog open={!!selectedId} onOpenChange={(open) => !open && closeDetail()}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          {selectedId && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {record?.student_name ?? t("detailTitle")}
                </DialogTitle>
                <DialogDescription>
                  {record
                    ? `${record.student_number} · ${record.period_name}`
                    : tCommon("states.loading")}
                </DialogDescription>
              </DialogHeader>

              {detailError ? (
                detail.error?.code === "ABSENCE_NO_ADMISSION" ? (
                  <EmptyState
                    title={t("detailEmptyTitle")}
                    message={t("noAdmission")}
                  />
                ) : (
                  <div className="rounded-lg border border-destructive/40 p-3">
                    <p className="text-sm">{tCommon("states.error")}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {detailError.message}
                    </p>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-2"
                      onClick={() => detail.refetch()}
                    >
                      {tCommon("actions.retry")}
                    </Button>
                  </div>
                )
              ) : !record ? (
                <p className="text-sm text-muted-foreground">
                  {tCommon("states.loading")}
                </p>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-lg border border-border/70 p-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t("columnsPercentage")}
                      </p>
                      <p className="mt-1 flex items-center gap-2 text-2xl font-semibold tabular-nums">
                        <ClipboardCheck
                          className="h-4 w-4 text-primary"
                          aria-hidden="true"
                        />
                        {record.percentage === null
                          ? t("noFigure")
                          : t("percentValue", { value: record.percentage })}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border/70 p-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t("columnsEligibleDays")}
                      </p>
                      <p className="mt-1 text-2xl font-semibold tabular-nums">
                        {record.eligible_days}
                      </p>
                    </div>
                    <div className="rounded-lg border border-border/70 p-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                        {t("columnsAbsences")}
                      </p>
                      <p className="mt-1 text-2xl font-semibold tabular-nums">
                        {record.absence_count}
                      </p>
                    </div>
                  </div>

                  {record.excluded_absence_count > 0 && (
                    <p className="rounded-lg border border-border/70 bg-muted/40 p-3 text-xs text-muted-foreground">
                      {t("excludedAbsences", {
                        count: record.excluded_absence_count,
                      })}
                    </p>
                  )}

                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <StatusBadge tone={record.eligible ? "success" : "muted"}>
                      {record.eligible
                        ? record.admission_status
                        : record.ineligible_reason
                          ? t(`reasons.${record.ineligible_reason}`)
                          : t("notEligible")}
                    </StatusBadge>
                    <span>
                      {t("columnsCommencement")}:{" "}
                      {formatDay(record.commencement_date)}
                    </span>
                    <span aria-hidden="true">·</span>
                    <span>
                      {t("status")}: {record.admission_status}
                    </span>
                  </div>

                  {!record.eligible && (
                    <div className="rounded-lg border border-border/70 bg-muted/40 p-3 text-xs text-muted-foreground">
                      <p>
                        {record.ineligible_reason === "NO_COMMENCEMENT"
                          ? t("commencementRequired")
                          : record.ineligible_reason === "NOT_STARTED"
                            ? t("commencementFuture", {
                                date: formatDay(record.commencement_date),
                              })
                            : t("admissionInactive")}
                      </p>
                      {record.ineligible_reason === "NO_COMMENCEMENT" &&
                        canManageCommencement && (
                          <Link
                            href="/app/admissions/commencement"
                            className="mt-1 inline-block font-medium text-primary underline"
                          >
                            {t("approveCommencement")}
                          </Link>
                        )}
                    </div>
                  )}

                  {canRecord && record.eligible && !form && (
                    <Button onClick={startRecord}>
                      <CalendarPlus className="me-1 h-4 w-4" aria-hidden="true" />
                      {t("recordTitle")}
                    </Button>
                  )}

                  {form && (
                    <div className="space-y-3 rounded-lg border border-border/80 p-3">
                      <p className="text-sm font-semibold">
                        {form.mode === "record"
                          ? t("recordTitle")
                          : form.mode === "cancel"
                            ? t("cancelTitle")
                            : t("correctTitle")}
                      </p>
                      {form.mode === "cancel" ? (
                        <p className="text-xs text-muted-foreground">
                          {t("cancelDescription")}
                        </p>
                      ) : (
                        <div>
                          <label
                            htmlFor="absence-date"
                            className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                          >
                            {form.mode === "record"
                              ? t("recordDate")
                              : t("correctDate")}
                          </label>
                          <Input
                            id="absence-date"
                            type="date"
                            dir="ltr"
                            max={today}
                            value={form.date}
                            onChange={(event) =>
                              setForm({ ...form, date: event.target.value })
                            }
                            className="mt-1"
                          />
                        </div>
                      )}
                      <div>
                        <label
                          htmlFor="absence-reason"
                          className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                        >
                          {form.mode === "record"
                            ? t("recordReason")
                            : form.mode === "cancel"
                              ? t("cancelReason")
                              : t("correctReason")}
                        </label>
                        <Textarea
                          id="absence-reason"
                          value={form.reason}
                          onChange={(event) =>
                            setForm({ ...form, reason: event.target.value })
                          }
                          className="mt-1"
                          rows={3}
                        />
                        <p className="mt-1 text-xs text-muted-foreground">
                          {form.mode === "record"
                            ? t("recordReasonHint")
                            : form.mode === "cancel"
                              ? t("cancelReasonHint")
                              : t("correctReasonHint")}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button onClick={submit} disabled={saving}>
                          {saving
                            ? form.mode === "record"
                              ? t("recording")
                              : form.mode === "cancel"
                                ? t("cancelling")
                                : t("correcting")
                            : form.mode === "record"
                              ? t("recordSubmit")
                              : form.mode === "cancel"
                                ? t("cancelSubmit")
                                : t("correctSubmit")}
                        </Button>
                        <Button
                          variant="outline"
                          onClick={() => setForm(null)}
                          disabled={saving}
                        >
                          {tCommon("actions.cancel")}
                        </Button>
                      </div>
                    </div>
                  )}

                  <div>
                    <p className="mb-2 text-sm font-semibold">{t("historyTitle")}</p>
                    {record.absences.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {t("historyEmpty")}
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {record.absences.map((absence) => (
                          <li
                            key={absence.id}
                            className="rounded-lg border border-border/70 p-3 text-sm"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium">
                                {formatDay(absence.absence_date)}
                              </span>
                              {absence.cancelled_at && (
                                <StatusBadge tone="danger">
                                  {t("cancelled")}
                                </StatusBadge>
                              )}
                              {!absence.cancelled_at && absence.superseded_at && (
                                <StatusBadge tone="muted">
                                  {t("historySuperseded")}
                                </StatusBadge>
                              )}
                              {!absence.superseded_at &&
                                !absence.cancelled_at &&
                                canRecord &&
                                !form && (
                                  <>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => startCorrect(absence)}
                                    >
                                      <PencilLine
                                        className="h-3.5 w-3.5"
                                        aria-hidden="true"
                                      />
                                      {t("correctTitle")}
                                    </Button>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      onClick={() => startCancel(absence)}
                                    >
                                      {t("cancelAction")}
                                    </Button>
                                  </>
                                )}
                            </div>
                            <p className="mt-1 text-xs text-muted-foreground">
                              {absence.reason}
                            </p>
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              {t("historyRecordedBy", {
                                name: absence.recorded_by_name ?? "—",
                                date: formatStamp(absence.recorded_at),
                              })}
                            </p>
                            {absence.cancelled_at && (
                              <p className="mt-1 text-xs text-muted-foreground">
                                {t("cancellationReason")}:{" "}
                                {absence.cancellation_reason}
                                <br />
                                {t("cancelledBy", {
                                  name: absence.cancelled_by_name ?? "—",
                                  date: formatStamp(absence.cancelled_at),
                                })}
                              </p>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                </>
              )}

              <DialogFooter>
                <Button variant="outline" onClick={closeDetail}>
                  {tCommon("actions.close")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
