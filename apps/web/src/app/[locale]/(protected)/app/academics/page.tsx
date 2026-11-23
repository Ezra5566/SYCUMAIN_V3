"use client";

import { useCallback, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import {
  listPrograms,
  listCourses,
  listPeriods,
  listClassSections,
  listClassrooms,
  listTimetable,
  listProgramOfferings,
  listSourceIntakes,
} from "@/lib/academic-api";
import {
  ClassSectionDialog,
  ClassroomDialog,
  CourseDialog,
  PeriodDialog,
  ProgramOfferingDialog,
  SectionOfferingsDialog,
} from "@/components/academics/structure-admin";
import {
  RemoveTimetableEntryButton,
  TimetableEntryDialog,
} from "@/components/academics/timetable-editor";
import { ClassHistoryDialog } from "@/components/academics/class-history-dialog";
import { PeriodCorrectionDialog } from "@/components/academics/period-correction-dialog";
import { TeacherAssignmentsDialog } from "@/components/academics/teacher-assignment-dialog";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard, StatGrid } from "@/components/ui/stat-card";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { DataTable, type Column } from "@/components/ui/data-table";
import type {
  AcademicPeriod,
  ClassSection,
  Classroom,
  Course,
  Program,
  ProgramOffering,
  SourceIntake,
  SourceIntakeSubject,
  TimetableEntry,
} from "@/types/academic";
import { sectionLabel, timetableLabel } from "@/lib/academic-display";

/**
 * Weekday labels for the timetable grid.
 *
 * The academic schema documents `day_of_week` as 0 = Monday … 6 = Sunday, so
 * this list is indexed directly by that value. Weekend days are included
 * because the imported SCU timetable can schedule them.
 */
const WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

const COURSE_ACCENTS = [
  "border-s-primary/70 bg-primary/[0.045]",
  "border-s-info/70 bg-info-soft/35",
  "border-s-success/70 bg-success-soft/35",
  "border-s-warning/70 bg-warning-soft/35",
] as const;

/** Stable course colour: the same course reads the same throughout the page. */
function courseAccent(value: string) {
  const hash = Array.from(value).reduce((sum, char) => sum + char.charCodeAt(0), 0);
  return COURSE_ACCENTS[hash % COURSE_ACCENTS.length];
}

interface AcademicBundle {
  programs: Program[];
  courses: Course[];
  periods: AcademicPeriod[];
  intakes: SourceIntake[];
  selectedIntake: SourceIntake | null;
  selectedIntakeId: string | null;
  classes: ClassSection[];
  classrooms: Classroom[];
  timetable: TimetableEntry[];
  programOfferings: ProgramOffering[];
  selectedPeriodId: string | null;
  failed: string[];
}

/**
 * Loads academic sections independently so a single failing endpoint degrades
 * one card instead of blanking the whole dashboard.
 */
