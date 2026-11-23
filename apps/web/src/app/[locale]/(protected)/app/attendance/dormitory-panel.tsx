"use client";

import { useCallback, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Ban,
  CalendarPlus,
  Home,
  PencilLine,
  SlidersHorizontal,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { dormitoryApi } from "@/lib/dormitory-attendance-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  DormitoryAbsence,
  DormitoryAssignment,
  DormitoryStudentDetail,
  DormitoryStudentList,
  DormitoryStudentRow,
} from "@/types/dormitory-attendance";

const PAGE_SIZE = 25;
const MIN_CORRECTION_REASON_LENGTH = 10;
const MIN_CANCELLATION_REASON_LENGTH = 10;

type FormMode = "record" | "correct" | "cancel";

interface FormState {
  mode: FormMode;
  date: string;
  points: string;
  reason: string;
  absenceId?: string;
}

/**
 * Dormitory attendance is a list of absences against a housing stay, not a
 * percentage. Nothing here derives a figure: the server decides which stay an
 * absence belongs to and whether the resident was eligible that day, and the
 * page renders what it returns.
 *
 * `mode` is explicit rather than inferred from permissions: the student surface
 * is read-only by construction, so a future permission change cannot silently
 * turn the self-view into an editing surface.
 */
export function DormitoryAttendancePanel({ mode }: { mode: "staff" | "self" }) {
  return mode === "self" ? <SelfDormitoryView /> : <StaffDormitoryView />;
}

// ── Shared presentation helpers ──

function useFormatting() {
  const format = useFormatter();

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

  return { formatDay, formatStamp };
}

function roomLabel(assignment: {
  building_name: string | null;
  room_number: string | null;
  bed_label: string | null;
  bed_number: number | null;
}): string {
  const bed =
    assignment.bed_label ??
    (assignment.bed_number ? `#${assignment.bed_number}` : null);
  return [assignment.building_name, assignment.room_number, bed]
    .filter(Boolean)
    .join(" · ");
}

// ── Student self-view ──

function SelfDormitoryView() {
  const t = useTranslations("dormitoryAttendance");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const { formatDay, formatStamp } = useFormatting();
  const { hasPermission } = useAuth();
  const allowed = hasPermission("attendance.view_dormitory");

  const fetchMine = useCallback(
    () => (allowed ? dormitoryApi.me() : Promise.resolve(null)),
    [allowed],
  );
  const mine = useApi<DormitoryStudentDetail | null>(
    fetchMine,
    [allowed],
    "my dormitory attendance",
  );

  if (!allowed) {
    return <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />;
  }
  if (mine.error) {
    return (
      <EmptyState
        title={tCommon("states.error")}
        message={localizeError(mine.error).message}
      />
    );
  }
  if (mine.loading) {
    return <p className="text-sm text-muted-foreground">{tCommon("states.loading")}</p>;
  }
  if (!mine.data || !mine.data.has_assignment) {
    return <EmptyState title={t("noAssignmentTitle")} message={t("myEmpty")} />;
  }

  const record = mine.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatBlock label={t("myPoints")} value={t("pointsValue", { value: record.points_total })} />
        <StatBlock label={t("myAbsences")} value={String(record.absence_count)} />
        <StatBlock
          label={t("myRoom")}
          value={
            record.current_assignment
              ? roomLabel(record.current_assignment)
              : t("noRoom")
          }
        />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t("assignmentTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <AssignmentList assignments={record.assignments} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{t("historyTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <AbsenceHistory
            absences={record.absences}
            formatDay={formatDay}
            formatStamp={formatStamp}
          />
        </CardContent>
      </Card>
    </div>
  );
}

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border/70 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function AssignmentList({ assignments }: { assignments: DormitoryAssignment[] }) {
  const t = useTranslations("dormitoryAttendance");
  const { formatDay } = useFormatting();

  if (assignments.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("noAssignment")}</p>;
  }

  return (
    <ul className="space-y-2">
      {assignments.map((assignment) => (
        <li
          key={assignment.id}
          className="rounded-lg border border-border/70 p-3 text-sm"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Home className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="font-medium">{roomLabel(assignment)}</span>
            <StatusBadge tone={assignment.is_current ? "success" : "muted"}>
              {assignment.is_current ? t("assignmentCurrent") : t("assignmentEnded")}
            </StatusBadge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {assignment.end_date
              ? t("assignmentEffective", {
                  start: formatDay(assignment.start_date),
                  end: formatDay(assignment.end_date),
                })
              : t("assignmentOpenEnded", { start: formatDay(assignment.start_date) })}
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("columnsAbsences")}: {assignment.absence_count} ·{" "}
            {t("columnsPoints")}:{" "}
            {t("pointsValue", { value: assignment.points_total })}
          </p>
        </li>
      ))}
    </ul>
  );
}

