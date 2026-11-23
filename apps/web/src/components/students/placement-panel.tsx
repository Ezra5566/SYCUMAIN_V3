"use client";

import { useCallback, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { useAuth } from "@/lib/auth-context";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { admissionApi } from "@/lib/admission-api";
import { placementApi } from "@/lib/placement-api";
import { listPeriods, listProgramOfferings } from "@/lib/academic-api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { DetailList } from "@/components/ui/detail-list";
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
  AdmissionForPlacement,
  PlacementListResponse,
} from "@/types/placement";
import type { AcademicPeriod, PaginatedList, ProgramOffering } from "@/types/academic";

interface PlacementPanelProps {
  studentId: string;
  onChanged: () => void;
}

const ELIGIBLE_STATUSES = new Set(["ADMITTED", "ACTIVE"]);

export function PlacementPanel({ studentId, onChanged }: PlacementPanelProps) {
  const t = useTranslations("studentProfile.placement");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const { hasPermission } = useAuth();
  const canManage = hasPermission("academic.manage_placements");
  const canAuthorize = hasPermission("academic.authorize_placement");
  const [editing, setEditing] = useState(false);

  const fetchPlacements = useCallback(
    () => placementApi.list(studentId),
    [studentId],
  );
  const fetchAdmissions = useCallback(
    () => admissionApi.admissions(studentId),
    [studentId],
  );
  const placements = useApi<PlacementListResponse>(
    fetchPlacements,
    [studentId],
    "student placements",
  );
  const admissions = useApi<AdmissionForPlacement[]>(
    fetchAdmissions,
    [studentId],
    "student admission options",
  );

  const current = placements.data?.items.find((item) => item.is_current) ?? null;
  const eligibleAdmissions = useMemo(
    () =>
      (admissions.data ?? []).filter((item) =>
        ELIGIBLE_STATUSES.has(item.status),
      ),
    [admissions.data],
  );
  const originalAdmission =
    (admissions.data ?? []).find(
      (item) => item.id === current?.admission_id,
    ) ??
    eligibleAdmissions[0] ??
    null;

  const loading = placements.loading || admissions.loading;
  const error = placements.error ?? admissions.error;

  const refresh = () => {
    placements.refetch();
    admissions.refetch();
    onChanged();
  };

  return (
    <section className="space-y-4 rounded-xl border border-border/80 bg-card p-4 shadow-card">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold">{t("title")}</h3>
          <p className="mt-1 text-xs text-muted-foreground">{t("description")}</p>
        </div>
        {canManage && eligibleAdmissions.length > 0 && (
          <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
            {current ? t("change") : t("assign")}
          </Button>
        )}
      </div>

      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState
          title={t("title")}
          message={localizeError(error).message}
          onRetry={() => {
            placements.refetch();
            admissions.refetch();
          }}
        />
      ) : (
        <>
          {current ? (
            <div className="space-y-3">
              <DetailList
                columns={3}
                items={[
                  {
                    label: t("originalIntake"),
                    value: current.admission_intake_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("admittedProgram"),
                    value: originalAdmission?.admitted_program_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("currentIntake"),
                    value: current.placement_intake_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("currentOffering"),
                    value: current.program_offering_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("currentProgram"),
                    value: current.program_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("effectiveFrom"),
                    value: format.dateTime(new Date(current.effective_from), {
                      dateStyle: "medium",
                    }),
                  },
                ]}
              />
              {current.is_earlier_intake_placement && (
                <div className="rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
                  <p className="font-medium">{t("earlierTitle")}</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("earlierDescription")}
                  </p>
                  <div className="mt-2 grid gap-1 text-xs sm:grid-cols-3">
                    <p>
                      <span className="text-muted-foreground">{t("authorizedBy")}: </span>
                      {current.authorized_by_name ?? "—"}
                    </p>
                    <p>
                      <span className="text-muted-foreground">{t("authorizationReason")}: </span>
                      {current.authorization_reason ?? "—"}
                    </p>
                    <p>
                      <span className="text-muted-foreground">{t("authorizedAt")}: </span>
                      {format.dateTime(new Date(current.created_at), {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })}
                    </p>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <EmptyState title={t("none")} message={t("noneHint")} />
          )}

          {(placements.data?.items.length ?? 0) > 0 && (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                {t("history")}
              </h4>
              <ol className="space-y-2">
                {placements.data?.items.map((item) => (
                  <li
                    key={item.id}
                    className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={item.is_current ? "default" : "secondary"}>
                        {item.is_current ? t("current") : t("superseded")}
                      </Badge>
                      <span className="font-medium">
                        {item.placement_intake_name ?? tCommon("states.notSet")} ·{" "}
                        {item.program_offering_name ?? tCommon("states.notSet")}
                      </span>
                      {item.is_earlier_intake_placement && (
                        <Badge variant="outline" className="border-warning/50 text-warning">
                          {t("earlierBadge")}
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t("effectiveFrom")}:{" "}
                      {format.dateTime(new Date(item.effective_from), {
                        dateStyle: "medium",
                      })}
                      {item.ended_at
                        ? ` · ${t("endedAt")}: ${format.dateTime(
                            new Date(item.ended_at),
                            { dateStyle: "medium", timeStyle: "short" },
                          )}`
                        : ""}
                      {` · ${t("createdBy")}: ${item.created_by_name ?? "—"}`}
                    </p>
                  </li>
                ))}
              </ol>
            </div>
          )}
        </>
      )}

      {editing && (
        <PlacementDialog
          studentId={studentId}
          admissions={eligibleAdmissions}
          canAuthorize={canAuthorize}
          onClose={() => setEditing(false)}
          onSaved={() => {
            refresh();
            setEditing(false);
          }}
        />
      )}
    </section>
  );
}