async function loadAcademicBundle(
  requestedIntakeId?: string,
  requestedProgramOfferingId?: string,
  requestedCourseId?: string,
): Promise<AcademicBundle> {
  const [catalog, periodPage] = await Promise.all([
    listSourceIntakes(),
    listPeriods(1, 50),
  ]);
  const intakes = catalog.items;
  const selectedIntake =
    intakes.find((intake) => intake.source_id === requestedIntakeId) ??
    intakes.find((intake) => intake.active) ??
    intakes[0] ??
    null;

  // An unconfigured intake must not fall back to the active period. Its source
  // offerings are loaded from the catalog; period-scoped records stay empty.
  const selectedPeriodId = selectedIntake?.period?.id ?? null;
  const scopedOfferingId = selectedPeriodId ? requestedProgramOfferingId : undefined;
  const scopedCourseId = selectedPeriodId ? requestedCourseId : undefined;

  const results = await Promise.allSettled([
    listPrograms(1, 100),
    listCourses(1, 100),
    selectedPeriodId
      ? listClassSections(
          1,
          100,
          undefined,
          selectedPeriodId,
          scopedOfferingId,
          scopedCourseId,
        )
      : Promise.resolve({ items: [] as ClassSection[] }),
    listClassrooms(1, 100),
    selectedPeriodId
      ? listTimetable(
          selectedPeriodId,
          undefined,
          scopedOfferingId,
          scopedCourseId,
        )
      : Promise.resolve({ items: [] as TimetableEntry[] }),
    selectedPeriodId
      ? listProgramOfferings(selectedPeriodId)
      : Promise.resolve({ items: [] as ProgramOffering[] }),
  ]);

  const [programs, courses, classes, classrooms, timetable, programOfferings] =
    results;
  const sectionKeys = [
    "programs",
    "courses",
    "classes",
    "classrooms",
    "timetable",
    "programOfferings",
  ] as const;

  const failed: string[] = [];
  results.forEach((result, index) => {
    if (result.status === "rejected") failed.push(sectionKeys[index]);
  });

  // Only rethrow when nothing loaded — otherwise show what we have.
  if (failed.length === results.length) {
    throw results[0].status === "rejected"
      ? results[0].reason
      : new Error("Academic load failed");
  }

  return {
    programs: programs.status === "fulfilled" ? programs.value.items : [],
    courses: courses.status === "fulfilled" ? courses.value.items : [],
    periods: periodPage.items,
    intakes,
    selectedIntake,
    selectedIntakeId: selectedIntake?.source_id ?? null,
    classes: classes.status === "fulfilled" ? classes.value.items : [],
    classrooms:
      classrooms.status === "fulfilled" ? classrooms.value.items : [],
    timetable: timetable.status === "fulfilled" ? timetable.value.items : [],
    programOfferings:
      programOfferings.status === "fulfilled" ? programOfferings.value.items : [],
    selectedPeriodId,
    failed,
  };
}

