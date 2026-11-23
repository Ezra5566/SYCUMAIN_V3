"use client";

import { useCallback, useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useParams, useSearchParams } from "next/navigation";
import { AlertTriangle, ChevronRight, GraduationCap, Globe2, Hash, Home, Mail, MapPin, Phone, ShieldCheck } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth-context";
import { AppShell } from "@/components/layout/app-shell";
import { studentApi } from "@/lib/student-api";
import { getStudentHousing } from "@/lib/housing-api";
import {
  getImmigrationHistory,
  getStudentImmigration,
  getStudentImmigrationCohort,
} from "@/lib/immigration-api";
import { getStudentAcademic, listPeriods } from "@/lib/academic-api";
import { sectionLabel } from "@/lib/academic-display";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { DetailList } from "@/components/ui/detail-list";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DocumentsTab } from "@/components/students/documents-tab";
import { WeeklyTimetable } from "@/components/academics/weekly-timetable";
import { ImmigrationActions } from "@/components/immigration/immigration-actions";
import { ProfilePhoto } from "@/components/students/profile-photo";
import { MajorSelection } from "@/components/students/major-selection";
import { PlacementPanel } from "@/components/students/placement-panel";
import { ProgrammeChangePanel } from "@/components/students/programme-change-panel";
import { EditStudentDialog } from "@/components/students/edit-student-dialog";
import { SelfServiceDialog } from "@/components/students/self-service-dialog";
import type { StudentHousingResponse } from "@/types/housing";
import type {
  ImmigrationCohort,
  ImmigrationProfile,
  ImmigrationProfileVersion,
} from "@/types/immigration";
import type { StudentAcademicOverview, TimetableEntry } from "@/types/academic";
import type { StudentDetail } from "@/types/student";

function QuickFact({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex min-w-0 items-start gap-2.5 rounded-lg border border-border/70 bg-muted/25 p-3">
      <span className="mt-0.5 text-muted-foreground" aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
          {label}
        </p>
        <p className="mt-0.5 truncate text-[13px] font-medium">{value}</p>
      </div>
    </div>
  );
}

function ProfileSignal({
  icon,
  label,
  value,
  meta,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  meta: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex min-w-0 items-center gap-3 rounded-xl border border-border/80 bg-card p-4 text-start shadow-card transition-[border-color,box-shadow] hover:border-primary/25 hover:shadow-raised focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/[0.08] text-primary">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          {label}
        </span>
        <span className="mt-0.5 block truncate text-[13px] font-semibold">{value}</span>
        <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">{meta}</span>
      </span>
      <ChevronRight
        className="h-4 w-4 shrink-0 text-muted-foreground/60 transition-transform group-hover:translate-x-0.5 rtl:rotate-180 rtl:group-hover:-translate-x-0.5"
        aria-hidden="true"
      />
    </button>
  );
}

