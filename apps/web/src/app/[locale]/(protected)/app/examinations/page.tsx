"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  CalendarClock,
  ClipboardCheck,
  ClipboardList,
  Eye,
  GraduationCap,
  MapPin,
  Plus,
  Send,
  Users,
  XCircle,
} from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { examinationApi } from "@/lib/examination-api";
import {
  listClassSections,
  listCourses,
  listPeriods,
  listProgramOfferings,
} from "@/lib/academic-api";
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
import { StatCard, StatGrid } from "@/components/ui/stat-card";
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
  AcademicPeriod,
  ClassSection,
  Course,
  PaginatedList,
  ProgramOffering,
} from "@/types/academic";
import type {
  Examination,
  ExaminationDetail,
  ExaminationDashboard,
  ExaminationList,
  ExaminationType,
  StudentExamination,
  StudentExaminationList,
} from "@/types/examination";

const PAGE_SIZE = 25;
const MIN_REASON_LENGTH = 10;

const EXAM_TYPES: ExaminationType[] = [
  "MIDTERM",
  "FINAL",
  "QUIZ",
  "ASSIGNMENT",
  "PROJECT",
  "OTHER",
];

/**
 * Examinations are an institutional event: one schedule, one room, one
 * publication decision, and however many teaching sections sit it. Nothing on
 * this page computes eligibility or decides whether a result is visible — the
 * server owns both, and the student view simply receives no score until the
 * institution publishes.
 */
export default function ExaminationsPage() {
  const { hasRole, hasPermission } = useAuth();

  if (hasRole("STUDENT") && !hasPermission("exams.manage")) {
    return <StudentExaminationsView />;
  }
  return <StaffExaminationsView />;
}

// ── shared formatting ──

function useExamFormatting() {
  const format = useFormatter();

  const formatDay = (value: string) =>
    format.dateTime(new Date(`${value}T00:00:00Z`), {
      dateStyle: "medium",
      timeZone: "UTC",
    });

  const formatTime = (value: string) =>
    format.dateTime(new Date(`1970-01-01T${value}Z`), {
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
    });

  const formatStamp = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });

  return { formatDay, formatTime, formatStamp };
}

// ── Student view ──

