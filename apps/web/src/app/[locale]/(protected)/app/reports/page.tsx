"use client";

import { useCallback } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useAuth } from "@/lib/auth-context";
import { reportApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatCard, StatGrid } from "@/components/ui/stat-card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import type { CountItem, OperationsReport } from "@/types/platform";

/** A breakdown table. Renders nothing when the backend has no rows for it. */
function Breakdown({
  title,
  items,
}: {
  title: string;
  items: CountItem[];
}) {
  const tCommon = useTranslations("common");
  const t = useTranslations("reports");

  if (items.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{t("empty")}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <caption className="sr-only">{title}</caption>
          <thead>
            <tr className="border-b text-xs uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="px-4 py-2 text-start font-medium">
                {tCommon("labels.name")}
              </th>
              <th scope="col" className="px-4 py-2 text-end font-medium">
                {tCommon("labels.count")}
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={`${item.label}-${item.sublabel ?? ""}`} className="border-b last:border-0">
                <td className="px-4 py-2">
                  {item.label}
                  {item.sublabel && (
                    <span className="block text-xs text-muted-foreground">
                      {item.sublabel}
                    </span>
                  )}
                </td>
                <td className="px-4 py-2 text-end tabular-nums">{item.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

export default function ReportsPage() {
  const t = useTranslations("reports");
  const tCommon = useTranslations("common");
  const tImmigration = useTranslations("immigration");
  const locale = useLocale();
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();

  const fetchReport = useCallback(() => reportApi.overview(), []);
  const { data, loading, error, refetch } = useApi<OperationsReport>(
    fetchReport,
    [],
    "operational reports",
  );

  const localized = localizeError(error);

  if (!hasPermission("reports.view")) {
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

      {loading ? (
        <LoadingState />
      ) : error ? (
        error.kind === "forbidden" ? (
          <EmptyState title={t("noPermission")} />
        ) : (
          <ErrorState
            title={localized.message}
            hint={localized.hint}
            onRetry={refetch}
          />
        )
      ) : !data ? (
        <EmptyState title={t("empty")} />
      ) : (
        <>
          <StatGrid>
            <StatCard
              label={t("metrics.totalStudents")}
              value={data.students.total}
            />
            <StatCard
              label={t("metrics.activeStudents")}
              value={data.students.active}
              tone="success"
            />
            <StatCard
              label={t("metrics.housedOnCampus")}
              value={data.housing.students_housed}
            />
            <StatCard
              label={t("metrics.availableBeds")}
              value={data.housing.available_beds}
              tone={data.housing.available_beds > 0 ? "success" : "danger"}
            />
            <StatCard
              label={t("metrics.occupiedBeds")}
              value={data.housing.occupied_beds}
            />
          </StatGrid>

          <Tabs defaultValue="students">
            <TabsList>
              <TabsTrigger value="students">{t("students")}</TabsTrigger>
              <TabsTrigger value="immigration">{t("immigration")}</TabsTrigger>
              <TabsTrigger value="housing">{t("housing")}</TabsTrigger>
              <TabsTrigger value="academics">{t("academics")}</TabsTrigger>
            </TabsList>

            <TabsContent value="students" className="space-y-6">
              <StatGrid>
                <StatCard
                  label={t("metrics.totalStudents")}
                  value={data.students.total}
                />
                <StatCard
                  label={t("metrics.activeStudents")}
                  value={data.students.active}
                  tone="success"
                />
                <StatCard
                  label={t("metrics.inactiveStudents")}
                  value={data.students.inactive}
                />
                <StatCard
                  label={t("metrics.graduated")}
                  value={data.students.graduated}
                />
                <StatCard
                  label={t("metrics.withdrawn")}
                  value={data.students.withdrawn}
                />
              </StatGrid>
              <div className="grid gap-6 lg:grid-cols-2">
                <Breakdown
                  title={t("sections.studentsByStatus")}
                  items={[
                    {
                      label: t("metrics.activeStudents"),
                      count: data.students.active,
                    },
                    {
                      label: t("metrics.inactiveStudents"),
                      count: data.students.inactive,
                    },
                    {
                      label: t("metrics.graduated"),
                      count: data.students.graduated,
                    },
                    {
                      label: t("metrics.withdrawn"),
                      count: data.students.withdrawn,
                    },
                    {
                      label: t("metrics.suspended"),
                      count: data.students.suspended,
                    },
                  ]}
                />
                <Breakdown
                  title={t("sections.studentsByNationality")}
                  items={data.students.by_nationality ?? []}
                />
                <Breakdown
                  title={t("sections.studentsByProgram")}
                  items={data.students.by_program ?? []}
                />
              </div>
            </TabsContent>

            <TabsContent value="immigration" className="space-y-6">
              <StatGrid>
                <StatCard
                  label={tCommon("labels.total")}
                  value={data.immigration.total_students}
                />
                <StatCard
                  label={tCommon("states.active")}
                  value={data.immigration.valid}
                  tone="success"
                />
                <StatCard
                  label={t("metrics.expiring30")}
                  value={data.immigration.expiring_30_days}
                  tone="warning"
                />
                <StatCard
                  label={t("metrics.expiring90")}
                  value={data.immigration.expiring_90_days}
                  tone="warning"
                />
                <StatCard
                  label={t("metrics.missingInformation")}
                  value={data.immigration.missing_information}
                  tone={data.immigration.missing_information > 0 ? "danger" : "default"}
                />
                <StatCard
                  label={t("metrics.namedCohorts")}
                  value={data.immigration.in_named_cohorts}
                  tone="success"
                />
                <StatCard
                  label={t("metrics.untrusted")}
                  value={data.immigration.untrusted_students}
                  tone={data.immigration.untrusted_students > 0 ? "warning" : "default"}
                />
              </StatGrid>
              <div className="grid gap-6 lg:grid-cols-2">
                <Breakdown
                  title={t("sections.immigrationExpiry")}
                  items={[
                    { label: tCommon("states.active"), count: data.immigration.valid },
                    {
                      label: t("metrics.expiring30"),
                      count: data.immigration.expiring_30_days,
                    },
                    {
                      label: t("metrics.expiring90"),
                      count: data.immigration.expiring_90_days,
                    },
                    {
                      label: t("metrics.expired"),
                      count: data.immigration.expired,
                    },
                  ]}
                />
                <Breakdown
                  title={tCommon("labels.type")}
                  items={(data.immigration.by_document_type ?? []).map((item) => ({
                    ...item,
                    label:
                      item.label === "passport"
                        ? tImmigration("passport")
                        : item.label === "visa"
                          ? tImmigration("visa")
                          : item.label === "residence_permit"
                            ? tImmigration("residencePermit")
                            : item.label,
                    sublabel:
                      item.sublabel === "expiring_90"
                        ? t("metrics.expiring90")
                        : item.sublabel,
                  }))}
                />
                <Breakdown
                  title={t("sections.byOriginalIntake")}
                  items={data.immigration.by_original_intake ?? []}
                />
                <Breakdown
                  title={t("sections.untrustedReasons")}
                  items={data.immigration.untrusted_by_reason ?? []}
                />
              </div>
            </TabsContent>

            <TabsContent value="housing" className="space-y-6">
              <StatGrid>
                <StatCard
                  label={t("metrics.totalCapacity")}
                  value={data.housing.total_beds}
                />
                <StatCard
                  label={t("metrics.occupiedBeds")}
                  value={data.housing.occupied_beds}
                />
                <StatCard
                  label={t("metrics.availableBeds")}
                  value={data.housing.available_beds}
                  tone="success"
                />
                <StatCard
                  label={t("metrics.fullRooms")}
                  value={data.housing.rooms_full}
                  tone="danger"
                />
                <StatCard
                  label={t("metrics.outOfServiceRooms")}
                  value={data.housing.rooms_out_of_service}
                />
              </StatGrid>
              <div className="grid gap-6 lg:grid-cols-2">
                <Breakdown
                  title={t("sections.housingOccupancy")}
                  items={[
                    {
                      label: t("metrics.roomsAvailable"),
                      count: data.housing.rooms_available,
                    },
                    {
                      label: t("metrics.roomsPartial"),
                      count: data.housing.rooms_partial,
                    },
                    {
                      label: t("metrics.fullRooms"),
                      count: data.housing.rooms_full,
                    },
                    {
                      label: t("metrics.outOfServiceRooms"),
                      count: data.housing.rooms_out_of_service,
                    },
                  ]}
                />
                <Breakdown
                  title={t("sections.housingByBuilding")}
                  items={[
                    {
                      label: t("metrics.housedOnCampus"),
                      count: data.housing.students_housed,
                    },
                    {
                      label: t("metrics.offCampus"),
                      count: data.housing.students_not_housed,
                    },
                  ]}
                />
              </div>
            </TabsContent>

            <TabsContent value="academics" className="space-y-6">
              <StatGrid>
                <StatCard
                  label={t("metrics.totalEnrollments")}
                  value={data.academics.total_enrollments}
                  hint={t("sections.enrollmentByPeriod")}
                />
                <StatCard
                  label={tCommon("labels.count")}
                  value={data.academics.total_classes}
                  hint={t("academics")}
                />
                <StatCard
                  label={tCommon("labels.count")}
                  value={data.academics.total_courses}
                />
                <StatCard
                  label={t("sections.teacherAssignments")}
                  value={data.academics.total_teacher_assignments}
                />
                <StatCard
                  label={tCommon("states.active")}
                  value={data.academics.active_periods}
                  tone="success"
                />
              </StatGrid>
              <div className="grid gap-6 lg:grid-cols-2">
                <Breakdown
                  title={t("sections.enrollmentByPeriod")}
                  items={data.academics.enrollments_by_period ?? []}
                />
                <Breakdown
                  title={t("sections.teacherAssignments")}
                  items={data.academics.classes_by_status ?? []}
                />
              </div>
            </TabsContent>
          </Tabs>

          <p className="mt-6 text-xs text-muted-foreground">
            {t("generatedAt", {
              date: new Date().toLocaleString(locale),
            })}
          </p>
        </>
      )}
    </AppShell>
  );
}