function PlacementDialog({
  studentId,
  admissions,
  canAuthorize,
  onClose,
  onSaved,
}: {
  studentId: string;
  admissions: AdmissionForPlacement[];
  canAuthorize: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("studentProfile.placement");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [admissionId, setAdmissionId] = useState(admissions[0]?.id ?? "");
  const [periodId, setPeriodId] = useState("");
  const [offeringId, setOfferingId] = useState("");
  const [reason, setReason] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const fetchPeriods = useCallback(() => listPeriods(1, 100), []);
  const periods = useApi<PaginatedList<AcademicPeriod>>(
    fetchPeriods,
    [],
    "placement intakes",
  );
  const fetchOfferings = useCallback(
    () =>
      periodId
        ? listProgramOfferings(periodId, undefined, 1, 100)
        : Promise.resolve(null),
    [periodId],
  );
  const offerings = useApi<PaginatedList<ProgramOffering> | null>(
    fetchOfferings,
    [periodId],
    "placement offerings",
  );

  const admission = admissions.find((item) => item.id === admissionId) ?? null;
  const period = periods.data?.items.find((item) => item.id === periodId) ?? null;
  const selectedOffering =
    offerings.data?.items.find((item) => item.id === offeringId) ?? null;
  const earlier = !!(
    admission?.admission_intake_start_date &&
    period?.start_date &&
    period.start_date < admission.admission_intake_start_date
  );
  const mappedOfferings = (offerings.data?.items ?? []).filter(
    (offering) => offering.program_id,
  );
  const canSubmit =
    !!admissionId &&
    !!offeringId &&
    !busy &&
    (!earlier || (!!reason.trim() && canAuthorize));

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setFailure(null);
    try {
      await placementApi.create(studentId, {
        admission_id: admissionId,
        program_offering_id: offeringId,
        effective_from: effectiveFrom || undefined,
        reason: earlier ? reason.trim() : undefined,
      });
      toast.success(t("success"));
      onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "create placement"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("dialogTitle")}</DialogTitle>
          <DialogDescription>{t("dialogDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="space-y-1.5 text-sm">
            <label htmlFor="placement-admission" className="font-medium">
              {t("admission")}
            </label>
            <select
              id="placement-admission"
              value={admissionId}
              onChange={(event) => setAdmissionId(event.target.value)}
              className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm"
            >
              <option value="">{t("selectAdmission")}</option>
              {admissions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.admission_intake_name ?? item.admission_intake_id} ·{" "}
                  {item.admitted_program_name ?? tCommon("states.notSet")} ·{" "}
                  {item.status}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5 text-sm">
            <label htmlFor="placement-intake" className="font-medium">
              {t("intake")}
            </label>
            <select
              id="placement-intake"
              value={periodId}
              onChange={(event) => {
                setPeriodId(event.target.value);
                setOfferingId("");
              }}
              className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm"
            >
              <option value="">{t("selectIntake")}</option>
              {(periods.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {item.code}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5 text-sm">
            <label htmlFor="placement-offering" className="font-medium">
              {t("offering")}
            </label>
            <select
              id="placement-offering"
              value={offeringId}
              onChange={(event) => setOfferingId(event.target.value)}
              disabled={!periodId || offerings.loading}
              className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
            >
              <option value="">{t("selectOffering")}</option>
              {mappedOfferings.map((offering) => (
                <option key={offering.id} value={offering.id}>
                  {offering.name}
                </option>
              ))}
            </select>
            {periodId &&
              offerings.data &&
              mappedOfferings.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  {t("noOfferings")}
                </p>
              )}
          </div>

          <div className="space-y-1.5 text-sm">
            <label htmlFor="placement-effective-from" className="font-medium">
              {t("effectiveFrom")}
            </label>
            <Input
              id="placement-effective-from"
              type="date"
              value={effectiveFrom}
              onChange={(event) => setEffectiveFrom(event.target.value)}
            />
          </div>

          {earlier && (
            <div className="rounded-lg border border-warning/40 bg-warning/10 p-3">
              <p className="text-sm font-medium">{t("earlierTitle")}</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {canAuthorize ? t("reasonHint") : t("notAuthorized")}
              </p>
              <label
                htmlFor="placement-reason"
                className="mt-3 block text-sm font-medium"
              >
                {t("reason")}
              </label>
              <Textarea
                id="placement-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t("reasonPlaceholder")}
                className="mt-1.5"
                disabled={!canAuthorize}
              />
              {!reason.trim() && canAuthorize && (
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("reasonRequired")}
                </p>
              )}
            </div>
          )}

          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {localizeError(failure).message}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={!canSubmit}>
            {t("submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