function ExpiryBlock({
  title,
  status,
  days,
  date,
}: {
  title: string;
  status: string | null;
  days: number | null;
  date: string | null;
}) {
  const t = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const statusLabel = useStatusLabel();

  const tone = toneForStatus(status);

  return (
    <div
      className={cn(
        "rounded-xl border border-border/80 bg-card p-4 shadow-card border-s-[3px]",
        tone === "danger"
          ? "border-s-destructive"
          : tone === "warning"
            ? "border-s-warning"
            : tone === "success"
              ? "border-s-success"
              : "border-s-primary/40",
      )}
    >
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <StatusBadge tone={tone}>
          {status
            ? statusLabel(status, "immigration.statusLabel")
            : tCommon("states.notSet")}
        </StatusBadge>
      </div>
      <dl className="space-y-1 text-sm">
        <div className="flex justify-between gap-4">
          <dt className="text-muted-foreground">{t("expiryDate")}</dt>
          <dd className="tabular-nums">
            {date ? format.dateTime(new Date(date), { dateStyle: "medium" }) : "—"}
          </dd>
        </div>
        {days !== null && (
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">{t("daysRemainingLabel")}</dt>
            <dd className="tabular-nums">
              {days >= 0
                ? t("daysRemaining", { count: days })
                : t("daysExpired", { count: Math.abs(days) })}
            </dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function AcademicTab({ academic }: { academic: StudentAcademicOverview | null }) {
  const t = useTranslations("academics");
  const tCommon = useTranslations("common");

  if (!academic) {
    return <EmptyState title={t("noClasses")} message={t("noEnrollment")} />;
  }

  return (
    <div className="space-y-6">
      <DetailList
        columns={3}
        items={[
          { label: t("program"), value: academic.program?.name ?? t("noProgram") },
          {
            label: t("programOffering"),
            value: academic.program_offering?.name ?? t("noProgram"),
          },
          { label: t("major"), value: academic.major?.name ?? t("noMajor") },
          {
            label: t("currentPeriod"),
            value: academic.current_period?.name ?? tCommon("states.notSet"),
          },
          ...(academic.selected_period &&
          academic.selected_period.id !== academic.current_period?.id
            ? [
                {
                  label: t("selectedPeriod"),
                  value: academic.selected_period.name,
                },
              ]
            : []),
        ]}
      />
      <div>
        <h3 className="mb-3 text-sm font-semibold">
          {t("enrolledClasses")} ({academic.enrolled_classes.length})
        </h3>
        {academic.enrolled_classes.length === 0 ? (
          <EmptyState title={t("enrolledClasses")} message={t("noEnrollment")} />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {academic.enrolled_classes.map((cls) => (
              <li key={cls.id} className="rounded-xl border border-border/80 bg-muted/20 p-3.5">
                <p className="font-mono text-xs text-muted-foreground">
                  {sectionLabel(cls)}
                </p>
                <p className="text-sm font-medium">
                  {cls.course_name ?? tCommon("states.notSet")}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {cls.capacity === null
                    ? t("capacityNotProvided")
                    : t("capacityCount", {
                        enrolled: cls.enrolled_count,
                        capacity: cls.capacity,
                      })}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function TimetableTab({ entries }: { entries: TimetableEntry[] }) {
  const t = useTranslations("academics");

  if (entries.length === 0) {
    return <EmptyState title={t("timetable")} message={t("noTimetable")} />;
  }

  return <WeeklyTimetable entries={entries} />;
}

function HousingTab({ housing }: { housing: StudentHousingResponse | null }) {
  const t = useTranslations("housing");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const statusLabel = useStatusLabel();

  const assignment = housing?.has_assignment ? housing.assignment : null;

  if (!assignment) {
    return <EmptyState title={t("noAssignment")} message={t("offCampus")} />;
  }

  return (
    <div className="space-y-4">
      <DetailList
        columns={2}
        items={[
          { label: t("building"), value: assignment.building_name ?? "—" },
          { label: t("floor"), value: assignment.floor_number ?? "—" },
          { label: t("room"), value: assignment.room_number ?? "—" },
          { label: t("bed"), value: assignment.bed_label ?? "—" },
          {
            label: tCommon("labels.status"),
            value: (
              <StatusBadge tone={toneForStatus(assignment.status)}>
                {statusLabel(assignment.status, "housing.assignmentStatus")}
              </StatusBadge>
            ),
          },
          {
            label: t("startDate"),
            value: assignment.start_date
              ? format.dateTime(new Date(assignment.start_date), { dateStyle: "medium" })
              : "—",
          },
        ]}
      />
      <Button asChild variant="outline" size="sm">
        <Link href="/app/housing">{t("title")}</Link>
      </Button>
    </div>
  );
}

function CohortBanner({ cohort }: { cohort: ImmigrationCohort | null }) {
  const t = useTranslations("immigration");
  const format = useFormatter();
  if (!cohort) return null;

  const verified = cohort.verification_status === "VERIFIED";
  const date = (value: string | null | undefined) =>
    value
      ? format.dateTime(new Date(value), {
          dateStyle: "medium",
          timeStyle: "short",
        })
      : "—";

  return (
    <div
      className={cn(
        "rounded-xl border p-4",
        verified
          ? "border-success/25 bg-success-soft/40"
          : "border-warning/30 bg-warning-soft/40",
      )}
    >
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
            verified ? "bg-success/15 text-success" : "bg-warning/15 text-warning",
          )}
          aria-hidden="true"
        >
          {verified ? (
            <ShieldCheck className="h-4 w-4" />
          ) : (
            <AlertTriangle className="h-4 w-4" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">{t("cohort.studentTitle")}</p>
            <Badge
              variant="outline"
              className={
                verified
                  ? "border-success/30 bg-success-soft text-success"
                  : "border-warning/30 bg-warning-soft text-warning"
              }
            >
              {t(`cohort.trust.${cohort.verification_status}`)}
            </Badge>
          </div>
          <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">{t("cohort.originalIntake")}:</dt>
              <dd className="font-medium">
                {cohort.original_admission_intake_name ?? t("cohort.none")}
              </dd>
            </div>
            <div className="flex gap-1.5">
              <dt className="text-muted-foreground">{t("cohort.placementIntake")}:</dt>
              <dd className="font-medium">
                {cohort.placement_intake_name ?? t("cohort.none")}
              </dd>
            </div>
            {cohort.last_confirmer_name && (
              <div className="flex gap-1.5 sm:col-span-2">
                <dt className="text-muted-foreground">{t("cohort.lastConfirmedBy")}:</dt>
                <dd className="font-medium">
                  {cohort.last_confirmer_name} · {date(cohort.last_confirmed_at)}
                </dd>
              </div>
            )}
            {!verified && cohort.verified_at && (
              <div className="flex gap-1.5 sm:col-span-2">
                <dt className="text-muted-foreground">{t("cohort.lastVerifiedAt")}:</dt>
                <dd className="font-medium">{date(cohort.verified_at)}</dd>
              </div>
            )}
            {cohort.revoked_at && (
              <div className="flex gap-1.5 sm:col-span-2">
                <dt className="text-muted-foreground">{t("cohort.revokedBy")}:</dt>
                <dd className="font-medium">
                  {cohort.revoked_by_name ?? t("cohort.none")} · {date(cohort.revoked_at)}
                  {cohort.revocation_reason ? ` — ${cohort.revocation_reason}` : ""}
                </dd>
              </div>
            )}
          </dl>
          {!verified && (
            <p className="mt-2 text-xs text-muted-foreground">
              {cohort.verification_status === "NO_ADMISSION"
                ? t("cohort.noAdmissionHint")
                : cohort.verification_status === "DISPUTED"
                  ? t("cohort.disputedHint")
                  : t("cohort.untrustedHint")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function ImmigrationTab({
  profile,
  studentId,
  isOwnRecord,
  canEdit,
  onChanged,
}: {
  profile: ImmigrationProfile | null;
  studentId: string;
  isOwnRecord: boolean;
  canEdit: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const t = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const { hasPermission } = useAuth();
  const canViewHistory = hasPermission("immigration.view_all");
  const historyStudentId = profile?.student_id;
  const fetchHistory = useCallback(
    () =>
      canViewHistory && historyStudentId
        ? getImmigrationHistory(historyStudentId)
        : Promise.resolve([]),
    [canViewHistory, historyStudentId],
  );
  const { data: history } = useApi<ImmigrationProfileVersion[]>(
    fetchHistory,
    [canViewHistory, historyStudentId],
    "immigration history",
  );
  const fetchCohort = useCallback(
    () => getStudentImmigrationCohort(studentId),
    [studentId],
  );
  const { data: cohort } = useApi<ImmigrationCohort>(
    fetchCohort,
    [studentId],
    "immigration cohort",
  );

  if (!profile) {
    return (
      <div className="space-y-6">
        <CohortBanner cohort={cohort} />
        <EmptyState title={t("noProfile")} message={t("noProfileHint")} />
      </div>
    );
  }

  const historyValue = (value: unknown) =>
    value === null || value === undefined || value === "" ? "—" : String(value);

  const dateValue = (value?: string | null) =>
    value ? format.dateTime(new Date(value), { dateStyle: "medium" }) : "—";

  return (
    <div className="space-y-6">
      <CohortBanner cohort={cohort} />
      <ImmigrationActions
        profile={profile}
        studentId={studentId}
        isOwnRecord={isOwnRecord}
        canEdit={canEdit}
        onChanged={onChanged}
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <ExpiryBlock
          title={t("passport")}
          status={profile.passport_status ?? null}
          days={profile.passport_days_remaining ?? null}
          date={profile.passport_expiry_date ?? null}
        />
        <ExpiryBlock
          title={t("visa")}
          status={profile.visa_status ?? null}
          days={profile.visa_days_remaining ?? null}
          date={profile.visa_expiry_date ?? null}
        />
        <ExpiryBlock
          title={t("residencePermit")}
          status={profile.residence_permit_status ?? null}
          days={profile.residence_permit_days_remaining ?? null}
          date={profile.residence_permit_expiry_date ?? null}
        />
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <h3 className="mb-3 text-sm font-semibold">{t("passport")}</h3>
          <DetailList
            columns={1}
            items={[
              { label: t("passportNumber"), value: profile.passport_number ?? "—" },
              {
                label: t("issuingCountry"),
                value: profile.passport_issuing_country ?? "—",
              },
              { label: t("issueDate"), value: dateValue(profile.passport_issue_date) },
              {
                label: t("nameOnDocument"),
                value: profile.passport_name_as_shown ?? "—",
              },
            ]}
          />
        </div>

        <div>
          <h3 className="mb-3 text-sm font-semibold">{t("visa")}</h3>
          <DetailList
            columns={1}
            items={[
              { label: t("visaType"), value: profile.visa_type ?? "—" },
              { label: t("visaNumber"), value: profile.visa_number ?? "—" },
              { label: t("issueDate"), value: dateValue(profile.visa_issue_date) },
              {
                label: t("issuingAuthority"),
                value: profile.visa_issuing_authority ?? "—",
              },
            ]}
          />
        </div>

        <div>
          <h3 className="mb-3 text-sm font-semibold">{t("residencePermit")}</h3>
          <DetailList
            columns={1}
            items={[
              {
                label: t("permitNumber"),
                value: profile.residence_permit_number ?? "—",
              },
              {
                label: t("issueDate"),
                value: dateValue(profile.residence_permit_issue_date),
              },
              {
                label: t("issuingAuthority"),
                value: profile.residence_permit_issuing_authority ?? "—",
              },
            ]}
          />
        </div>

        <div>
          <h3 className="mb-3 text-sm font-semibold">{t("documents")}</h3>
          {profile.documents && profile.documents.length > 0 ? (
            <ul className="space-y-2">
              {profile.documents.map((doc) => (
                <li
                  key={doc.id}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
                >
                  <span className="truncate text-sm">{doc.original_filename}</span>
                  <Badge variant="outline" className="shrink-0 text-xs">
                    {t(`documentTypes.${doc.document_type}`)}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              {tCommon("counts.documents", { count: 0 })}
            </p>
          )}
        </div>
      </div>

      {canViewHistory && (
        <section aria-labelledby="immigration-history-heading">
          <h3
            id="immigration-history-heading"
            className="mb-1 text-sm font-semibold"
          >
            {t("history")}
          </h3>
          <p className="mb-3 text-xs text-muted-foreground">{t("historyHint")}</p>
          {!history || history.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("noHistory")}</p>
          ) : (
            <ol className="relative ms-1 space-y-3 border-s border-border/80 ps-5">
              {history.map((version) => (
                <li key={version.id} className="relative rounded-xl border border-border/80 bg-card p-3.5 shadow-card">
                  <span
                    className="absolute -start-[1.63rem] top-4 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary"
                    aria-hidden="true"
                  />
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">
                      #{version.version_number}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {format.dateTime(new Date(version.changed_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("recordedBy", { name: version.changed_by_name ?? "—" })}
                  </p>
                  {version.change_reason && (
                    <p className="mt-2 text-sm">
                      <span className="text-muted-foreground">{t("reason")}: </span>
                      {version.change_reason}
                    </p>
                  )}
                  <dl className="mt-2 space-y-1 text-xs">
                    {version.changed_fields.map((field) => (
                      <div key={field} className="flex flex-wrap gap-1">
                        <dt className="font-medium">{field}:</dt>
                        <dd className="text-muted-foreground">
                          {t("previous")} {historyValue(version.previous_data?.[field])} →{" "}
                          {t("new")} {historyValue(version.new_data[field])}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </div>
  );
}

export default function StudentProfilePage() {
  const t = useTranslations("studentProfile");
  const tStudents = useTranslations("students");
  const tAcademics = useTranslations("academics");
  const tCommon = useTranslations("common");
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const studentId = params?.id ?? "";
  const locale = useLocale();
  const { hasPermission, user } = useAuth();
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();
  const [editing, setEditing] = useState(false);
  const [selfEditing, setSelfEditing] = useState(false);
  const [selectedPeriodId, setSelectedPeriodId] = useState("");

  const fetchStudent = useCallback(() => studentApi.getStudent(studentId), [studentId]);
  // These three are optional relationships: a student may legitimately have no
  // housing, immigration or academic record, so a failure here must not blank
  // the whole profile.
  const fetchHousing = useCallback(async () => {
    try {
      return await getStudentHousing(studentId);
    } catch {
      return null;
    }
  }, [studentId]);
  const fetchImmigration = useCallback(async () => {
    try {
      return await getStudentImmigration(studentId);
    } catch {
      return null;
    }
  }, [studentId]);
  const fetchAcademic = useCallback(async () => {
    try {
      return await getStudentAcademic(studentId, selectedPeriodId || undefined);
    } catch {
      return null;
    }
  }, [studentId, selectedPeriodId]);
  const fetchPeriods = useCallback(() => listPeriods(1, 50), []);

  const student = useApi<StudentDetail>(fetchStudent, [studentId], "student profile");
  const housing = useApi<StudentHousingResponse | null>(fetchHousing, [studentId], "student housing");
  const immigration = useApi<ImmigrationProfile | null>(fetchImmigration, [studentId], "student immigration");
  const academic = useApi<StudentAcademicOverview | null>(
    fetchAcademic,
    [studentId, selectedPeriodId],
    "student academic",
  );
  const periods = useApi(fetchPeriods, [], "academic periods");

  const requestedTab = searchParams.get("tab");
  const [tab, setTab] = useState(
    requestedTab && ["overview", "academic", "immigration", "housing", "timetable", "documents"].includes(requestedTab)
      ? requestedTab
      : "overview",
  );
  const localized = localizeError(student.error);

  if (student.loading) {
    return (
      <AppShell>
        <LoadingState />
      </AppShell>
    );
  }

  if (student.error || !student.data) {
    return (
      <AppShell>
        <ErrorState
          title={student.error?.status === 404 ? t("notFound") : localized.message}
          message={student.error?.status === 404 ? undefined : localized.hint}
          onRetry={student.error?.status === 404 ? undefined : student.refetch}
        />
        <div className="mt-4 flex justify-center">
          <Button asChild variant="outline" size="sm">
            <Link href="/app/students">{tStudents("directory")}</Link>
          </Button>
        </div>
      </AppShell>
    );
  }

  const record = student.data;
  const canEdit = hasPermission("student.edit");
  // Self-service is scoped to the signed-in student's own record.
  const isOwnRecord = !!user && record.user_id === user.id;
  const canSelfEdit = isOwnRecord && !canEdit;
  // Document *access* is a permission; the API independently checks that the
  // viewer may see this particular student's file.
  const canViewDocuments = hasPermission("documents.view");
  const canUploadDocuments = hasPermission("documents.upload");
  const canReviewDocuments = hasPermission("documents.manage");
  const fullName = `${record.first_name} ${record.last_name}`;
  const assignment = housing.data?.has_assignment ? housing.data.assignment : null;
  const permitStatus = immigration.data?.residence_permit_status ?? null;
  const permitDays = immigration.data?.residence_permit_days_remaining ?? null;

  const dateValue = (value?: string | null) =>
    value ? format.dateTime(new Date(value), { dateStyle: "medium" }) : tCommon("states.notSet");

  return (
    <AppShell>
      <PageHeader
        title={fullName}
        description={
          record.preferred_name
            ? `${tStudents("fields.preferredName")}: ${record.preferred_name}`
            : t("title")
        }
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: tStudents("title"), href: "/app/students" },
          { label: `${record.last_name} ${record.first_name}` },
        ]}
        actions={
          canEdit ? (
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              {tCommon("actions.edit")}
            </Button>
          ) : canSelfEdit ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setSelfEditing(true)}
            >
              {t("selfService.editButton")}
            </Button>
          ) : undefined
        }
      />

      {editing && (
        <EditStudentDialog
          open={editing}
          onOpenChange={setEditing}
          student={record}
          onSaved={() => {
            student.refetch();
            academic.refetch();
          }}
        />
      )}

      {selfEditing && (
        <SelfServiceDialog
          open={selfEditing}
          onOpenChange={setSelfEditing}
          student={record}
          onSaved={() => student.refetch()}
        />
      )}

      <Card className="mb-6 overflow-hidden">
        <div className="flex h-1 w-full bg-primary" aria-hidden="true">
          <span className="h-full w-24 bg-gold" />
        </div>
        <CardContent className="flex flex-col gap-5 p-5 sm:flex-row sm:items-start sm:p-6">
          <ProfilePhoto
            studentId={record.id}
            hasPhoto={record.has_photo}
            fullName={fullName}
            canEdit={canEdit || canSelfEdit}
            onChanged={() => student.refetch()}
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0">
                <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  {t("title")}
                </p>
                <h2 className="mt-1 truncate text-xl font-semibold tracking-[-0.02em]">
                  {fullName}
                </h2>
                {record.preferred_name && (
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {record.preferred_name}
                  </p>
                )}
                <p className="mt-1 font-mono text-xs text-muted-foreground">
                  {record.student_id}
                </p>
              </div>
              <StatusBadge tone={toneForStatus(record.status)}>
                {statusLabel(record.status, "students.status")}
              </StatusBadge>
            </div>

            <div className="mt-5 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
              <QuickFact
                icon={<Hash className="h-4 w-4" />}
                label={tStudents("fields.studentNumber")}
                value={record.student_id}
              />
              <QuickFact
                icon={<Mail className="h-4 w-4" />}
                label={tStudents("fields.email")}
                value={record.user_email ?? tCommon("states.notSet")}
              />
              <QuickFact
                icon={<Phone className="h-4 w-4" />}
                label={tStudents("fields.phone")}
                value={record.phone ?? tCommon("states.notSet")}
              />
              <QuickFact
                icon={<MapPin className="h-4 w-4" />}
                label={tStudents("fields.nationality")}
                value={record.nationality ?? tCommon("states.notSet")}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {(immigration.data || housing.data || academic.data) && (
        <div className="mb-6 grid gap-3 sm:grid-cols-3">
          {immigration.data && (
            <ProfileSignal
              icon={<Globe2 className="h-4 w-4" aria-hidden="true" />}
              label={t("signals.immigration")}
              value={
                permitStatus
                  ? statusLabel(permitStatus, "immigration.statusLabel")
                  : tCommon("states.notProvided")
              }
              meta={
                permitDays !== null
                  ? t("signals.daysRemaining", { count: permitDays })
                  : tCommon("actions.viewDetails")
              }
              onClick={() => setTab("immigration")}
            />
          )}
          {housing.data && (
            <ProfileSignal
              icon={<Home className="h-4 w-4" aria-hidden="true" />}
              label={t("signals.housing")}
              value={
                assignment?.building_name
                  ? `${assignment.building_name} · ${assignment.room_number ?? "—"}`
                  : t("signals.noResidence")
              }
              meta={
                assignment?.bed_label ?? tCommon("actions.viewDetails")
              }
              onClick={() => setTab("housing")}
            />
          )}
          {academic.data && (
            <ProfileSignal
              icon={<GraduationCap className="h-4 w-4" aria-hidden="true" />}
              label={t("signals.academic")}
              value={academic.data.program?.name ?? tAcademics("noProgram")}
              meta={t("signals.classCount", {
                count: academic.data.enrolled_classes.length,
              })}
              onClick={() => setTab("academic")}
            />
          )}
        </div>
      )}

      {(periods.data?.items.length ?? 0) > 0 && (
        <div className="mb-5 flex flex-col gap-1.5 sm:max-w-sm">
          <label htmlFor="student-period" className="text-xs font-medium text-muted-foreground">
            {tAcademics("periodFilter")}
          </label>
          <select
            id="student-period"
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
            value={selectedPeriodId}
            onChange={(event) => setSelectedPeriodId(event.target.value)}
          >
            <option value="">{tAcademics("currentPeriodOption")}</option>
            {periods.data?.items.map((period) => (
              <option key={period.id} value={period.id}>
                {period.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <Tabs
        value={tab}
        onValueChange={setTab}
        dir={locale === "ar" ? "rtl" : "ltr"}
      >
        <TabsList className="flex w-full flex-wrap justify-start">
          <TabsTrigger value="overview">{t("tabs.overview")}</TabsTrigger>
          <TabsTrigger value="academic">{t("tabs.academic")}</TabsTrigger>
          <TabsTrigger value="immigration">{t("tabs.immigration")}</TabsTrigger>
          <TabsTrigger value="housing">{t("tabs.housing")}</TabsTrigger>
          <TabsTrigger value="timetable">{t("tabs.timetable")}</TabsTrigger>
          <TabsTrigger value="documents" disabled={!canViewDocuments}>
            {t("tabs.documents")}
          </TabsTrigger>
          {/*
            Attendance is a student-level record, so the profile action opens
            the attendance workspace on this student rather than duplicating the
            register here. The link is disabled only when the account may not
            view attendance at all; a student without an episode or a
            commencement still lands on a page that explains why.
          */}
          {hasPermission("attendance.view") ? (
            <TabsTrigger value="attendance" asChild>
              <Link href={`/app/attendance?student=${studentId}`}>
                {t("tabs.attendance")}
              </Link>
            </TabsTrigger>
          ) : (
            <TabsTrigger value="attendance" disabled>
              {t("tabs.attendance")}
            </TabsTrigger>
          )}
          <TabsTrigger value="support" disabled>
            {t("tabs.support")}
          </TabsTrigger>
          <TabsTrigger value="activity" disabled>
            {t("tabs.activity")}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid gap-6 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">{tStudents("identity")}</CardTitle>
              </CardHeader>
              <CardContent>
                <DetailList
                  columns={1}
                  items={[
                    { label: tCommon("labels.name"), value: fullName },
                    {
                      label: tStudents("fields.preferredName"),
                      value: record.preferred_name ?? tCommon("states.notSet"),
                    },
                    {
                      label: tStudents("fields.dateOfBirth"),
                      value: dateValue(record.date_of_birth),
                    },
                    {
                      label: tStudents("fields.gender"),
                      value: record.gender ?? tCommon("states.notSet"),
                    },
                    {
                      label: tStudents("fields.nationality"),
                      value: record.nationality ?? tCommon("states.notSet"),
                    },
                  ]}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">{tStudents("contact")}</CardTitle>
              </CardHeader>
              <CardContent>
                <DetailList
                  columns={1}
                  items={[
                    {
                      label: tStudents("fields.email"),
                      value: record.user_email ?? tCommon("states.notSet"),
                    },
                    {
                      label: tStudents("fields.phone"),
                      value: record.phone ?? tCommon("states.notSet"),
                    },
                    {
                      label: tStudents("fields.emergencyContactName"),
                      value: record.emergency_contact_name ?? tCommon("states.notSet"),
                    },
                    {
                      label: tStudents("fields.emergencyContactPhone"),
                      value: record.emergency_contact_phone ?? tCommon("states.notSet"),
                    },
                  ]}
                />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="academic">
          <div className="space-y-6">
            {/* A student's own record is the only place the self-service picker
                appears: staff change a placement through the edit dialog. */}
            {isOwnRecord && (
              <MajorSelection onSelected={() => student.refetch()} />
            )}
            {hasPermission("academic.view_admissions") && (
              <PlacementPanel
                studentId={record.id}
                onChanged={() => {
                  academic.refetch();
                  student.refetch();
                }}
              />
            )}
            {(hasPermission("academic.view_admissions") || isOwnRecord) && (
              <ProgrammeChangePanel
                studentId={record.id}
                own={isOwnRecord}
                onChanged={() => {
                  academic.refetch();
                  student.refetch();
                }}
              />
            )}
            <Card>
              <CardContent className="pt-6">
                {academic.loading ? (
                  <LoadingState />
                ) : (
                  <AcademicTab academic={academic.data} />
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="immigration">
          <Card>
            <CardContent className="pt-6">
              {immigration.loading ? (
                <LoadingState />
              ) : (
                <ImmigrationTab
                  profile={immigration.data}
                  studentId={record.id}
                  isOwnRecord={isOwnRecord}
                  canEdit={!isOwnRecord && hasPermission("immigration.edit")}
                  onChanged={immigration.refetch}
                />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="housing">
          <Card>
            <CardContent className="pt-6">
              {housing.loading ? <LoadingState /> : <HousingTab housing={housing.data} />}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="timetable">
          <Card>
            <CardContent className="pt-6">
              {academic.loading ? (
                <LoadingState />
              ) : (
                <TimetableTab entries={academic.data?.timetable ?? []} />
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="documents">
          {canViewDocuments ? (
            <DocumentsTab
              studentId={record.id}
              canUpload={canUploadDocuments}
              canManage={canReviewDocuments}
            />
          ) : (
            <EmptyState
              title={t("tabs.documents")}
              message={tCommon("states.notAvailable")}
            />
          )}
        </TabsContent>
      </Tabs>
    </AppShell>
  );
}