function StudentExaminationsView() {
  const t = useTranslations("examinations");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const { formatDay, formatTime } = useExamFormatting();
  const { hasPermission } = useAuth();
  const allowed = hasPermission("exams.view");

  const fetchMine = useCallback(
    () => (allowed ? examinationApi.mine() : Promise.resolve(null)),
    [allowed],
  );
  const mine = useApi<StudentExaminationList | null>(
    fetchMine,
    [allowed],
    "my examinations",
  );

  if (!allowed) {
    return (
      <AppShell>
        <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />
      </AppShell>
    );
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
    return (
      <p className="text-sm text-muted-foreground">{tCommon("states.loading")}</p>
    );
  }

  const items = mine.data?.items ?? [];
  const upcoming = items.filter((item) => !item.is_past);
  const past = items.filter((item) => item.is_past);
  const withResults = items.filter((item) => item.result !== null);

  return (
    <AppShell>
      <PageHeader
        title={t("myTitle")}
        description={t("mySubtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("myTitle") },
        ]}
      />

      <div className="space-y-4">
        <StatGrid className="xl:grid-cols-3">
        <StatCard
          label={t("myUpcoming")}
          value={mine.data?.upcoming_count ?? 0}
          icon={<CalendarClock className="h-4 w-4" />}
          tone="info"
        />
        <StatCard
          label={t("myPast")}
          value={mine.data?.past_count ?? 0}
          icon={<ClipboardList className="h-4 w-4" />}
        />
        <StatCard
          label={t("myResults")}
          value={withResults.length}
          icon={<GraduationCap className="h-4 w-4" />}
          tone="success"
        />
      </StatGrid>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t("myUpcoming")}</CardTitle>
          </CardHeader>
          <CardContent>
            {upcoming.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("noUpcoming")}</p>
            ) : (
              <ul className="space-y-2">
                {upcoming.map((item) => (
                  <StudentExamRow
                    key={item.id}
                    item={item}
                    formatDay={formatDay}
                    formatTime={formatTime}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t("myPast")}</CardTitle>
          </CardHeader>
          <CardContent>
            {past.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("noPast")}</p>
            ) : (
              <ul className="space-y-2">
                {past.map((item) => (
                  <StudentExamRow
                    key={item.id}
                    item={item}
                    formatDay={formatDay}
                    formatTime={formatTime}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}

function StudentExamRow({
  item,
  formatDay,
  formatTime,
}: {
  item: StudentExamination;
  formatDay: (value: string) => string;
  formatTime: (value: string) => string;
}) {
  const t = useTranslations("examinations");

  return (
    <li className="rounded-lg border border-border/70 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{item.title}</span>
        <StatusBadge tone={item.status === "CANCELLED" ? "danger" : item.is_past ? "muted" : "info"}>
          {item.status === "CANCELLED"
            ? t("cancelled")
            : item.is_past
              ? t("past")
              : t("upcoming")}
        </StatusBadge>
        <StatusBadge>{t(`types.${item.examination_type}`)}</StatusBadge>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          {formatDay(item.exam_date)} · {formatTime(item.start_time)} –{" "}
          {formatTime(item.end_time)}
        </span>
        <span className="inline-flex items-center gap-1">
          <MapPin className="h-3 w-3" aria-hidden="true" />
          {item.location ?? t("noLocation")}
        </span>
        {item.course_code && <span dir="ltr">{item.course_code}</span>}
      </div>

      {item.section_labels.length > 0 && (
        <p className="mt-1 text-xs text-muted-foreground">
          {item.section_labels.join(" · ")}
        </p>
      )}

      {item.instructions && (
        <p className="mt-2 whitespace-pre-line rounded-md bg-muted/40 p-2 text-xs text-muted-foreground">
          {item.instructions}
        </p>
      )}

      <div className="mt-2 text-xs">
        {item.result ? (
          <span className="font-medium">
            {t("scoreValue", {
              score: item.result.score,
            })}
            {item.result.letter_grade
              ? ` · ${item.result.letter_grade}`
              : ""}
          </span>
        ) : (
          <span className="text-muted-foreground">
            {item.results_published ? t("noResultRecorded") : t("resultsPending")}
          </span>
        )}
      </div>
    </li>
  );
}

// ── Staff view ──

interface FormState {
  title: string;
  examinationType: ExaminationType;
  courseId: string;
  periodId: string;
  offeringId: string;
  sectionIds: string[];
  examDate: string;
  startTime: string;
  endTime: string;
  location: string;
  instructions: string;
  maxScore: string;
  examinationId?: string;
}

interface ResultDraft {
  studentId: string;
  score: string;
  letter: string;
  note: string;
  resultId?: string;
  reason: string;
}

function StaffExaminationsView() {
  const t = useTranslations("examinations");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const { formatDay, formatTime, formatStamp } = useExamFormatting();
  const { hasPermission } = useAuth();

  const canView = hasPermission("exams.view");
  const canManage = hasPermission("exams.manage");
  const canRecord = hasPermission("exams.record_results");
  const canPublish = hasPermission("exams.publish");

  const [search, setSearch] = useState("");
  const [periodFilter, setPeriodFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [publicationFilter, setPublicationFilter] = useState("");
  const [page, setPage] = useState(1);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState<ResultDraft | null>(null);
  const [cancelTarget, setCancelTarget] = useState<Examination | null>(null);
  const [cancelReason, setCancelReason] = useState("");

  const fetchDashboard = useCallback(
    () => (canView ? examinationApi.dashboard() : Promise.resolve(null)),
    [canView],
  );
  const dashboard = useApi<ExaminationDashboard | null>(
    fetchDashboard,
    [canView],
    "examination dashboard",
  );

  const fetchList = useCallback(() => {
    if (!canView) return Promise.resolve(null);
    return examinationApi.list({
      search: search.trim() || undefined,
      periodId: periodFilter || undefined,
      status: (statusFilter || undefined) as "SCHEDULED" | "CANCELLED" | undefined,
      published: (publicationFilter || undefined) as
        | "published"
        | "unpublished"
        | undefined,
      page,
      pageSize: PAGE_SIZE,
    });
  }, [canView, search, periodFilter, statusFilter, publicationFilter, page]);
  const listing = useApi<ExaminationList | null>(
    fetchList,
    [canView, search, periodFilter, statusFilter, publicationFilter, page],
    "examinations",
  );

  const fetchDetail = useCallback(
    () => (selectedId ? examinationApi.detail(selectedId) : Promise.resolve(null)),
    [selectedId],
  );
  const detail = useApi<ExaminationDetail | null>(
    fetchDetail,
    [selectedId],
    "examination detail",
  );

  const fetchPeriods = useCallback(
    () => (canView ? listPeriods(1, 50) : Promise.resolve(null)),
    [canView],
  );
  const periods = useApi<PaginatedList<AcademicPeriod> | null>(
    fetchPeriods,
    [canView],
    "examination periods",
  );

  const fetchCourses = useCallback(
    () => (canManage ? listCourses(1, 100) : Promise.resolve(null)),
    [canManage],
  );
  const courses = useApi<PaginatedList<Course> | null>(
    fetchCourses,
    [canManage],
    "examination courses",
  );

  // Offerings of the chosen intake. The server refuses sections that do not
  // serve the chosen offering, so the picker only offers the real cohorts of
  // this intake rather than every programme the school has ever run.
  const fetchOfferings = useCallback(async () => {
    if (!canManage || !form?.periodId) return null;
    return listProgramOfferings(form.periodId);
  }, [canManage, form?.periodId]);
  const offerings = useApi<PaginatedList<ProgramOffering> | null>(
    fetchOfferings,
    [canManage, form?.periodId],
    "examination offerings",
  );

  // Sections are scoped by the chosen course and intake: an examination covers
  // one subject inside one intake, so offering anything else would only produce
  // a server refusal. Once an offering is chosen, only the sections that serve
  // it are shown, which is the same rule the server enforces.
  const fetchSections = useCallback(async () => {
    if (!form?.courseId || !form.periodId) return null;
    return listClassSections(
      1,
      100,
      undefined,
      form.periodId,
      form.offeringId || undefined,
      form.courseId,
    );
  }, [form?.courseId, form?.periodId, form?.offeringId]);
  const sections = useApi<PaginatedList<ClassSection> | null>(
    fetchSections,
    [form?.courseId, form?.periodId, form?.offeringId],
    "examination sections",
  );

  const localizedError = localizeError(listing.error);

  const periodOptions = useMemo(
    () => [
      { value: "", label: t("allPeriods") },
      ...(periods.data?.items ?? []).map((period) => ({
        value: period.id,
        label: period.name,
      })),
    ],
    [periods.data, t],
  );

  const statusOptions = useMemo(
    () => [
      { value: "", label: t("allStatuses") },
      { value: "SCHEDULED", label: t("scheduled") },
      { value: "CANCELLED", label: t("cancelled") },
    ],
    [t],
  );

  const publicationOptions = useMemo(
    () => [
      { value: "", label: t("allPublication") },
      { value: "published", label: t("published") },
      { value: "unpublished", label: t("unpublished") },
    ],
    [t],
  );

  const today = new Date().toISOString().slice(0, 10);

  const openCreate = () => {
    setForm({
      title: "",
      examinationType: "FINAL",
      courseId: "",
      // Default to the intake already being filtered on, otherwise the first
      // real intake, so the selectors show the state the form actually holds.
      periodId: periodFilter || periods.data?.items[0]?.id || "",
      offeringId: "",
      sectionIds: [],
      examDate: today,
      startTime: "09:00",
      endTime: "11:00",
      location: "",
      instructions: "",
      maxScore: "",
    });
  };

  const openEdit = (item: Examination) => {
    setForm({
      title: item.title,
      examinationType: item.examination_type,
      courseId: item.course_id,
      periodId: item.academic_period_id,
      offeringId: item.program_offering_id ?? "",
      sectionIds: item.sections.map((section) => section.class_section_id),
      examDate: item.exam_date,
      startTime: item.start_time.slice(0, 5),
      endTime: item.end_time.slice(0, 5),
      location: item.location ?? "",
      instructions: item.instructions ?? "",
      maxScore: item.max_score === null ? "" : String(item.max_score),
      examinationId: item.id,
    });
  };

  const submitForm = async () => {
    if (!form) return;
    if (!form.title.trim() || !form.courseId || !form.periodId) {
      toast.error(t("formRequired"));
      return;
    }
    if (form.sectionIds.length === 0) {
      toast.error(t("sectionsRequired"));
      return;
    }

    const payload = {
      title: form.title.trim(),
      examination_type: form.examinationType,
      course_id: form.courseId,
      academic_period_id: form.periodId,
      program_offering_id: form.offeringId || null,
      exam_date: form.examDate,
      start_time: form.startTime,
      end_time: form.endTime,
      location: form.location.trim() || null,
      instructions: form.instructions.trim() || null,
      max_score: form.maxScore.trim() === "" ? null : Number(form.maxScore),
      section_ids: form.sectionIds,
    };

    setSaving(true);
    try {
      if (form.examinationId) {
        await examinationApi.update(form.examinationId, payload);
        toast.success(t("updateSuccess"));
      } else {
        await examinationApi.create(payload);
        toast.success(t("createSuccess"));
      }
      setForm(null);
      listing.refetch();
      dashboard.refetch();
      if (selectedId) detail.refetch();
    } catch (error) {
      toast.error(localizeError(normalizeApiError(error, "examination form")).message);
    } finally {
      setSaving(false);
    }
  };

  const submitResult = async () => {
    if (!draft || !selectedId) return;
    const score = Number(draft.score);
    if (draft.score.trim() === "" || !Number.isFinite(score) || score < 0) {
      toast.error(t("recordScore"));
      return;
    }
    if (draft.resultId && draft.reason.trim().length < MIN_REASON_LENGTH) {
      toast.error(t("correctionReasonHint"));
      return;
    }

    setSaving(true);
    try {
      if (draft.resultId) {
        await examinationApi.correctResult(selectedId, draft.resultId, {
          score,
          letter_grade: draft.letter.trim() || null,
          note: draft.note.trim() || null,
          reason: draft.reason.trim(),
        });
        toast.success(t("correctSuccess"));
      } else {
        await examinationApi.recordResult(selectedId, draft.studentId, {
          score,
          letter_grade: draft.letter.trim() || null,
          note: draft.note.trim() || null,
        });
        toast.success(t("recordSuccess"));
      }
      setDraft(null);
      detail.refetch();
      listing.refetch();
      dashboard.refetch();
    } catch (error) {
      toast.error(localizeError(normalizeApiError(error, "examination result")).message);
    } finally {
      setSaving(false);
    }
  };

  const publish = async (item: Examination) => {
    setSaving(true);
    try {
      await examinationApi.publish(item.id);
      toast.success(t("publishSuccess"));
      detail.refetch();
      listing.refetch();
      dashboard.refetch();
    } catch (error) {
      toast.error(localizeError(normalizeApiError(error, "examination publish")).message);
    } finally {
      setSaving(false);
    }
  };

  const submitCancel = async () => {
    if (!cancelTarget) return;
    if (cancelReason.trim().length < MIN_REASON_LENGTH) {
      toast.error(t("cancelReasonHint"));
      return;
    }
    setSaving(true);
    try {
      await examinationApi.cancel(cancelTarget.id, cancelReason.trim());
      toast.success(t("cancelSuccess"));
      setCancelTarget(null);
      setCancelReason("");
      detail.refetch();
      listing.refetch();
      dashboard.refetch();
    } catch (error) {
      toast.error(localizeError(normalizeApiError(error, "examination cancel")).message);
    } finally {
      setSaving(false);
    }
  };

  const statusBadge = (item: Examination) =>
    item.status === "CANCELLED" ? (
      <StatusBadge tone="danger">{t("cancelled")}</StatusBadge>
    ) : item.published_at ? (
      <StatusBadge tone="success">{t("published")}</StatusBadge>
    ) : (
      <StatusBadge tone="muted">{t("unpublished")}</StatusBadge>
    );

  const columns: Column<Examination>[] = [
    {
      key: "title",
      header: t("columnsTitle"),
      cell: (item) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{item.title}</p>
          <p className="truncate text-xs text-muted-foreground">
            {t(`types.${item.examination_type}`)}
            {item.course_code ? ` · ${item.course_code}` : ""}
            {item.program_offering_name ? ` · ${item.program_offering_name}` : ""}
          </p>
        </div>
      ),
    },
    {
      key: "date",
      header: t("columnsDate"),
      hideOnMobile: true,
      cell: (item) => (
        <span className="text-sm">
          {formatDay(item.exam_date)}
          <span className="block text-xs text-muted-foreground">
            {formatTime(item.start_time)} – {formatTime(item.end_time)}
          </span>
        </span>
      ),
    },
    {
      key: "sections",
      header: t("columnsSections"),
      className: "text-end",
      cell: (item) => (
        <span className="tabular-nums text-sm">{item.section_count}</span>
      ),
    },
    {
      key: "students",
      header: t("columnsEligible"),
      className: "text-end",
      hideOnMobile: true,
      cell: (item) => (
        <span className="tabular-nums text-sm">{item.eligible_count}</span>
      ),
    },
    {
      key: "results",
      header: t("columnsResults"),
      className: "text-end",
      cell: (item) => (
        <span className="tabular-nums text-sm">{item.result_count}</span>
      ),
    },
    {
      key: "status",
      header: t("columnsStatus"),
      cell: (item) => statusBadge(item),
    },
    {
      key: "actions",
      header: "",
      className: "text-end",
      cell: (item) => (
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setSelectedId(item.id);
            setDraft(null);
          }}
        >
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          {tCommon("actions.view")}
        </Button>
      ),
    },
  ];

  if (!canView) {
    return (
      <AppShell>
        <EmptyState title={t("deniedTitle")} message={t("deniedMessage")} />
      </AppShell>
    );
  }

  const counts = dashboard.data?.counts;

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
        actions={
          canManage ? (
            <Button size="sm" onClick={openCreate}>
              <Plus className="me-1 h-4 w-4" aria-hidden="true" />
              {t("createAction")}
            </Button>
          ) : undefined
        }
      />

      <StatGrid>
        <StatCard
          label={t("statTotal")}
          value={counts?.total ?? 0}
          icon={<ClipboardList className="h-4 w-4" />}
        />
        <StatCard
          label={t("statUpcoming")}
          value={counts?.upcoming ?? 0}
          icon={<CalendarClock className="h-4 w-4" />}
          tone="info"
        />
        <StatCard
          label={t("statCompleted")}
          value={counts?.completed ?? 0}
          icon={<ClipboardCheck className="h-4 w-4" />}
        />
        <StatCard
          label={t("statResults")}
          value={counts?.results_recorded ?? 0}
          icon={<Users className="h-4 w-4" />}
        />
        <StatCard
          label={t("statPublished")}
          value={counts?.published ?? 0}
          icon={<Send className="h-4 w-4" />}
          tone="success"
        />
      </StatGrid>

      <Card className="mb-4">
        <CardHeader className="flex-row items-center gap-2 space-y-0 pb-3">
          <ClipboardList
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
          />
          <FilterSelect
            label={t("periodLabel")}
            value={periodFilter}
            showLabel
            options={periodOptions}
            onChange={(value) => {
              setPeriodFilter(value);
              setPage(1);
            }}
          />
          <FilterSelect
            label={t("statusLabel")}
            value={statusFilter}
            showLabel
            options={statusOptions}
            onChange={(value) => {
              setStatusFilter(value);
              setPage(1);
            }}
          />
          <FilterSelect
            label={t("publicationLabel")}
            value={publicationFilter}
            showLabel
            options={publicationOptions}
            onChange={(value) => {
              setPublicationFilter(value);
              setPage(1);
            }}
          />
        </CardContent>
      </Card>

      <DataTable
        columns={columns}
        rows={listing.data?.items ?? []}
        rowKey={(item) => item.id}
        loading={listing.loading}
        error={listing.error ? localizedError.message : null}
        onRetry={listing.refetch}
        emptyTitle={t("emptyTitle")}
        emptyMessage={t("emptyMessage")}
        mobileCard={(item) => (
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-2">
              <p className="font-medium">{item.title}</p>
              {statusBadge(item)}
            </div>
            <p className="text-xs text-muted-foreground">
              {formatDay(item.exam_date)} · {formatTime(item.start_time)} –{" "}
              {formatTime(item.end_time)}
            </p>
            <p className="text-xs text-muted-foreground">
              {t("columnsSections")}: {item.section_count} ·{" "}
              {t("columnsResults")}: {item.result_count}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={() => {
                setSelectedId(item.id);
                setDraft(null);
              }}
            >
              {tCommon("actions.view")}
            </Button>
          </div>
        )}
      />

      {listing.data && (
        <Pagination
          page={listing.data.page}
          pageSize={listing.data.page_size}
          total={listing.data.total}
          totalPages={Math.max(
            1,
            Math.ceil(listing.data.total / listing.data.page_size),
          )}
          onPageChange={setPage}
        />
      )}

      {/* ── Detail ── */}
      <Dialog
        open={!!selectedId}
        onOpenChange={(open) => {
          if (!open) {
            setSelectedId(null);
            setDraft(null);
          }
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-3xl">
          {selectedId && (
            <>
              <DialogHeader>
                <DialogTitle>
                  {detail.data?.examination.title ?? t("detailTitle")}
                </DialogTitle>
                <DialogDescription>
                  {detail.data
                    ? `${detail.data.examination.academic_period_name ?? ""} · ${
                        detail.data.examination.course_name ?? ""
                      }`
                    : tCommon("states.loading")}
                </DialogDescription>
              </DialogHeader>

              {detail.error ? (
                <div className="rounded-lg border border-destructive/40 p-3">
                  <p className="text-sm">{tCommon("states.error")}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {localizeError(detail.error).message}
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
              ) : !detail.data ? (
                <p className="text-sm text-muted-foreground">
                  {tCommon("states.loading")}
                </p>
              ) : (
                <ExaminationPanel
                  detail={detail.data}
                  canManage={canManage}
                  canRecord={canRecord}
                  canPublish={canPublish}
                  saving={saving}
                  draft={draft}
                  setDraft={setDraft}
                  onSubmitResult={submitResult}
                  onPublish={() => publish(detail.data!.examination)}
                  onEdit={() => openEdit(detail.data!.examination)}
                  onCancel={() => setCancelTarget(detail.data!.examination)}
                  formatDay={formatDay}
                  formatTime={formatTime}
                  formatStamp={formatStamp}
                />
              )}

              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => {
                    setSelectedId(null);
                    setDraft(null);
                  }}
                >
                  {tCommon("actions.close")}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* ── Create / edit ── */}
      <Dialog open={!!form} onOpenChange={(open) => !open && setForm(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>
              {form?.examinationId ? t("editTitle") : t("createTitle")}
            </DialogTitle>
            <DialogDescription>{t("createSubtitle")}</DialogDescription>
          </DialogHeader>

          {form && (
            <div className="space-y-3">
              <div>
                <label htmlFor="exam-title" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {t("fieldTitle")}
                </label>
                <Input
                  id="exam-title"
                  value={form.title}
                  onChange={(event) => setForm({ ...form, title: event.target.value })}
                  className="mt-1"
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="exam-type" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("fieldType")}
                  </label>
                  <FilterSelect
                    label={t("fieldType")}
                    value={form.examinationType}
                    options={EXAM_TYPES.map((value) => ({
                      value,
                      label: t(`types.${value}`),
                    }))}
                    onChange={(value) =>
                      setForm({ ...form, examinationType: value as ExaminationType })
                    }
                    className="mt-1"
                  />
                </div>
                <div>
                  <label htmlFor="exam-period" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("fieldPeriod")}
                  </label>
                  <FilterSelect
                    label={t("fieldPeriod")}
                    value={form.periodId}
                    options={[
                      { value: "", label: t("fieldPeriodChoose") },
                      ...(periods.data?.items ?? []).map((period) => ({
                        value: period.id,
                        label: period.name,
                      })),
                    ]}
                    onChange={(value) =>
                      setForm({
                        ...form,
                        periodId: value,
                        offeringId: "",
                        sectionIds: [],
                      })
                    }
                    className="mt-1"
                  />
                </div>
                <div>
                  <label htmlFor="exam-offering" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("fieldOffering")}
                  </label>
                  <FilterSelect
                    label={t("fieldOffering")}
                    value={form.offeringId}
                    options={[
                      { value: "", label: t("fieldOfferingNone") },
                      ...(offerings.data?.items ?? []).map((offering) => ({
                        value: offering.id,
                        label: offering.name,
                      })),
                    ]}
                    onChange={(value) =>
                      setForm({
                        ...form,
                        offeringId: value,
                        sectionIds: [],
                      })
                    }
                    className="mt-1"
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("fieldOfferingHint")}
                  </p>
                </div>
                <div>
                  <label htmlFor="exam-course" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("fieldCourse")}
                  </label>
                  <FilterSelect
                    label={t("fieldCourse")}
                    value={form.courseId}
                    options={[
                      { value: "", label: t("fieldCourseChoose") },
                      ...(courses.data?.items ?? []).map((course) => ({
                        value: course.id,
                        label: course.code
                          ? `${course.code} · ${course.name}`
                          : course.name,
                      })),
                    ]}
                    onChange={(value) =>
                      setForm({ ...form, courseId: value, sectionIds: [] })
                    }
                    className="mt-1"
                  />
                </div>
                <div>
                  <label htmlFor="exam-max" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("fieldMaxScore")}
                  </label>
                  <Input
                    id="exam-max"
                    type="number"
                    dir="ltr"
                    min={0}
                    value={form.maxScore}
                    onChange={(event) => setForm({ ...form, maxScore: event.target.value })}
                    className="mt-1"
                  />
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("fieldMaxScoreHint")}
                  </p>
                </div>
                <div>
                  <label htmlFor="exam-date" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                    {t("fieldDate")}
                  </label>
                  <Input
                    id="exam-date"
                    type="date"
                    dir="ltr"
                    value={form.examDate}
                    onChange={(event) => setForm({ ...form, examDate: event.target.value })}
                    className="mt-1"
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="exam-start" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      {t("fieldStart")}
                    </label>
                    <Input
                      id="exam-start"
                      type="time"
                      dir="ltr"
                      value={form.startTime}
                      onChange={(event) =>
                        setForm({ ...form, startTime: event.target.value })
                      }
                      className="mt-1"
                    />
                  </div>
                  <div>
                    <label htmlFor="exam-end" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                      {t("fieldEnd")}
                    </label>
                    <Input
                      id="exam-end"
                      type="time"
                      dir="ltr"
                      value={form.endTime}
                      onChange={(event) =>
                        setForm({ ...form, endTime: event.target.value })
                      }
                      className="mt-1"
                    />
                  </div>
                </div>
              </div>

              <div>
                <label htmlFor="exam-location" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {t("fieldLocation")}
                </label>
                <Input
                  id="exam-location"
                  value={form.location}
                  onChange={(event) => setForm({ ...form, location: event.target.value })}
                  className="mt-1"
                />
              </div>

              <div>
                <label htmlFor="exam-instructions" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {t("fieldInstructions")}
                </label>
                <Textarea
                  id="exam-instructions"
                  rows={3}
                  value={form.instructions}
                  onChange={(event) =>
                    setForm({ ...form, instructions: event.target.value })
                  }
                  className="mt-1"
                />
              </div>

              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {t("fieldSections")}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("fieldSectionsHint")}
                </p>
                {!form.courseId || !form.periodId ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("sectionsNeedScope")}
                  </p>
                ) : sections.loading ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {tCommon("states.loading")}
                  </p>
                ) : (sections.data?.items ?? []).length === 0 ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("sectionsEmpty")}
                  </p>
                ) : (
                  <ul className="mt-2 space-y-1">
                    {(sections.data?.items ?? []).map((section) => {
                      const checked = form.sectionIds.includes(section.id);
                      return (
                        <li key={section.id}>
                          <label className="flex items-center gap-2 text-sm">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) =>
                                setForm({
                                  ...form,
                                  sectionIds: event.target.checked
                                    ? [...form.sectionIds, section.id]
                                    : form.sectionIds.filter((id) => id !== section.id),
                                })
                              }
                            />
                            <span className="min-w-0" dir="auto">
                              <span className="block">
                                {section.section_code ??
                                  section.source_label ??
                                  section.id.slice(0, 8)}
                              </span>
                              {section.program_offerings.length > 0 && (
                                <span className="block text-xs text-muted-foreground">
                                  {section.program_offerings
                                    .map((offering) => offering.name)
                                    .join(" · ")}
                                </span>
                              )}
                            </span>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          )}

          <DialogFooter>
            <Button onClick={submitForm} disabled={saving}>
              {saving ? t("saving") : t("save")}
            </Button>
            <Button variant="outline" onClick={() => setForm(null)} disabled={saving}>
              {tCommon("actions.cancel")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Cancellation ── */}
      <Dialog
        open={!!cancelTarget}
        onOpenChange={(open) => {
          if (!open) {
            setCancelTarget(null);
            setCancelReason("");
          }
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("cancelTitle")}</DialogTitle>
            <DialogDescription>{cancelTarget?.title}</DialogDescription>
          </DialogHeader>
          <div>
            <label htmlFor="cancel-reason" className="text-xs font-semibold uppercase tracking-[0.1em] text-muted-foreground">
              {t("cancelReason")}
            </label>
            <Textarea
              id="cancel-reason"
              rows={3}
              value={cancelReason}
              onChange={(event) => setCancelReason(event.target.value)}
              className="mt-1"
            />
            <p className="mt-1 text-xs text-muted-foreground">{t("cancelReasonHint")}</p>
          </div>
          <DialogFooter>
            <Button variant="destructive" onClick={submitCancel} disabled={saving}>
              {saving ? t("saving") : t("cancelSubmit")}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                setCancelTarget(null);
                setCancelReason("");
              }}
              disabled={saving}
            >
              {tCommon("actions.cancel")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}