function AbsenceHistory({
  absences,
  formatDay,
  formatStamp,
  onCorrect,
  onCancel,
  assignmentLabel,
}: {
  absences: DormitoryAbsence[];
  formatDay: (value: string | null) => string;
  formatStamp: (value: string) => string;
  onCorrect?: (absence: DormitoryAbsence) => void;
  onCancel?: (absence: DormitoryAbsence) => void;
  assignmentLabel?: (assignmentId: string) => string;
}) {
  const t = useTranslations("dormitoryAttendance");

  if (absences.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("historyEmpty")}</p>;
  }

  return (
    <ul className="space-y-2">
      {absences.map((absence) => (
        <li
          key={absence.id}
          className="rounded-lg border border-border/70 p-3 text-sm"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{formatDay(absence.absence_date)}</span>
            <StatusBadge tone="warning">
              {t("pointsValue", { value: absence.points })}
            </StatusBadge>
            {absence.cancelled_at && (
              <StatusBadge tone="danger">{t("historyCancelled")}</StatusBadge>
            )}
            {!absence.cancelled_at && absence.superseded_at && (
              <StatusBadge tone="muted">{t("historySuperseded")}</StatusBadge>
            )}
            {absence.is_active && onCorrect && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onCorrect(absence)}
              >
                <PencilLine className="h-3.5 w-3.5" aria-hidden="true" />
                {t("correctTitle")}
              </Button>
            )}
            {absence.is_active && onCancel && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onCancel(absence)}
              >
                <Ban className="h-3.5 w-3.5" aria-hidden="true" />
                {t("cancelAction")}
              </Button>
            )}
          </div>
          {assignmentLabel && (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {assignmentLabel(absence.housing_assignment_id)}
            </p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">{absence.reason}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("historyRecordedBy", {
              name: absence.recorded_by_name ?? "—",
              date: formatStamp(absence.recorded_at),
            })}
          </p>
          {absence.cancelled_at && (
            <p className="mt-1 rounded-md bg-destructive/5 p-2 text-xs text-muted-foreground">
              {t("historyCancellationReason")}:{" "}
              {absence.cancellation_reason}
              <br />
              {t("historyCancelledBy", {
                name: absence.cancelled_by_name ?? "—",
                date: formatStamp(absence.cancelled_at),
              })}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}

// ── Staff view ──

function StaffDormitoryView() {
  const t = useTranslations("dormitoryAttendance");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const { formatDay, formatStamp } = useFormatting();
  const { hasPermission } = useAuth();

  const canView = hasPermission("attendance.view_dormitory");
  const canRecord = hasPermission("attendance.record_dormitory");

  const [search, setSearch] = useState("");
  const [residency, setResidency] = useState("all");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchResidents = useCallback(() => {
    if (!canView) return Promise.resolve(null);
    return dormitoryApi.listStudents({
      search: search.trim() || undefined,
      residency: residency as "all" | "current" | "former",
      page,
      pageSize: PAGE_SIZE,
    });
  }, [canView, search, residency, page]);
  const residents = useApi<DormitoryStudentList | null>(
    fetchResidents,
    [canView, search, residency, page],
    "dormitory residents",
  );

  const fetchDetail = useCallback(
    () => (selectedId ? dormitoryApi.detail(selectedId) : Promise.resolve(null)),
    [selectedId],
  );
  const detail = useApi<DormitoryStudentDetail | null>(
    fetchDetail,
    [selectedId],
    "dormitory detail",
  );

  const localizedError = localizeError(residents.error);
  const detailError = detail.error ? localizeError(detail.error) : null;
  const record = detail.data;

  const residencyOptions = useMemo(
    () => [
      { value: "all", label: t("residencyAll") },
      { value: "current", label: t("residencyCurrent") },
      { value: "former", label: t("residencyFormer") },
    ],
    [t],
  );

  const today = new Date().toISOString().slice(0, 10);

  const residencyBadge = (row: {
    is_current_resident: boolean;
    ineligible_reason: string | null;
  }) =>
    row.is_current_resident ? (
      <StatusBadge tone="success">{t("currentResident")}</StatusBadge>
    ) : row.ineligible_reason === "BETWEEN_ASSIGNMENTS" ? (
      <StatusBadge tone="warning">{t("betweenAssignments")}</StatusBadge>
    ) : (
      <StatusBadge tone="muted">{t("formerResident")}</StatusBadge>
    );

  const openDetail = (row: DormitoryStudentRow) => {
    setSelectedId(row.student_id);
    setForm(null);
  };

  const closeDetail = () => {
    setSelectedId(null);
    setForm(null);
  };

  const startRecord = () => {
    setForm({ mode: "record", date: today, points: "", reason: "" });
  };

  const startCorrect = (absence: DormitoryAbsence) => {
    setForm({
      mode: "correct",
      date: absence.absence_date,
      points: String(absence.points),
      reason: "",
      absenceId: absence.id,
    });
  };

  const startCancel = (absence: DormitoryAbsence) => {
    setForm({
      mode: "cancel",
      date: absence.absence_date,
      points: String(absence.points),
      reason: "",
      absenceId: absence.id,
    });
  };

  const submit = async () => {
    if (!form || !record) return;

    // Cancellation is its own act: the record keeps its date and points, and
    // only the reason and the actor are added.
    if (form.mode === "cancel") {
      if (form.reason.trim().length < MIN_CANCELLATION_REASON_LENGTH) {
        toast.error(t("cancelReasonHint"));
        return;
      }
      setSaving(true);
      try {
        if (form.absenceId) {
          await dormitoryApi.cancel(record.student_id, form.absenceId, {
            reason: form.reason.trim(),
          });
          toast.success(t("cancelSuccess"));
        }
        setForm(null);
        detail.refetch();
        residents.refetch();
      } catch (error) {
        toast.error(
          localizeError(normalizeApiError(error, "dormitory cancel")).message,
        );
      } finally {
        setSaving(false);
      }
      return;
    }

    if (!form.date) {
      toast.error(t("recordDate"));
      return;
    }
    const points = Number(form.points);
    if (form.points.trim() === "" || !Number.isFinite(points) || points < 0) {
      toast.error(t("recordPoints"));
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

    setSaving(true);
    try {
      if (form.mode === "record") {
        await dormitoryApi.record(record.student_id, {
          absence_date: form.date,
          points,
          reason,
        });
        toast.success(t("recordSuccess"));
      } else if (form.absenceId) {
        await dormitoryApi.correct(record.student_id, form.absenceId, {
          absence_date: form.date,
          points,
          reason,
        });
        toast.success(t("correctSuccess"));
      }
      setForm(null);
      detail.refetch();
      residents.refetch();
    } catch (error) {
      toast.error(
        localizeError(normalizeApiError(error, "dormitory submit")).message,
      );
    } finally {
      setSaving(false);
    }
  };

  const columns: Column<DormitoryStudentRow>[] = [
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
      key: "room",
      header: t("columnsRoom"),
      hideOnMobile: true,
      cell: (item) => (
        <span className="text-sm">
          {roomLabel({
            building_name: item.building_name,
            room_number: item.room_number,
            bed_label: item.bed_label,
            bed_number: item.bed_number,
          }) || "—"}
        </span>
      ),
    },
    {
      key: "period",
      header: t("columnsPeriod"),
      hideOnMobile: true,
      cell: (item) => (
        <span className="text-sm">
          {item.assignment_end_date
            ? t("assignmentEffective", {
                start: formatDay(item.assignment_start_date),
                end: formatDay(item.assignment_end_date),
              })
            : t("assignmentOpenEnded", {
                start: formatDay(item.assignment_start_date),
              })}
        </span>
      ),
    },
    {
      key: "residency",
      header: t("columnsResidency"),
      cell: (item) => residencyBadge(item),
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
      key: "points",
      header: t("columnsPoints"),
      className: "text-end",
      cell: (item) => (
        <span className="tabular-nums text-sm font-semibold">
          {t("pointsValue", { value: item.points_total })}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      className: "text-end",
      cell: (item) => (
        <Button variant="outline" size="sm" onClick={() => openDetail(item)}>
          {tCommon("actions.view")}
        </Button>
      ),
    },
  ];

  if (!canView) {
    return <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />;
  }

  const assignmentLabel = (assignmentId: string) => {
    const assignment = record?.assignments.find((a) => a.id === assignmentId);
    return assignment ? roomLabel(assignment) : "—";
  };

  return (
    <>
      <Card className="mb-4">
        <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
          <SlidersHorizontal
            className="h-4 w-4 text-muted-foreground"
            aria-hidden="true"
          />
          <CardTitle className="text-sm">{t("filtersTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setPage(1);
            }}
            placeholder={t("searchPlaceholder")}
            className="sm:col-span-1"
          />
          <FilterSelect
            label={t("residencyLabel")}
            value={residency}
            showLabel
            options={residencyOptions}
            onChange={(value) => {
              setResidency(value);
              setPage(1);
            }}
          />
        </CardContent>
      </Card>

      <DataTable
        columns={columns}
        rows={residents.data?.items ?? []}
        rowKey={(item) => item.student_id}
        loading={residents.loading}
        error={residents.error ? localizedError.message : null}
        onRetry={residents.refetch}
        emptyTitle={t("emptyTitle")}
        emptyMessage={t("emptyMessage")}
        mobileCard={(item) => (
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">{item.student_name}</p>
              {residencyBadge(item)}
            </div>
            <p className="font-mono text-xs text-muted-foreground" dir="ltr">
              {item.student_number}
            </p>
            <p className="text-xs text-muted-foreground">
              {roomLabel({
                building_name: item.building_name,
                room_number: item.room_number,
                bed_label: item.bed_label,
                bed_number: item.bed_number,
              }) || "—"}
            </p>
            <div className="flex flex-wrap gap-2 pt-1 text-xs text-muted-foreground">
              <span>
                {t("columnsAbsences")}: {item.absence_count}
              </span>
              <span>·</span>
              <span>
                {t("columnsPoints")}:{" "}
                {t("pointsValue", { value: item.points_total })}
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

      {residents.data && (
        <Pagination
          page={residents.data.page}
          pageSize={residents.data.page_size}
          total={residents.data.total}
          totalPages={Math.max(
            1,
            Math.ceil(residents.data.total / residents.data.page_size),
          )}
          onPageChange={setPage}
        />
      )}

      <Dialog open={!!selectedId} onOpenChange={(open) => !open && closeDetail()}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          {selectedId && (
            <>
              <DialogHeader>
                <DialogTitle>{record?.student_name ?? t("detailTitle")}</DialogTitle>
                <DialogDescription>
                  {record
                    ? `${record.student_number} · ${t("detailTitle")}`
                    : tCommon("states.loading")}
                </DialogDescription>
              </DialogHeader>

              {detailError ? (
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
              ) : !record ? (
                <p className="text-sm text-muted-foreground">
                  {tCommon("states.loading")}
                </p>
              ) : (
                <>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <StatBlock
                      label={t("statPoints")}
                      value={t("pointsValue", { value: record.points_total })}
                    />
                    <StatBlock
                      label={t("statAbsences")}
                      value={String(record.absence_count)}
                    />
                    <StatBlock
                      label={t("statRoom")}
                      value={
                        record.current_assignment
                          ? roomLabel(record.current_assignment)
                          : t("noRoom")
                      }
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {residencyBadge(record)}
                    {record.ineligible_reason && (
                      <span>{t(`reasons.${record.ineligible_reason}`)}</span>
                    )}
                  </div>

                  {!record.eligible_today && canRecord && (
                    <p className="rounded-lg border border-border/70 bg-muted/40 p-3 text-xs text-muted-foreground">
                      {t("notEligibleTitle")}:{" "}
                      {record.ineligible_reason
                        ? t(`reasons.${record.ineligible_reason}`)
                        : t("noAssignment")}
                    </p>
                  )}

                  {canRecord && record.eligible_today && !form && (
                    <Button onClick={startRecord}>
                      <CalendarPlus className="me-1 h-4 w-4" aria-hidden="true" />
                      {t("recordTitle")}
                    </Button>
                  )}

                  {form && form.mode === "cancel" && (
                    <div className="space-y-3 rounded-lg border border-border/80 p-3">
                      <p className="text-sm font-semibold">{t("cancelTitle")}</p>
                      <p className="text-xs text-muted-foreground">
                        {t("cancelDescription")}
                      </p>
                      <div>
                        <label
                          htmlFor="dormitory-cancel-reason"
                          className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                        >
                          {t("cancelReason")}
                        </label>
                        <Textarea
                          id="dormitory-cancel-reason"
                          value={form.reason}
                          onChange={(event) =>
                            setForm({ ...form, reason: event.target.value })
                          }
                          className="mt-1"
                          rows={3}
                        />
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t("cancelReasonHint")}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button onClick={submit} disabled={saving} variant="destructive">
                          {saving ? t("cancelling") : t("cancelSubmit")}
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

                  {form && form.mode !== "cancel" && (
                    <div className="space-y-3 rounded-lg border border-border/80 p-3">
                      <p className="text-sm font-semibold">
                        {form.mode === "record" ? t("recordTitle") : t("correctTitle")}
                      </p>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <div>
                          <label
                            htmlFor="dormitory-date"
                            className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                          >
                            {form.mode === "record" ? t("recordDate") : t("correctDate")}
                          </label>
                          <Input
                            id="dormitory-date"
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
                        <div>
                          <label
                            htmlFor="dormitory-points"
                            className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                          >
                            {form.mode === "record"
                              ? t("recordPoints")
                              : t("correctPoints")}
                          </label>
                          <Input
                            id="dormitory-points"
                            type="number"
                            dir="ltr"
                            min={0}
                            step="0.5"
                            value={form.points}
                            onChange={(event) =>
                              setForm({ ...form, points: event.target.value })
                            }
                            className="mt-1"
                          />
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t("recordPointsHint")}
                          </p>
                        </div>
                      </div>
                      <div>
                        <label
                          htmlFor="dormitory-reason"
                          className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground"
                        >
                          {form.mode === "record"
                            ? t("recordReason")
                            : t("correctReason")}
                        </label>
                        <Textarea
                          id="dormitory-reason"
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
                            : t("correctReasonHint")}
                        </p>
                      </div>
                      <div className="flex gap-2">
                        <Button onClick={submit} disabled={saving}>
                          {saving
                            ? form.mode === "record"
                              ? t("recording")
                              : t("correcting")
                            : form.mode === "record"
                              ? t("recordSubmit")
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
                    <p className="mb-2 text-sm font-semibold">
                      {t("assignmentTitle")}
                    </p>
                    <AssignmentList assignments={record.assignments} />
                  </div>

                  <div>
                    <p className="mb-2 text-sm font-semibold">{t("historyTitle")}</p>
                    <AbsenceHistory
                      absences={record.absences}
                      formatDay={formatDay}
                      formatStamp={formatStamp}
                      onCorrect={canRecord && !form ? startCorrect : undefined}
                      onCancel={canRecord && !form ? startCancel : undefined}
                      assignmentLabel={assignmentLabel}
                    />
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
    </>
  );
}