export default function AcademicsPage() {
  const t = useTranslations("academics");
  const tInstitutional = useTranslations("institutional");
  const tCommon = useTranslations("common");
  const { hasPermission, hasRole } = useAuth();
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();
  const format = useFormatter();
  const [selectedIntakeId, setSelectedIntakeId] = useState("");
  const [programOfferingId, setProgramOfferingId] = useState("");
  const [courseId, setCourseId] = useState("");

  const { data, loading, error, refetch } = useApi(
    () =>
      loadAcademicBundle(
        selectedIntakeId || undefined,
        programOfferingId || undefined,
        courseId || undefined,
      ),
    [selectedIntakeId, programOfferingId, courseId],
    "academic dashboard",
  );

  const localized = localizeError(error);

  // One flag per entity rather than a single "can edit academics". The
  // permissions are granted separately, so a clerk who may schedule the
  // timetable but not rename a major must not be shown the major dialog and
  // then refused by the API.
  const canManage = {
    programs: hasPermission("academic.manage_programs"),
    courses: hasPermission("academic.manage_courses"),
    periods: hasPermission("academic.manage_periods"),
    classes: hasPermission("academic.manage_classes"),
    classrooms: hasPermission("academic.manage_classrooms"),
    timetable: hasPermission("academic.manage_timetable"),
    offerings: hasPermission("academic.manage_programs"),
    teachers: hasPermission("academic.manage_teachers"),
  };
  const canCorrectPeriodDates = hasPermission("academic.correct_period_dates");

  const dateRange = (start: string, end: string) =>
    `${format.dateTime(new Date(start), { dateStyle: "short" })} – ${format.dateTime(
      new Date(end),
      { dateStyle: "short" },
    )}`;

  const periodColumns: Column<AcademicPeriod>[] = [
    {
      key: "name",
      header: t("academicPeriod"),
      cell: (period) => (
        <div>
          <p className="font-medium">{period.name}</p>
          <p className="font-mono text-xs text-muted-foreground">{period.code}</p>
        </div>
      ),
    },
    {
      key: "dates",
      header: tCommon("labels.date"),
      cell: (period) => (
        <span className="text-sm tabular-nums">
          {dateRange(period.start_date, period.end_date)}
        </span>
      ),
    },
    {
      key: "status",
      header: tCommon("labels.status"),
      cell: (period) => (
        <StatusBadge tone={toneForStatus(period.status)}>
          {statusLabel(period.status, "academics.periodStatus")}
        </StatusBadge>
      ),
    },
  ];

  if (canManage.periods || canCorrectPeriodDates) {
    periodColumns.push({
      key: "actions",
      header: tCommon("labels.actions"),
      cell: (period) => (
        <div className="flex flex-wrap items-center gap-1">
          {canManage.periods && <PeriodDialog period={period} onSaved={refetch} />}
          {canCorrectPeriodDates &&
            period.date_correction_enabled &&
            (period.status !== "COMPLETED" || hasRole("ADMIN")) && (
              <PeriodCorrectionDialog period={period} onSaved={refetch} />
            )}
        </div>
      ),
    });
  }

  const courseColumns: Column<Course>[] = [
    {
      key: "code",
      header: t("courseCode"),
      cell: (course) => (
        <span className="font-mono">{course.code ?? tCommon("states.notSet")}</span>
      ),
    },
    { key: "name", header: t("course"), cell: (course) => course.name },
    {
      key: "program",
      header: t("program"),
      hideOnMobile: true,
      cell: (course) => course.program_name ?? tCommon("states.notSet"),
    },
    {
      key: "credits",
      header: t("credits"),
      cell: (course) => course.credits ?? t("creditsNotProvided"),
    },
  ];

  // The action column is appended, not hidden, so a viewer without the
  // permission gets no empty column header at all.
  if (canManage.courses) {
    courseColumns.push({
      key: "actions",
      header: tCommon("labels.actions"),
      cell: (course) => (
        <CourseDialog
          course={course}
          programs={data?.programs ?? []}
          onSaved={refetch}
        />
      ),
    });
  }

  const classroomColumns: Column<Classroom>[] = [
    {
      key: "room",
      header: t("classroom"),
      cell: (room) => (
        <div>
          <p className="font-medium">{room.room_code}</p>
          {room.building && (
            <p className="text-xs text-muted-foreground">{room.building}</p>
          )}
        </div>
      ),
    },
    {
      key: "capacity",
      header: t("fields.capacity"),
      cell: (room) => room.capacity ?? t("capacityNotProvided"),
    },
    {
      key: "status",
      header: tCommon("labels.status"),
      cell: (room) => (
        <StatusBadge tone={toneForStatus(room.status)}>
          {statusLabel(room.status, "academics.classroomStatus")}
        </StatusBadge>
      ),
    },
  ];

  if (canManage.classrooms) {
    classroomColumns.push({
      key: "actions",
      header: tCommon("labels.actions"),
      cell: (room) => <ClassroomDialog classroom={room} onSaved={refetch} />,
    });
  }

  if (!hasPermission("academic.view")) {
    return (
      <AppShell>
        <EmptyState title={t("studentScopeNotice")} message={tCommon("labels.noResultsHint")} />
      </AppShell>
    );
  }

  const selectedIntake =
    data?.intakes.find(
      (intake) => intake.source_id === (selectedIntakeId || data?.selectedIntakeId),
    ) ??
    data?.selectedIntake ??
    null;
  const selectedPeriod = selectedIntake?.period ?? null;
  const isConfigured = Boolean(selectedPeriod);
  const todayIndex = (new Date().getDay() + 6) % 7;

  const renderSubjects = (subjects: SourceIntakeSubject[]) => (
    <ul className="mt-2 space-y-1.5">
      {subjects.map((subject) => (
        <li
          key={`${subject.section_key}-${subject.name}`}
          className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground"
        >
          <span className="min-w-0 truncate">{subject.name}</span>
          {subject.delivery === "shared" && (
            <StatusBadge tone="info" icon={null} className="px-1.5 py-0.5 text-[10px]">
              {subject.shared_with.length > 0
                ? t("sharedWith", { count: subject.shared_with.length })
                : t("sharedTeaching")}
            </StatusBadge>
          )}
          {subject.held && (
            <StatusBadge tone="warning" className="px-1.5 py-0.5 text-[10px]">
              {t("heldConflict")}
            </StatusBadge>
          )}
        </li>
      ))}
    </ul>
  );
  const timetableSlots = Array.from(
    new Set((data?.timetable ?? []).map((entry) => entry.start_time.slice(0, 5))),
  ).sort();

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
          selectedIntake && (
            <StatusBadge tone={selectedIntake.active ? "success" : "warning"}>
              {selectedIntake.name}
            </StatusBadge>
          )
        }
      />

      {error ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState message={localized.message} hint={localized.hint} onRetry={refetch} />
          </CardContent>
        </Card>
      ) : (
        <>
          {data && data.failed.length > 0 && (
            <div
              role="status"
              className="mb-4 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning"
            >
              {t("noCourses")}
            </div>
          )}

          <div className="mb-5 flex flex-col gap-3 rounded-xl border border-border/80 bg-muted/20 p-3 sm:flex-row sm:items-end">
            <label className="flex-1 space-y-1.5 text-xs font-medium">
              <span className="block text-muted-foreground">{t("intakeFilter")}</span>
              <select
                className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                value={selectedIntakeId || data?.selectedIntakeId || ""}
                onChange={(event) => {
                  setSelectedIntakeId(event.target.value);
                  setProgramOfferingId("");
                  setCourseId("");
                }}
              >
                {(data?.intakes ?? []).map((intake) => (
                  <option key={intake.source_id} value={intake.source_id}>
                    {intake.name}
                  </option>
                ))}
              </select>
            </label>
            {isConfigured && (
              <>
                <label className="flex-1 space-y-1.5 text-xs font-medium">
                  <span className="block text-muted-foreground">
                    {t("programOfferingFilter")}
                  </span>
                  <select
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                    value={programOfferingId}
                    onChange={(event) => {
                      setProgramOfferingId(event.target.value);
                      setCourseId("");
                    }}
                  >
                    <option value="">{t("allProgramOfferings")}</option>
                    {(data?.programOfferings ?? []).map((offering) => (
                      <option key={offering.id} value={offering.id}>
                        {offering.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex-1 space-y-1.5 text-xs font-medium">
                  <span className="block text-muted-foreground">{t("courseFilter")}</span>
                  <select
                    className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
                    value={courseId}
                    onChange={(event) => setCourseId(event.target.value)}
                  >
                    <option value="">{t("allCourses")}</option>
                    {(data?.courses ?? []).map((course) => (
                      <option key={course.id} value={course.id}>
                        {course.name}
                      </option>
                    ))}
                  </select>
                </label>
              </>
            )}
          </div>

          {selectedIntake && (
            <div className="mb-5 rounded-xl border border-border/80 bg-muted/20 p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{selectedIntake.name}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("intakeSummary")}
                  </p>
                </div>
                <StatusBadge tone={selectedIntake.active ? "success" : "neutral"}>
                  {selectedIntake.active ? t("active") : t("notActive")}
                </StatusBadge>
              </div>
              <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-lg border border-border/70 bg-background/60 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground">{t("sourceIntake")}</p>
                  <StatusBadge
                    className="mt-1.5"
                    tone={selectedIntake.source_identified ? "success" : "danger"}
                  >
                    {selectedIntake.source_identified ? t("identified") : t("notAvailable")}
                  </StatusBadge>
                </div>
                <div className="rounded-lg border border-border/70 bg-background/60 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground">{t("academicPeriod")}</p>
                  <StatusBadge
                    className="mt-1.5"
                    tone={selectedIntake.period_configured ? "success" : "warning"}
                  >
                    {selectedIntake.period_configured
                      ? t("configured")
                      : t("notConfigured")}
                  </StatusBadge>
                </div>
                <div className="rounded-lg border border-border/70 bg-background/60 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground">{t("timetableData")}</p>
                  <StatusBadge
                    className="mt-1.5"
                    tone={selectedIntake.timetable_imported ? "success" : "neutral"}
                  >
                    {selectedIntake.timetable_imported
                      ? t("imported")
                      : t("notImported")}
                  </StatusBadge>
                </div>
                <div className="rounded-lg border border-border/70 bg-background/60 px-3 py-2">
                  <p className="text-[11px] text-muted-foreground">{t("readiness")}</p>
                  <StatusBadge
                    className="mt-1.5"
                    tone={selectedIntake.ready ? "success" : "warning"}
                  >
                    {selectedIntake.ready ? t("ready") : t("notReady")}
                  </StatusBadge>
                </div>
              </div>
              {isConfigured &&
                selectedIntake.verified_source_session_count !== null &&
                selectedIntake.verified_source_session_count !== undefined && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {t("verifiedSessions", {
                      verified: selectedIntake.verified_source_session_count,
                      total: selectedIntake.source_session_count,
                    })}
                  </p>
                )}
              {selectedIntake.held_section_count > 0 && (
                <p className="mt-2 text-xs font-medium text-warning">
                  {t("heldConflictHint")}
                </p>
              )}
              {!isConfigured && (
                <p className="mt-3 text-xs text-muted-foreground">
                  {t("sourceOnlyHint")}
                </p>
              )}
            </div>
          )}

          <StatGrid>
            <StatCard
              label={t("programOfferings")}
              value={
                loading
                  ? "—"
                  : isConfigured
                    ? (data?.programOfferings.length ?? 0)
                    : (selectedIntake?.offering_count ?? 0)
              }
            />
            <StatCard label={t("programs")} value={loading ? "—" : (data?.programs.length ?? 0)} />
            <StatCard label={t("courses")} value={loading ? "—" : (data?.courses.length ?? 0)} />
            <StatCard
              label={t("classes")}
              value={loading || !isConfigured ? "—" : (data?.classes.length ?? 0)}
            />
            <StatCard
              label={t("timetable")}
              value={loading || !isConfigured ? "—" : (data?.timetable.length ?? 0)}
            />
          </StatGrid>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <Card className="lg:col-span-2">
              <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
                <div>
                  <CardTitle className="text-base">{t("programOfferings")}</CardTitle>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {selectedIntake?.name ?? t("academicPeriod")}
                  </p>
                </div>
                {isConfigured && canManage.offerings && (
                  <ProgramOfferingDialog
                    periods={data?.periods ?? []}
                    programs={data?.programs ?? []}
                    onSaved={refetch}
                  />
                )}
              </CardHeader>
              <CardContent className="pt-0">
                {!isConfigured ? (
                  selectedIntake && selectedIntake.offerings.length > 0 ? (
                    <>
                      <p className="mb-3 text-xs text-muted-foreground">
                        {t("sourceOnlyOfferingsHint")}
                      </p>
                      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                        {selectedIntake.offerings.map((offering) => (
                          <li
                            key={offering.source_id}
                            className="min-w-0 rounded-lg border border-border/80 bg-muted/15 p-3"
                          >
                            <div className="flex min-w-0 items-start justify-between gap-2">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-medium">{offering.name}</p>
                                <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                                  {offering.source_id}
                                </p>
                              </div>
                              <StatusBadge tone="warning">{t("sourceOnly")}</StatusBadge>
                            </div>
                            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                              <span>{t("subjectsCount", { count: offering.subject_count })}</span>
                              <span aria-hidden="true">·</span>
                              <span>
                                {t("sharedSectionsCount", {
                                  count: offering.shared_section_count,
                                })}
                              </span>
                              {offering.held && (
                                <StatusBadge tone="warning" className="px-1.5 py-0.5 text-[10px]">
                                  {t("heldConflict")}
                                </StatusBadge>
                              )}
                            </div>
                            {renderSubjects(offering.subjects)}
                          </li>
                        ))}
                      </ul>
                    </>
                  ) : (
                    <EmptyState title={t("noProgramOfferings")} />
                  )
                ) : (data?.programOfferings.length ?? 0) === 0 ? (
                  <EmptyState title={t("noProgramOfferings")} />
                ) : (
                  <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
                    {data?.programOfferings.map((offering) => {
                      const source = selectedIntake?.offerings.find(
                        (item) => item.program_offering_id === offering.id,
                      );
                      return (
                        <li
                          key={offering.id}
                          className="min-w-0 rounded-lg border border-border/80 bg-muted/15 p-3"
                        >
                          <div className="flex min-w-0 items-start justify-between gap-3">
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium">{offering.name}</p>
                              <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                                {offering.source_id}
                              </p>
                              <p className="mt-1 truncate text-xs text-muted-foreground">
                                {selectedPeriod?.name ?? t("academicPeriod")}
                              </p>
                            </div>
                            {canManage.offerings && (
                              <ProgramOfferingDialog
                                offering={offering}
                                periods={data?.periods ?? []}
                                programs={data?.programs ?? []}
                                onSaved={refetch}
                              />
                            )}
                          </div>
                          {source && (
                            <>
                              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                                <span>{t("subjectsCount", { count: source.subject_count })}</span>
                                {source.mapped_section_count != null && (
                                  <>
                                    <span aria-hidden="true">·</span>
                                    <span>
                                      {t("mappedSections", {
                                        count: source.mapped_section_count,
                                      })}
                                    </span>
                                  </>
                                )}
                                {source.assigned_student_count != null && (
                                  <>
                                    <span aria-hidden="true">·</span>
                                    <span>
                                      {t("assignedStudents", {
                                        count: source.assigned_student_count,
                                      })}
                                    </span>
                                  </>
                                )}
                              </div>
                              {source.held && (
                                <p className="mt-2 text-xs font-medium text-warning">
                                  {t("heldConflictHint")}
                                </p>
                              )}
                              {renderSubjects(source.subjects)}
                            </>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
                <CardTitle className="text-base">{t("academicPeriods")}</CardTitle>
                {canManage.periods && <PeriodDialog onSaved={refetch} />}
              </CardHeader>
              <CardContent className="pt-0">
                <DataTable
                  columns={periodColumns}
                  rows={data?.periods ?? []}
                  rowKey={(period) => period.id}
                  loading={loading}
                  emptyTitle={t("noClasses")}
                />
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-base">{t("courses")}</CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <DataTable
                  columns={courseColumns}
                  rows={data?.courses ?? []}
                  rowKey={(course) => course.id}
                  loading={loading}
                  emptyTitle={t("noCourses")}
                />
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
                <CardTitle className="text-base">{t("classrooms")}</CardTitle>
                {canManage.classrooms && <ClassroomDialog onSaved={refetch} />}
              </CardHeader>
              <CardContent className="pt-0">
                <DataTable
                  columns={classroomColumns}
                  rows={data?.classrooms ?? []}
                  rowKey={(room) => room.id}
                  loading={loading}
                  emptyTitle={t("noClassrooms")}
                />
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
                <CardTitle className="text-base">{t("classes")}</CardTitle>
                {isConfigured && canManage.classes && (
                  <ClassSectionDialog
                    courses={data?.courses ?? []}
                    periods={data?.periods ?? []}
                    onSaved={refetch}
                  />
                )}
              </CardHeader>
              <CardContent>
                {!isConfigured ? (
                  <p className="text-sm text-muted-foreground">
                    {t("sourceOnlyClassesHint")}
                  </p>
                ) : (data?.classes.length ?? 0) === 0 ? (
                  <EmptyState title={t("noClasses")} />
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {data?.classes.map((section) => {
                      const capacity = section.capacity ?? null;
                      const fill =
                        capacity !== null && capacity > 0
                          ? section.enrolled_count / capacity
                          : 0;
                      return (
                        <div
                          key={section.id}
                          className={cn(
                            "overflow-hidden rounded-lg border border-s-[3px] border-border/80 p-3 shadow-card",
                            courseAccent(section.course_code ?? section.id),
                          )}
                        >
                          <div className="mb-1 flex items-start justify-between gap-2">
                            <span className="min-w-0 truncate font-mono text-xs text-muted-foreground">
                              {sectionLabel(section)}
                            </span>
                            <StatusBadge tone={toneForStatus(section.status)}>
                              {statusLabel(section.status, "academics.classStatus")}
                            </StatusBadge>
                          </div>
                          <p className="truncate text-sm font-medium">
                            {section.course_name ?? tCommon("states.notSet")}
                          </p>
                          <div className="mt-2 flex items-center justify-between gap-2">
                            <span className="text-[11px] text-muted-foreground tabular-nums">
                              {capacity === null
                                ? t("capacityNotProvided")
                                : t("capacityCount", {
                                    enrolled: section.enrolled_count,
                                    capacity,
                                  })}
                            </span>
                            {capacity !== null && (
                              <span className="text-[11px] font-medium tabular-nums text-muted-foreground">
                                {Math.min(100, Math.round(fill * 100))}%
                              </span>
                            )}
                          </div>
                          {capacity !== null && (
                            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                              <div
                                className={cn(
                                  "h-full rounded-full",
                                  fill >= 1
                                    ? "bg-destructive"
                                    : fill > 0
                                      ? "bg-warning"
                                      : "bg-success",
                                )}
                                style={{ width: `${Math.min(100, Math.round(fill * 100))}%` }}
                              />
                            </div>
                          )}
                          {section.teachers.length > 0 ? (
                            <p className="mt-2 truncate text-xs text-muted-foreground">
                              {section.teachers
                                .map((teacher) => `${teacher.first_name} ${teacher.last_name}`)
                                .join(", ")}
                            </p>
                          ) : (
                            <StatusBadge tone="warning" className="mt-2">
                              {tInstitutional("unassigned")}
                            </StatusBadge>
                          )}
                          {section.program_offerings.length > 0 && (
                            <p className="mt-2 truncate text-xs text-muted-foreground">
                              {t("programOfferings")}:{" "}
                              {section.program_offerings.map((offering) => offering.name).join(", ")}
                            </p>
                          )}
                          {(canManage.classes || canManage.teachers) && (
                            <div className="mt-2 flex flex-wrap justify-end gap-1">
                              {canManage.teachers && (
                                <TeacherAssignmentsDialog
                                  section={section}
                                  onSaved={refetch}
                                />
                              )}
                              {canManage.classes && (
                                <>
                                  <SectionOfferingsDialog
                                    section={section}
                                    offerings={data?.programOfferings ?? []}
                                    onSaved={refetch}
                                  />
                                  <ClassHistoryDialog
                                    classId={section.id}
                                    classLabel={sectionLabel(section)}
                                  />
                                  <ClassSectionDialog
                                    section={section}
                                    courses={data?.courses ?? []}
                                    periods={data?.periods ?? []}
                                    onSaved={refetch}
                                  />
                                </>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="lg:col-span-2">
              <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
                <div>
                  <CardTitle className="text-base">{t("timetable")}</CardTitle>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("subtitle")}
                  </p>
                </div>
                {isConfigured && canManage.timetable && (
                  <TimetableEntryDialog
                    sections={data?.classes ?? []}
                    classrooms={data?.classrooms ?? []}
                    onSaved={refetch}
                  />
                )}
              </CardHeader>
              <CardContent>
                {!isConfigured ? (
                  <p className="text-sm text-muted-foreground">
                    {t("sourceOnlyTimetableHint")}
                  </p>
                ) : (data?.timetable.length ?? 0) === 0 ? (
                  <EmptyState title={t("noTimetable")} />
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-border/80">
                    <div className="min-w-[76rem]">
                      <div className="grid grid-cols-[4.25rem_repeat(7,minmax(0,1fr))] border-b border-border/80 bg-muted/50">
                        <div className="border-e border-border/70 px-2 py-2.5 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                          {tCommon("labels.time")}
                        </div>
                        {WEEKDAY_KEYS.map((dayKey, dayIndex) => (
                          <div
                            key={dayKey}
                            className={cn(
                              "border-e border-border/70 px-2 py-2.5 text-center text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground last:border-e-0",
                              dayIndex === todayIndex && "bg-primary/[0.055] text-primary",
                            )}
                          >
                            {t(`daysShort.${dayKey}`)}
                            {dayIndex === todayIndex && (
                              <span className="mt-0.5 block text-[8px] normal-case tracking-normal">
                                {t("today")}
                              </span>
                            )}
                          </div>
                        ))}
                      </div>

                      {timetableSlots.map((slot) => (
                        <div
                          key={slot}
                          className="grid grid-cols-[4.25rem_repeat(7,minmax(0,1fr))] border-b border-border/70 last:border-b-0"
                        >
                          <div className="border-e border-border/70 bg-muted/20 px-2 py-3 text-[11px] font-semibold tabular-nums text-muted-foreground">
                            {slot}
                          </div>
                          {WEEKDAY_KEYS.map((dayKey, dayIndex) => {
                            const entries = (data?.timetable ?? [])
                              .filter(
                                (entry) =>
                                  entry.day_of_week === dayIndex &&
                                  entry.start_time.slice(0, 5) === slot,
                              )
                              .sort((a, b) => a.start_time.localeCompare(b.start_time));

                            return (
                              <div
                                key={`${slot}-${dayKey}`}
                                className={cn(
                                  "min-h-24 border-e border-border/70 p-1.5 last:border-e-0",
                                  dayIndex === todayIndex && "bg-primary/[0.025]",
                                )}
                              >
                                <div className="space-y-1.5">
                                  {entries.length === 0 ? (
                                    <span className="block h-full min-h-20 rounded-md bg-muted/15" aria-hidden="true" />
                                  ) : (
                                    entries.map((entry) => (
                                      <div
                                        key={entry.id}
                                        className={cn(
                                          "rounded-md border border-s-[2px] border-border/70 p-2",
                                          courseAccent(entry.course_code ?? entry.id),
                                        )}
                                      >
                                        <p className="truncate font-mono text-[10px] font-semibold text-primary">
                                          {timetableLabel(entry)}
                                        </p>
                                        <p className="mt-1 text-[10px] tabular-nums text-muted-foreground" dir="ltr">
                                          {entry.start_time.slice(0, 5)}–{entry.end_time.slice(0, 5)}
                                        </p>
                                        {entry.classroom_name && (
                                          <p className="mt-1 truncate text-[10px] text-muted-foreground">
                                            {t("roomNumber", { number: entry.classroom_name })}
                                          </p>
                                        )}
                                        {entry.teacher_names.length > 0 && (
                                          <p className="mt-0.5 truncate text-[10px] text-muted-foreground">
                                            {entry.teacher_names.join(", ")}
                                          </p>
                                        )}
                                        {canManage.timetable && (
                                          <div className="mt-1 flex justify-end gap-0.5">
                                            <TimetableEntryDialog
                                              entry={entry}
                                              sections={data?.classes ?? []}
                                              classrooms={data?.classrooms ?? []}
                                              onSaved={refetch}
                                            />
                                            <RemoveTimetableEntryButton
                                              entry={entry}
                                              onSaved={refetch}
                                            />
                                          </div>
                                        )}
                                      </div>
                                    ))
                                  )}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </AppShell>
  );
}