// ── Detail panel ──

function ExaminationPanel({
  detail,
  canManage,
  canRecord,
  canPublish,
  saving,
  draft,
  setDraft,
  onSubmitResult,
  onPublish,
  onEdit,
  onCancel,
  formatDay,
  formatTime,
  formatStamp,
}: {
  detail: ExaminationDetail;
  canManage: boolean;
  canRecord: boolean;
  canPublish: boolean;
  saving: boolean;
  draft: ResultDraft | null;
  setDraft: (draft: ResultDraft | null) => void;
  onSubmitResult: () => void;
  onPublish: () => void;
  onEdit: () => void;
  onCancel: () => void;
  formatDay: (value: string) => string;
  formatTime: (value: string) => string;
  formatStamp: (value: string) => string;
}) {
  const t = useTranslations("examinations");
  const tCommon = useTranslations("common");
  const { examination, eligible_students, results } = detail;
  const currentResults = results.filter((row) => row.is_current);
  const historyResults = results.filter((row) => !row.is_current);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        {examination.status === "CANCELLED" ? (
          <StatusBadge tone="danger">{t("cancelled")}</StatusBadge>
        ) : examination.published_at ? (
          <StatusBadge tone="success">{t("published")}</StatusBadge>
        ) : (
          <StatusBadge tone="muted">{t("unpublished")}</StatusBadge>
        )}
        <span>
          {formatDay(examination.exam_date)} · {formatTime(examination.start_time)} –{" "}
          {formatTime(examination.end_time)}
        </span>
        <span className="inline-flex items-center gap-1">
          <MapPin className="h-3 w-3" aria-hidden="true" />
          {examination.location ?? t("noLocation")}
        </span>
        {examination.program_offering_name && (
          <span className="inline-flex items-center gap-1">
            <GraduationCap className="h-3 w-3" aria-hidden="true" />
            {examination.program_offering_name}
          </span>
        )}
      </div>

      {examination.cancellation_reason && (
        <p className="rounded-lg border border-destructive/40 p-2 text-xs text-muted-foreground">
          {examination.cancellation_reason}
        </p>
      )}

      {examination.instructions && (
        <div>
          <p className="text-sm font-semibold">{t("instructionsTitle")}</p>
          <p className="mt-1 whitespace-pre-line text-xs text-muted-foreground">
            {examination.instructions}
          </p>
        </div>
      )}

      <div>
        <p className="mb-1 text-sm font-semibold">{t("sectionsTitle")}</p>
        <ul className="grid gap-2 sm:grid-cols-2">
          {examination.sections.map((section) => (
            <li
              key={section.class_section_id}
              className="rounded-lg border border-border/70 px-2.5 py-1.5"
            >
              <p className="text-sm font-medium">{section.label}</p>
              <p className="text-[11px] text-muted-foreground">
                {section.offerings.length > 0
                  ? section.offerings.join(" · ")
                  : t("noOffering")}
                {" · "}
                {t("eligibleInSection", { count: section.eligible_count })}
              </p>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-wrap gap-2">
        {canManage && examination.status !== "CANCELLED" && (
          <Button variant="outline" size="sm" onClick={onEdit} disabled={saving}>
            {t("editAction")}
          </Button>
        )}
        {canManage && examination.status !== "CANCELLED" && (
          <Button variant="outline" size="sm" onClick={onCancel} disabled={saving}>
            <XCircle className="me-1 h-3.5 w-3.5" aria-hidden="true" />
            {t("cancelAction")}
          </Button>
        )}
        {canPublish && examination.status !== "CANCELLED" && !examination.published_at && (
          <Button size="sm" onClick={onPublish} disabled={saving}>
            <Send className="me-1 h-3.5 w-3.5" aria-hidden="true" />
            {t("publishAction")}
          </Button>
        )}
      </div>

      {examination.published_at && (
        <p className="text-xs text-muted-foreground">
          {t("publishedBy", {
            name: examination.published_by_name ?? "—",
            date: formatStamp(examination.published_at),
          })}
        </p>
      )}

      <div>
        <p className="mb-1 text-sm font-semibold">
          {t("eligibleTitle")} ({eligible_students.length})
        </p>
        {eligible_students.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("noEligible")}</p>
        ) : (
          <ul className="divide-y divide-border/60 rounded-lg border border-border/70">
            {eligible_students.map((student) => {
              const current = currentResults.find(
                (row) => row.student_id === student.student_id,
              );
              const editing =
                draft && draft.studentId === student.student_id ? draft : null;
              return (
                <li key={student.student_id} className="p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <Link
                        href={`/app/students/${student.student_id}`}
                        className="truncate font-medium underline-offset-2 hover:text-primary hover:underline"
                        title={t("openStudent")}
                      >
                        {student.student_name}
                      </Link>
                      <p className="font-mono text-xs text-muted-foreground" dir="ltr">
                        {student.student_number}
                      </p>
                      {(student.program_offering_name ||
                        student.section_labels.length > 0) && (
                        <p className="truncate text-[11px] text-muted-foreground">
                          {[
                            student.program_offering_name,
                            student.section_labels.join(" · "),
                          ]
                            .filter(Boolean)
                            .join(" — ")}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      {current ? (
                        <span className="tabular-nums text-sm font-semibold">
                          {t("scoreValue", { score: current.score })}
                          {current.letter_grade ? ` · ${current.letter_grade}` : ""}
                        </span>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          {t("noResultRecorded")}
                        </span>
                      )}
                      {canRecord &&
                        examination.status !== "CANCELLED" &&
                        !editing &&
                        (current ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              setDraft({
                                studentId: student.student_id,
                                score: String(current.score),
                                letter: current.letter_grade ?? "",
                                note: current.note ?? "",
                                resultId: current.id,
                                reason: "",
                              })
                            }
                          >
                            {t("correctAction")}
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() =>
                              setDraft({
                                studentId: student.student_id,
                                score: "",
                                letter: "",
                                note: "",
                                reason: "",
                              })
                            }
                          >
                            {t("recordAction")}
                          </Button>
                        ))}
                    </div>
                  </div>

                  {editing && (
                    <div className="mt-3 space-y-2 rounded-lg border border-border/80 p-3">
                      <p className="text-sm font-semibold">
                        {editing.resultId ? t("correctionTitle") : t("recordTitle")}
                      </p>
                      <div className="grid gap-2 sm:grid-cols-2">
                        <div>
                          <label className="text-xs text-muted-foreground" htmlFor={`score-${student.student_id}`}>
                            {t("recordScore")}
                          </label>
                          <Input
                            id={`score-${student.student_id}`}
                            type="number"
                            dir="ltr"
                            min={0}
                            value={editing.score}
                            onChange={(event) =>
                              setDraft({ ...editing, score: event.target.value })
                            }
                          />
                        </div>
                        <div>
                          <label className="text-xs text-muted-foreground" htmlFor={`letter-${student.student_id}`}>
                            {t("recordLetter")}
                          </label>
                          <Input
                            id={`letter-${student.student_id}`}
                            value={editing.letter}
                            onChange={(event) =>
                              setDraft({ ...editing, letter: event.target.value })
                            }
                          />
                        </div>
                      </div>
                      <div>
                        <label className="text-xs text-muted-foreground" htmlFor={`note-${student.student_id}`}>
                          {t("recordNote")}
                        </label>
                        <Input
                          id={`note-${student.student_id}`}
                          value={editing.note}
                          onChange={(event) =>
                            setDraft({ ...editing, note: event.target.value })
                          }
                        />
                      </div>
                      {editing.resultId && (
                        <div>
                          <label className="text-xs text-muted-foreground" htmlFor={`reason-${student.student_id}`}>
                            {t("correctionReason")}
                          </label>
                          <Textarea
                            id={`reason-${student.student_id}`}
                            rows={2}
                            value={editing.reason}
                            onChange={(event) =>
                              setDraft({ ...editing, reason: event.target.value })
                            }
                          />
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t("correctionReasonHint")}
                          </p>
                        </div>
                      )}
                      <div className="flex gap-2">
                        <Button size="sm" onClick={onSubmitResult} disabled={saving}>
                          {saving
                            ? t("saving")
                            : editing.resultId
                              ? t("correctionSubmit")
                              : t("recordSubmit")}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setDraft(null)}
                          disabled={saving}
                        >
                          {tCommon("actions.cancel")}
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {historyResults.length > 0 && (
        <div>
          <p className="mb-1 text-sm font-semibold">{t("historyTitle")}</p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {historyResults.map((row) => (
              <li key={row.id} className="rounded-md border border-border/60 p-2">
                <span className="font-medium text-foreground">
                  {row.student_name ?? "—"}
                </span>{" "}
                · {t("scoreValue", { score: row.score })}
                {row.letter_grade ? ` · ${row.letter_grade}` : ""}
                {row.correction_reason ? ` · ${row.correction_reason}` : ""}
                <span className="block">
                  {t("recordedBy", {
                    name: row.recorded_by_name ?? "—",
                    date: formatStamp(row.recorded_at),
                  })}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
