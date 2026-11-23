"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import { studentApi } from "@/lib/student-api";
import { listPeriods, listPrograms } from "@/lib/academic-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError } from "@/lib/api-error";
import { downloadBlob } from "@/lib/download";
import {
  Download,
  Eye,
  FileUp,
  RotateCcw,
  SlidersHorizontal,
  UserPlus,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { DataTable, type Column } from "@/components/ui/data-table";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import { toast } from "@/components/ui/toast";
import { OnboardStudentDialog } from "@/components/students/onboard-student-dialog";
import { BulkStatusDialog } from "@/components/students/bulk-status-dialog";
import { ImportStudentsDialog } from "@/components/students/import-students-dialog";
import { StudentPeekDialog } from "@/components/students/student-peek";
import type {
  ImmigrationStatusFilter,
  StudentBrief,
  StudentListResponse,
  StudentSort,
  StudentStatus,
} from "@/types/student";

const STATUS_VALUES: StudentStatus[] = [
  "ACTIVE",
  "INACTIVE",
  "GRADUATED",
  "WITHDRAWN",
  "SUSPENDED",
];

const IMMIGRATION_VALUES: ImmigrationStatusFilter[] = [
  "VALID",
  "EXPIRING_SOON",
  "URGENT",
  "EXPIRED",
  "NOT_PROVIDED",
];

const SORT_VALUES: StudentSort[] = [
  "name",
  "-name",
  "student_number",
  "-student_number",
  "newest",
  "oldest",
];

const PAGE_SIZE = 25;

function initialsOf(student: StudentBrief) {
  return `${student.first_name[0] ?? ""}${student.last_name[0] ?? ""}`.toUpperCase();
}

/** Stable 1–6 avatar tint per student, so a long directory scans faster. */
function toneOf(student: StudentBrief) {
  const key = `${student.first_name}${student.last_name}${student.id}`;
  let sum = 0;
  for (let index = 0; index < key.length; index += 1) sum += key.charCodeAt(index);
  return (sum % 6) + 1;
}

export default function StudentsPage() {
  const t = useTranslations("students");
  const tCommon = useTranslations("common");
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StudentStatus | "">("");
  const [immigrationFilter, setImmigrationFilter] = useState<
    ImmigrationStatusFilter | ""
  >("");
  const [programFilter, setProgramFilter] = useState("");
  const [originalIntakeFilter, setOriginalIntakeFilter] = useState("");
  const [currentIntakeFilter, setCurrentIntakeFilter] = useState("");
  const [sort, setSort] = useState<StudentSort>("name");
  const [page, setPage] = useState(1);

  const [onboarding, setOnboarding] = useState(false);
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [peek, setPeek] = useState<StudentBrief | null>(null);

  const fetchStudents = useCallback(
    () =>
      studentApi.listStudents({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        status: (statusFilter as StudentStatus) || undefined,
        immigration_status: (immigrationFilter as ImmigrationStatusFilter) || undefined,
        program_id: programFilter || undefined,
        original_intake_id: originalIntakeFilter || undefined,
        current_intake_id: currentIntakeFilter || undefined,
        sort,
      }),
    [
      page,
      search,
      statusFilter,
      immigrationFilter,
      programFilter,
      originalIntakeFilter,
      currentIntakeFilter,
      sort,
    ],
  );

  const { data, loading, error, refetch } = useApi<StudentListResponse>(
    fetchStudents,
    [
      page,
      search,
      statusFilter,
      immigrationFilter,
      programFilter,
      originalIntakeFilter,
      currentIntakeFilter,
      sort,
    ],
    "student directory",
  );

  // Programs are only needed to populate the filter. A failure here must not
  // take down the directory, so it degrades to "no program filter".
  const fetchPrograms = useCallback(() => listPrograms(1, 100), []);
  const programs = useApi(fetchPrograms, [], "program filter");
  const periods = useApi(() => listPeriods(1, 100), [], "intake filter");

  // The directory is a staff surface. A student holds `student.view` for their
  // own record only, so the API rejects this call — say so plainly rather than
  // showing a generic failure.
  const forbidden = error?.kind === "forbidden";
  const localized = localizeError(error);
  const canManage = hasPermission("student.create");
  const canEdit = hasPermission("student.edit");
  const students = data?.items ?? [];
  const meta = data?.meta;

  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await studentApi.exportDirectory();
      downloadBlob(blob, `students-${new Date().toISOString().slice(0, 10)}.csv`);
    } catch (err) {
      // An export is a data-protection action, so a refusal is reported rather
      // than silently doing nothing.
      toast.error(localizeError(normalizeApiError(err, "student export")).message);
    } finally {
      setExporting(false);
    }
  };

  const resetTo = (update: () => void) => {
    update();
    setPage(1);
    setSelected([]);
  };

  const statusOptions = useMemo(
    () => [
      { value: "", label: tCommon("labels.all") },
      ...STATUS_VALUES.map((value) => ({ value, label: t(`status.${value}`) })),
    ],
    [t, tCommon],
  );

  const immigrationOptions = useMemo(
    () => [
      { value: "", label: tCommon("labels.all") },
      ...IMMIGRATION_VALUES.map((value) => ({
        value,
        label: t(`immigrationFilter.${value}`),
      })),
    ],
    [t, tCommon],
  );

  const sortOptions = useMemo(
    () => SORT_VALUES.map((value) => ({ value, label: t(`sort.${value}`) })),
    [t],
  );

  const programOptions = useMemo(
    () => [
      { value: "", label: tCommon("labels.all") },
      ...(programs.data?.items ?? []).map((program) => ({
        value: program.id,
        label: program.name,
      })),
    ],
    [programs.data, tCommon],
  );

  const intakeOptions = useMemo(
    () => [
      { value: "", label: tCommon("labels.all") },
      ...(periods.data?.items ?? []).map((period) => ({
        value: period.id,
        label: period.name,
      })),
    ],
    [periods.data, tCommon],
  );

  const hasFilters = Boolean(
    search ||
      statusFilter ||
      immigrationFilter ||
      programFilter ||
      originalIntakeFilter ||
      currentIntakeFilter,
  );

  const clearFilters = () => {
    setSearch("");
    setStatusFilter("");
    setImmigrationFilter("");
    setProgramFilter("");
    setOriginalIntakeFilter("");
    setCurrentIntakeFilter("");
    setPage(1);
    setSelected([]);
  };

  const allOnPageSelected =
    students.length > 0 && students.every((s) => selected.includes(s.id));

  const toggleAll = () =>
    setSelected(allOnPageSelected ? [] : students.map((s) => s.id));

  const toggleOne = (id: string) =>
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );

  const columns: Column<StudentBrief>[] = [
    ...(canEdit
      ? [
          {
            key: "select",
            header: (
              <input
                type="checkbox"
                checked={allOnPageSelected}
                onChange={toggleAll}
                aria-label={t("selectAllOnPage")}
                className="h-4 w-4 rounded border-input align-middle"
              />
            ),
            className: "w-10",
            cell: (student: StudentBrief) => (
              <input
                type="checkbox"
                checked={selected.includes(student.id)}
                onChange={() => toggleOne(student.id)}
                aria-label={t("selectStudent", {
                  name: `${student.first_name} ${student.last_name}`,
                })}
                className="h-4 w-4 rounded border-input align-middle"
              />
            ),
          } satisfies Column<StudentBrief>,
        ]
      : []),
    {
      key: "student",
      header: t("columns.student"),
      cell: (student) => (
        <div className="flex min-w-0 items-center gap-3">
          <span
            className="scu-avatar h-8 w-8 shrink-0 text-[10px] font-semibold tracking-wide ring-1 ring-border ring-offset-2 ring-offset-card"
            data-tone={toneOf(student)}
            aria-hidden="true"
          >
            {initialsOf(student)}
          </span>
          <div className="min-w-0">
            <Link
              href={`/app/students/${student.id}`}
              className="rounded-sm font-medium hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {student.last_name}, {student.first_name}
            </Link>
            {student.preferred_name && (
              <p className="text-xs text-muted-foreground">({student.preferred_name})</p>
            )}
            {student.user_email && (
              <p className="truncate text-xs text-muted-foreground" dir="ltr">
                {student.user_email}
              </p>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "student_id",
      header: t("columns.studentId"),
      cell: (student) => (
        <span className="font-mono text-xs">{student.student_id}</span>
      ),
    },
    {
      key: "nationality",
      header: t("columns.nationality"),
      hideOnMobile: true,
      cell: (student) => student.nationality ?? tCommon("states.notSet"),
    },
    {
      key: "status",
      header: t("columns.status"),
      cell: (student) => (
        <StatusBadge tone={toneForStatus(student.status)}>
          {t(`status.${student.status}`)}
        </StatusBadge>
      ),
    },
    {
      key: "actions",
      header: tCommon("labels.actions"),
      className: "text-end",
      cell: (student) => (
        <Button variant="ghost" size="sm" onClick={() => setPeek(student)}>
          <Eye className="h-3.5 w-3.5" aria-hidden="true" />
          {t("peek.quickView")}
        </Button>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("directory")}
        description={
          meta ? tCommon("counts.students", { count: meta.total }) : t("subtitle")
        }
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
        actions={
          canManage ? (
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => setImporting(true)}
              >
                <FileUp className="h-4 w-4" aria-hidden="true" />
                {t("intake.button")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleExport}
                disabled={exporting}
              >
                <Download className="h-4 w-4" aria-hidden="true" />
                {t("intake.exportButton")}
              </Button>
              <Button size="sm" onClick={() => setOnboarding(true)}>
                <UserPlus className="h-4 w-4" aria-hidden="true" />
                {t("createStudent")}
              </Button>
            </div>
          ) : undefined
        }
      />

      {importing && (
        <ImportStudentsDialog
          open={importing}
          onOpenChange={setImporting}
          onImported={refetch}
        />
      )}

      {onboarding && (
        <OnboardStudentDialog
          open={onboarding}
          onOpenChange={setOnboarding}
          onCreated={refetch}
        />
      )}

      {bulkOpen && (
        <BulkStatusDialog
          open={bulkOpen}
          onOpenChange={setBulkOpen}
          studentIds={selected}
          onApplied={() => {
            setSelected([]);
            refetch();
          }}
        />
      )}

      {forbidden ? (
        <EmptyState title={t("denied")} message={tCommon("labels.noResultsHint")} />
      ) : (
        <>
          <Card className="mb-4">
            <CardHeader className="flex-row items-center justify-between gap-2 space-y-0 pb-3">
              <span className="flex items-center gap-2">
                <SlidersHorizontal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <CardTitle className="text-sm">{tCommon("labels.filters")}</CardTitle>
              </span>
              {hasFilters && (
                <Button variant="ghost" size="sm" onClick={clearFilters}>
                  <RotateCcw className="me-1.5 h-3.5 w-3.5" aria-hidden="true" />
                  {t("clearFilters")}
                </Button>
              )}
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SearchInput
                value={search}
                onChange={(value) => resetTo(() => setSearch(value))}
                placeholder={t("searchPlaceholder")}
                className="sm:col-span-2 lg:col-span-1"
              />
              <FilterSelect
                label={t("filterByStatus")}
                value={statusFilter}
                showLabel
                options={statusOptions}
                onChange={(value) =>
                  resetTo(() => setStatusFilter(value as StudentStatus | ""))
                }
              />
              <FilterSelect
                label={t("filterByImmigration")}
                value={immigrationFilter}
                showLabel
                options={immigrationOptions}
                onChange={(value) =>
                  resetTo(() =>
                    setImmigrationFilter(value as ImmigrationStatusFilter | ""),
                  )
                }
              />
              <FilterSelect
                label={t("filterByProgram")}
                value={programFilter}
                showLabel
                options={programOptions}
                onChange={(value) => resetTo(() => setProgramFilter(value))}
              />
              <FilterSelect
                label={t("filterByOriginalIntake")}
                value={originalIntakeFilter}
                showLabel
                options={intakeOptions}
                onChange={(value) => resetTo(() => setOriginalIntakeFilter(value))}
              />
              <FilterSelect
                label={t("filterByCurrentIntake")}
                value={currentIntakeFilter}
                showLabel
                options={intakeOptions}
                onChange={(value) => resetTo(() => setCurrentIntakeFilter(value))}
              />
              <FilterSelect
                label={t("sortLabel")}
                value={sort}
                showLabel
                options={sortOptions}
                onChange={(value) => resetTo(() => setSort(value as StudentSort))}
              />
            </CardContent>
          </Card>

          {canEdit && selected.length > 0 && (
            <div
              role="region"
              aria-label={t("bulk.title")}
              className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-primary/15 bg-primary/[0.045] px-4 py-3"
            >
              <span className="text-sm font-medium">
                {t("selectedCount", { count: selected.length })}
              </span>
              <Button size="sm" onClick={() => setBulkOpen(true)}>
                {t("bulk.changeStatus")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSelected([])}>
                {tCommon("actions.clear")}
              </Button>
            </div>
          )}

          <DataTable
            columns={columns}
            rows={students}
            rowKey={(student) => student.id}
            loading={loading}
            error={error ? localized.message : null}
            onRetry={refetch}
            emptyTitle={t("empty")}
            emptyMessage={t("emptyHint")}
            mobileCard={(student) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    {canEdit && (
                      <input
                        type="checkbox"
                        checked={selected.includes(student.id)}
                        onChange={() => toggleOne(student.id)}
                        aria-label={t("selectStudent", {
                          name: `${student.first_name} ${student.last_name}`,
                        })}
                        className="mt-1 h-4 w-4 rounded border-input"
                      />
                    )}
                    <span
                      className="scu-avatar h-9 w-9 shrink-0 text-[10px] font-semibold tracking-wide ring-1 ring-border ring-offset-2 ring-offset-card"
                      data-tone={toneOf(student)}
                      aria-hidden="true"
                    >
                      {initialsOf(student)}
                    </span>
                    <Link
                      href={`/app/students/${student.id}`}
                      className="rounded-sm font-medium hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {student.last_name}, {student.first_name}
                    </Link>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <StatusBadge tone={toneForStatus(student.status)}>
                      {t(`status.${student.status}`)}
                    </StatusBadge>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2"
                      onClick={() => setPeek(student)}
                    >
                      <Eye className="h-3.5 w-3.5" aria-hidden="true" />
                      <span className="sr-only">{t("peek.quickView")}</span>
                    </Button>
                  </div>
                </div>
                <p className="font-mono text-xs text-muted-foreground">
                  {student.student_id}
                </p>
                <p className="text-sm text-muted-foreground">
                  {student.nationality ?? tCommon("states.notSet")}
                </p>
              </div>
            )}
          />

          {meta && (
            <Pagination
              page={meta.page}
              pageSize={meta.page_size}
              total={meta.total}
              totalPages={meta.total_pages}
              onPageChange={setPage}
            />
          )}
        </>
      )}

      <StudentPeekDialog
        student={peek}
        open={Boolean(peek)}
        onOpenChange={(open) => {
          if (!open) setPeek(null);
        }}
      />
    </AppShell>
  );
}
