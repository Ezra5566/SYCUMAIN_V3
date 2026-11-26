"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { CalendarDays, Clock3, GraduationCap, Info, Users } from "lucide-react";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterSelect } from "@/components/ui/filter-select";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { WeeklyTimetable } from "@/components/academics/weekly-timetable";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { getInstitutionalTimetable, listPeriods, listProgramOfferings } from "@/lib/academic-api";
import type { AcademicPeriod } from "@/types/academic";

/**
 * The shared institutional timetable.
 *
 * Unlike a student's own timetable, this page is not about the viewer. It opens
 * a period and a program offering and shows every section scheduled for that
 * offering, so a student can read the cohort's week — including courses they
 * are not enrolled in. The personalised view lives in the student profile and
 * is untouched by this page.
 */
export default function InstitutionalTimetablePage() {
  const t = useTranslations("institutionalTimetable");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const periodsApi = useApi(() => listPeriods(1, 100), [], "academic periods");
  const periods: AcademicPeriod[] = useMemo(
    () => periodsApi.data?.items ?? [],
    [periodsApi.data],
  );
  const [periodId, setPeriodId] = useState("");

  // Default to the period the institution is currently running, not to
  // whatever happens to be first in the list.
  useEffect(() => {
    if (periodId || periods.length === 0) return;
    const active = periods.find((period) => period.status === "ACTIVE");
    setPeriodId((active ?? periods[0]).id);
  }, [periodId, periods]);

  const offeringsApi = useApi(
    () =>
      periodId
        ? listProgramOfferings(periodId, undefined, 1, 100)
        : Promise.resolve(null),
    [periodId],
    "program offerings",
  );
  const offerings = useMemo(
    () => offeringsApi.data?.items ?? [],
    [offeringsApi.data],
  );
  const [offeringId, setOfferingId] = useState("");

  useEffect(() => {
    setOfferingId("");
  }, [periodId]);

  useEffect(() => {
    if (offeringId || offerings.length === 0) return;
    setOfferingId(offerings[0].id);
  }, [offeringId, offerings]);

  const timetableApi = useApi(
    () =>
      periodId && offeringId
        ? getInstitutionalTimetable(offeringId, periodId)
        : Promise.resolve(null),
    [periodId, offeringId],
    "institutional timetable",
  );

  const data = timetableApi.data;
  const readiness = data?.readiness;
  const isIncomplete = readiness?.status === "INCOMPLETE";
  const selectedPeriod = periods.find((period) => period.id === periodId);
  const localized = localizeError(timetableApi.error);

  const readinessKey = readiness?.message_code ?? "TIMETABLE_NOT_SCHEDULED";
  const readinessMessage = t.has(`readiness.${readinessKey}`)
    ? t(`readiness.${readinessKey}`)
    : t("readiness.generic");

  const loading =
    periodsApi.loading ||
    offeringsApi.loading ||
    (timetableApi.loading && !data);

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

      <div className="mb-5 flex flex-col gap-3 rounded-xl border border-border/80 bg-muted/20 p-3 sm:flex-row sm:items-end">
        <FilterSelect
          label={t("periodLabel")}
          value={periodId}
          showLabel
          className="flex-1"
          onChange={setPeriodId}
          options={periods.map((period) => ({
            value: period.id,
            label: period.name_zh
              ? `${period.name} · ${period.name_zh}`
              : period.name,
          }))}
        />
        <FilterSelect
          label={t("offeringLabel")}
          value={offeringId}
          showLabel
          className="flex-1"
          onChange={setOfferingId}
          options={offerings.map((offering) => ({
            value: offering.id,
            label: offering.name,
          }))}
        />
        <p className="text-xs text-muted-foreground sm:max-w-[16rem]">{t("sharedHint")}</p>
      </div>

      {periodsApi.error ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={localizeError(periodsApi.error).message}
              hint={localizeError(periodsApi.error).hint}
              onRetry={periodsApi.refetch}
            />
          </CardContent>
        </Card>
      ) : periodsApi.loading ? (
        <LoadingState />
      ) : periods.length === 0 ? (
        <EmptyState title={t("noPeriods")} message={t("noPeriodsHint")} />
      ) : offeringsApi.loading ? (
        <LoadingState />
      ) : offerings.length === 0 ? (
        <Card>
          <CardContent className="pt-6">
            <EmptyState title={t("noOfferings")} message={t("noOfferingsHint")} />
          </CardContent>
        </Card>
      ) : timetableApi.error ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={localized.message}
              hint={localized.hint}
              onRetry={timetableApi.refetch}
            />
          </CardContent>
        </Card>
      ) : loading ? (
        <LoadingState />
      ) : (
        <div className="space-y-4">
          {isIncomplete && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-sm text-warning"
            >
              <Info className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <div className="min-w-0">
                <p>{readinessMessage}</p>
                {readiness && readiness.sections_scheduled > 0 && (
                  <p className="mt-0.5 text-xs opacity-90">
                    {t("scheduledOf", {
                      scheduled: readiness.sections_scheduled,
                      total: readiness.sections_total,
                    })}
                  </p>
                )}
              </div>
            </div>
          )}

          {selectedPeriod && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-border/80 bg-background px-4 py-3">
                <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("period")}
                </p>
                <p className="mt-1 truncate text-sm font-semibold">{selectedPeriod.name}</p>
                <StatusBadge
                  className="mt-1.5"
                  tone={selectedPeriod.status === "ACTIVE" ? "success" : "neutral"}
                >
                  {t(`periodStatus.${selectedPeriod.status}`)}
                </StatusBadge>
              </div>
              <div className="rounded-xl border border-border/80 bg-background px-4 py-3">
                <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("sessions")}
                </p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">
                  {readiness?.sessions ?? 0}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t("sectionsCount", {
                    scheduled: readiness?.sections_scheduled ?? 0,
                    total: readiness?.sections_total ?? 0,
                  })}
                </p>
              </div>
              <div className="rounded-xl border border-border/80 bg-background px-4 py-3">
                <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <GraduationCap className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("courses")}
                </p>
                <p className="mt-1 text-2xl font-semibold tabular-nums">
                  {readiness?.courses_scheduled ?? 0}/{readiness?.courses_total ?? 0}
                </p>
                <p className="text-xs text-muted-foreground">{t("coursesScheduled")}</p>
              </div>
            </div>
          )}

          <Card>
            <CardHeader className="flex-row items-center justify-between gap-2 pb-2">
              <CardTitle className="text-base">{t("weeklyTitle")}</CardTitle>
              {data && (
                <span className="truncate text-xs text-muted-foreground">
                  {data.program_offering.name}
                </span>
              )}
            </CardHeader>
            <CardContent>
              {data && data.entries.length > 0 ? (
                <WeeklyTimetable entries={data.entries} />
              ) : (
                <EmptyState title={t("noSessions")} message={t("noSessionsHint")} />
              )}
            </CardContent>
          </Card>

          {data && data.sections.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{t("sectionListTitle")}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="divide-y divide-border/70">
                  {data.sections.map((section) => (
                    <li
                      key={section.id}
                      className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm"
                    >
                      <div className="min-w-0">
                        <p className="truncate font-medium">
                          {section.course_code ? `${section.course_code} · ` : ""}
                          {section.course_name ?? section.source_label ?? t("unnamedSection")}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {section.section_code ?? section.source_label ?? ""}
                          {section.teachers.length > 0 && (
                            <>
                              {" · "}
                              <Users className="inline h-3 w-3" aria-hidden="true" />{" "}
                              {section.teachers.join(", ")}
                            </>
                          )}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs tabular-nums text-muted-foreground">
                          {t("sessionCount", { count: section.session_count })}
                        </span>
                        <StatusBadge
                          tone={section.session_count > 0 ? "success" : "warning"}
                        >
                          {section.session_count > 0 ? t("scheduled") : t("notScheduled")}
                        </StatusBadge>
                      </div>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {readiness && readiness.issues.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">{t("issuesTitle")}</CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1.5 text-sm">
                  {readiness.issues.map((issue) => (
                    <li key={issue.code} className="flex items-center justify-between gap-2">
                      <span className="text-muted-foreground">
                        {t.has(`issues.${issue.code}`)
                          ? t(`issues.${issue.code}`)
                          : issue.code}
                      </span>
                      <span className="tabular-nums">{issue.count}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </AppShell>
  );
}
