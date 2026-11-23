"use client";

import { useCallback, useMemo, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { ArrowRight, Check, X } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { admissionApi } from "@/lib/admission-api";
import { admissionChangeApi } from "@/lib/admission-change-api";
import { listPrograms, listProgramOfferings } from "@/lib/academic-api";
import { StatusCorrectionDialog } from "@/components/admissions/status-correction-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DetailList } from "@/components/ui/detail-list";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
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
  AdmissionChange,
  AdmissionChangeListResponse,
} from "@/types/admission-change";
import type { AdmissionForPlacement } from "@/types/placement";
import type { PaginatedList, Program, ProgramOffering } from "@/types/academic";

interface ProgrammeChangePanelProps {
  studentId: string;
  own?: boolean;
  onChanged?: () => void;
}

const LIVE = new Set(["PENDING", "ADMITTED", "ACTIVE"]);
const TERMINAL = new Set(["COMPLETED", "WITHDRAWN", "CANCELLED"]);

export function ProgrammeChangePanel({
  studentId,
  own = false,
  onChanged,
}: ProgrammeChangePanelProps) {
  const t = useTranslations("studentProfile.programmeChange");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const { hasPermission, user } = useAuth();
  const canManage = !own && hasPermission("academic.manage_admissions");
  const canRequest = own || canManage;
  const canApprove = hasPermission("academic.approve_admission_change");
  const canCorrectStatus = !own && hasPermission("academic.correct_admission_status");
  const [requestAdmission, setRequestAdmission] =
    useState<AdmissionForPlacement | null>(null);
  const [reviewChange, setReviewChange] = useState<AdmissionChange | null>(null);
  const [statusCorrection, setStatusCorrection] = useState<{
    admission: AdmissionForPlacement;
    mode: "direct" | "request";
  } | null>(null);

  const fetchAdmissions = useCallback(
    () =>
      own ? admissionApi.ownAdmissions() : admissionApi.admissions(studentId),
    [own, studentId],
  );
  const fetchChanges = useCallback(
    () =>
      own
        ? admissionChangeApi.listOwn()
        : admissionChangeApi.list(studentId),
    [own, studentId],
  );
  const admissions = useApi<AdmissionForPlacement[]>(
    fetchAdmissions,
    [own, studentId],
    "student admissions",
  );
  const changes = useApi<AdmissionChangeListResponse>(
    fetchChanges,
    [own, studentId],
    "student admission changes",
  );

  const byAdmission = useMemo(() => {
    const grouped = new Map<string, AdmissionChange[]>();
    for (const change of changes.data?.items ?? []) {
      const list = grouped.get(change.admission_id) ?? [];
      list.push(change);
      grouped.set(change.admission_id, list);
    }
    return grouped;
  }, [changes.data]);

  const refresh = () => {
    admissions.refetch();
    changes.refetch();
    onChanged?.();
  };

  if (admissions.loading || changes.loading) return <LoadingState />;
  if (admissions.error || changes.error) {
    return (
      <ErrorState
        title={t("title")}
        message={localizeError(admissions.error ?? changes.error!).message}
        onRetry={() => {
          admissions.refetch();
          changes.refetch();
        }}
      />
    );
  }

  const episodes = admissions.data ?? [];
  if (episodes.length === 0) {
    return <EmptyState title={t("noAdmissions")} message={t("noAdmissionsHint")} />;
  }

  return (
    <section className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold">{t("title")}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{t("description")}</p>
      </div>

      {episodes.map((episode) => {
        const episodeChanges = byAdmission.get(episode.id) ?? [];
        const pending = episodeChanges.filter((change) => change.status === "PENDING");
        const decided = episodeChanges
          .filter(
            (change) =>
              (change.status === "APPROVED" || change.status === "REJECTED") &&
              (change.change_type === "PROGRAM_CHANGE" ||
                change.change_type === "STATUS_CORRECTION"),
          )
          .sort((a, b) =>
            (a.reviewed_at ?? a.requested_at).localeCompare(
              b.reviewed_at ?? b.requested_at,
            ),
          );
        const live = LIVE.has(episode.status);
        const terminal = TERMINAL.has(episode.status);
        const correctionsEnabled = episode.corrections_enabled !== false;

        return (
          <Card key={episode.id}>
            <CardHeader className="flex flex-col gap-2 space-y-0 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <CardTitle className="text-base">
                  {episode.admission_intake_name ?? tCommon("states.notSet")}
                </CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("episodeHint")}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <StatusBadge tone={toneForStatus(episode.status)}>
                  {t(`status.${episode.status}`)}
                </StatusBadge>
                {canRequest && live && pending.length === 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setRequestAdmission(episode)}
                  >
                    {t("requestChange")}
                  </Button>
                )}
                {correctionsEnabled && terminal && canCorrectStatus && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      setStatusCorrection({ admission: episode, mode: "direct" })
                    }
                  >
                    {t("statusCorrection.directAction")}
                  </Button>
                )}
                {correctionsEnabled &&
                  terminal &&
                  !canCorrectStatus &&
                  canManage && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() =>
                        setStatusCorrection({ admission: episode, mode: "request" })
                      }
                    >
                      {t("statusCorrection.requestAction")}
                    </Button>
                  )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <DetailList
                columns={2}
                items={[
                  {
                    label: t("originallyAdmitted"),
                    value:
                      episode.admitted_program_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("currentProgramme"),
                    value: episode.current_program_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("admissionIntake"),
                    value: episode.admission_intake_name ?? tCommon("states.notSet"),
                  },
                  {
                    label: t("admittedOffering"),
                    value:
                      episode.admitted_program_offering_name ??
                      tCommon("states.notSet"),
                  },
                ]}
              />

              {pending.map((change) => {
                const isStatusCorrection =
                  change.change_type === "STATUS_CORRECTION";
                const fromStatus = String(
                  change.current_data_snapshot?.status ?? "",
                );
                const toStatus = String(change.proposed_data.status ?? "");
                const canReviewThis = isStatusCorrection
                  ? canCorrectStatus && (!terminal || correctionsEnabled)
                  : canApprove;
                return (
                <div
                  key={change.id}
                  className="rounded-lg border border-warning/40 bg-warning/10 p-3"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <Badge variant="outline" className="border-warning/50 text-warning">
                        {isStatusCorrection
                          ? t("statusCorrection.pending")
                          : t("pending")}
                      </Badge>
                      {isStatusCorrection ? (
                        <>
                          <span className="font-medium">
                            {fromStatus
                              ? t(`status.${fromStatus}`)
                              : tCommon("states.notSet")}
                          </span>
                          <ArrowRight
                            className="h-4 w-4 text-muted-foreground rtl:rotate-180"
                            aria-hidden="true"
                          />
                          <span className="font-medium">
                            {toStatus
                              ? t(`status.${toStatus}`)
                              : tCommon("states.notSet")}
                          </span>
                        </>
                      ) : (
                        <>
                          <span className="font-medium">
                            {change.from_program_name ?? tCommon("states.notSet")}
                          </span>
                          <ArrowRight
                            className="h-4 w-4 text-muted-foreground rtl:rotate-180"
                            aria-hidden="true"
                          />
                          <span className="font-medium">
                            {change.to_program_name ?? tCommon("states.notSet")}
                          </span>
                        </>
                      )}
                    </div>
                    {canReviewThis && change.requested_by_id !== user?.id && (
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={() => setReviewChange(change)}
                        >
                          {t("review")}
                        </Button>
                      </div>
                    )}
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    {t("requestedBy", {
                      name: change.requested_by_name ?? tCommon("states.notSet"),
                    })}
                    {" · "}
                    {format.dateTime(new Date(change.requested_at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </p>
                  {change.reason && (
                    <p className="mt-1 text-xs">
                      <span className="text-muted-foreground">{t("reason")}: </span>
                      {change.reason}
                    </p>
                  )}
                  {change.requested_by_id === user?.id && (
                    <p className="mt-2 text-xs text-muted-foreground">
                      {t("selfApprovalHint")}
                    </p>
                  )}
                </div>
                );
              })}

              {decided.length > 0 && (
                <div>
                  <h4 className="mb-2 text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                    {t("timeline")}
                  </h4>
                  <ol className="relative ms-1 space-y-3 border-s border-border/80 ps-5">
                    <li className="relative rounded-lg border border-border/70 bg-muted/20 p-3">
                      <span
                        className="absolute -start-[1.63rem] top-4 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary"
                        aria-hidden="true"
                      />
                      <p className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">
                        {t("admitted")}
                      </p>
                      <p className="mt-1 text-sm font-medium">
                        {episode.admitted_program_name ?? tCommon("states.notSet")}
                      </p>
                    </li>
                    {decided.map((change) => {
                      const isStatusCorrection =
                        change.change_type === "STATUS_CORRECTION";
                      const fromStatus = String(
                        change.current_data_snapshot?.status ?? "",
                      );
                      const toStatus = String(change.proposed_data.status ?? "");
                      return (
                      <li
                        key={change.id}
                        className="relative rounded-lg border border-border/70 bg-card p-3"
                      >
                        <span
                          className="absolute -start-[1.63rem] top-4 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary"
                          aria-hidden="true"
                        />
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="flex flex-wrap items-center gap-2 text-sm">
                            {isStatusCorrection ? (
                              <>
                                <span className="font-medium">
                                  {fromStatus
                                    ? t(`status.${fromStatus}`)
                                    : tCommon("states.notSet")}
                                </span>
                                <ArrowRight
                                  className="h-3.5 w-3.5 text-muted-foreground rtl:rotate-180"
                                  aria-hidden="true"
                                />
                                <span className="font-medium">
                                  {toStatus
                                    ? t(`status.${toStatus}`)
                                    : tCommon("states.notSet")}
                                </span>
                              </>
                            ) : (
                              <>
                                <span className="font-medium">
                                  {change.from_program_name ??
                                    tCommon("states.notSet")}
                                </span>
                                <ArrowRight
                                  className="h-3.5 w-3.5 text-muted-foreground rtl:rotate-180"
                                  aria-hidden="true"
                                />
                                <span className="font-medium">
                                  {change.to_program_name ??
                                    tCommon("states.notSet")}
                                </span>
                              </>
                            )}
                          </div>
                          <StatusBadge
                            tone={change.status === "APPROVED" ? "success" : "danger"}
                          >
                            {t(`changeStatus.${change.status}`)}
                          </StatusBadge>
                        </div>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {change.status === "APPROVED"
                            ? t("approvedBy", {
                                name:
                                  change.reviewed_by_name ??
                                  tCommon("states.notSet"),
                              })
                            : t("rejectedBy", {
                                name:
                                  change.reviewed_by_name ??
                                  tCommon("states.notSet"),
                              })}
                          {change.reviewed_at
                            ? ` · ${format.dateTime(new Date(change.reviewed_at), {
                                dateStyle: "medium",
                                timeStyle: "short",
                              })}`
                            : ""}
                        </p>
                        {change.decision_reason && (
                          <p className="mt-1 text-xs">
                            <span className="text-muted-foreground">
                              {t("decisionReason")}:{" "}
                            </span>
                            {change.decision_reason}
                          </p>
                        )}
                      </li>
                      );
                    })}
                  </ol>
                </div>
              )}

              {decided.length === 0 && pending.length === 0 && (
                <p className="text-xs text-muted-foreground">{t("noChanges")}</p>
              )}
            </CardContent>
          </Card>
        );
      })}

      {requestAdmission && (
        <RequestDialog
          studentId={studentId}
          own={own}
          admission={requestAdmission}
          onClose={() => setRequestAdmission(null)}
          onSaved={() => {
            setRequestAdmission(null);
            refresh();
          }}
        />
      )}

      {reviewChange && (
        <ReviewDialog
          change={reviewChange}
          onClose={() => setReviewChange(null)}
          onSaved={() => {
            setReviewChange(null);
            refresh();
          }}
        />
      )}

      {statusCorrection && (
        <StatusCorrectionDialog
          studentId={studentId}
          admission={statusCorrection.admission}
          mode={statusCorrection.mode}
          onClose={() => setStatusCorrection(null)}
          onSaved={() => {
            setStatusCorrection(null);
            refresh();
          }}
        />
      )}
    </section>
  );
}

function RequestDialog({
  studentId,
  own,
  admission,
  onClose,
  onSaved,
}: {
  studentId: string;
  own: boolean;
  admission: AdmissionForPlacement;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("studentProfile.programmeChange");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [programId, setProgramId] = useState("");
  const [offeringId, setOfferingId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const fetchPrograms = useCallback(() => listPrograms(1, 100), []);
  const programs = useApi<PaginatedList<Program>>(fetchPrograms, [], "programmes");
  const fetchOfferings = useCallback(
    () => listProgramOfferings(admission.admission_intake_id, undefined, 1, 100),
    [admission.admission_intake_id],
  );
  const offerings = useApi<PaginatedList<ProgramOffering>>(
    fetchOfferings,
    [admission.admission_intake_id],
    "programme offerings",
  );

  const programmeOptions = (programs.data?.items ?? []).filter(
    (program) =>
      program.id !== admission.current_program_id &&
      program.status !== "INACTIVE",
  );
  const offeringOptions = (offerings.data?.items ?? []).filter(
    (offering) =>
      offering.program_id === programId && offering.selectable !== false,
  );
  const canChooseOffering =
    admission.status === "ADMITTED" || admission.status === "ACTIVE";
  const canSubmit = programId !== "" && !busy;

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setFailure(null);
    try {
      const input = {
        change_type: "PROGRAM_CHANGE" as const,
        to_program_id: programId,
        to_program_offering_id: offeringId || undefined,
        reason: reason.trim() || undefined,
      };
      if (own) {
        await admissionChangeApi.requestOwn(input);
      } else {
        await admissionChangeApi.request(studentId, admission.id, input);
      }
      toast.success(t("requestSuccess"));
      onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "programme change"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("requestTitle")}</DialogTitle>
          <DialogDescription>{t("requestDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm">
            <p className="text-xs text-muted-foreground">{t("originallyAdmitted")}</p>
            <p className="font-medium">
              {admission.admitted_program_name ?? tCommon("states.notSet")}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">{t("currentProgramme")}</p>
            <p className="font-medium">
              {admission.current_program_name ?? tCommon("states.notSet")}
            </p>
          </div>

          <div className="space-y-1.5 text-sm">
            <label htmlFor="change-programme" className="font-medium">
              {t("newProgramme")}
            </label>
            <select
              id="change-programme"
              value={programId}
              onChange={(event) => {
                setProgramId(event.target.value);
                setOfferingId("");
              }}
              className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm"
            >
              <option value="">{t("selectProgramme")}</option>
              {programmeOptions.map((program) => (
                <option key={program.id} value={program.id}>
                  {program.name} ({program.code})
                </option>
              ))}
            </select>
          </div>

          {canChooseOffering ? (
            <div className="space-y-1.5 text-sm">
              <label htmlFor="change-offering" className="font-medium">
                {t("newOffering")}
              </label>
              <select
                id="change-offering"
                value={offeringId}
                onChange={(event) => setOfferingId(event.target.value)}
                disabled={!programId || offerings.loading}
                className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              >
                <option value="">{t("keepOffering")}</option>
                {offeringOptions.map((offering) => (
                  <option key={offering.id} value={offering.id}>
                    {offering.name}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">{t("offeringHint")}</p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              {t("pendingOfferingHint")}
            </p>
          )}

          <div className="space-y-1.5 text-sm">
            <label htmlFor="change-reason" className="font-medium">
              {t("reason")}
            </label>
            <Textarea
              id="change-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t("reasonPlaceholder")}
            />
          </div>

          <p className="text-xs text-muted-foreground">{t("notNewEpisode")}</p>

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
            {t("submitRequest")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ReviewDialog({
  change,
  onClose,
  onSaved,
}: {
  change: AdmissionChange;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("studentProfile.programmeChange");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const isStatusCorrection = change.change_type === "STATUS_CORRECTION";
  const fromStatus = String(change.current_data_snapshot?.status ?? "");
  const toStatus = String(change.proposed_data.status ?? "");

  async function decide(decision: "APPROVE" | "REJECT") {
    setBusy(true);
    setFailure(null);
    try {
      await admissionChangeApi.review(change.id, {
        decision,
        reason: reason.trim() || undefined,
      });
      toast.success(
        decision === "APPROVE"
          ? isStatusCorrection
            ? t("statusCorrection.approveSuccess")
            : t("approveSuccess")
          : isStatusCorrection
            ? t("statusCorrection.rejectSuccess")
            : t("rejectSuccess"),
      );
      onSaved();
    } catch (error) {
      setFailure(normalizeApiError(error, "change review"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isStatusCorrection
              ? t("statusCorrection.reviewTitle")
              : t("reviewTitle")}
          </DialogTitle>
          <DialogDescription>
            {isStatusCorrection
              ? t("statusCorrection.reviewDescription")
              : t("reviewDescription")}
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm">
          <p className="font-medium">
            {isStatusCorrection
              ? fromStatus
                ? t(`status.${fromStatus}`)
                : tCommon("states.notSet")
              : (change.from_program_name ?? tCommon("states.notSet"))}{" "}
            <ArrowRight className="inline h-3.5 w-3.5 rtl:rotate-180" aria-hidden="true" />{" "}
            {isStatusCorrection
              ? toStatus
                ? t(`status.${toStatus}`)
                : tCommon("states.notSet")
              : (change.to_program_name ?? tCommon("states.notSet"))}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {t("requestedBy", {
              name: change.requested_by_name ?? tCommon("states.notSet"),
            })}
          </p>
          {change.reason && (
            <p className="mt-1 text-xs">
              <span className="text-muted-foreground">{t("reason")}: </span>
              {change.reason}
            </p>
          )}
        </div>

        <div className="space-y-1.5 text-sm">
          <label htmlFor="decision-reason" className="font-medium">
            {t("decisionReason")}
          </label>
          <Textarea
            id="decision-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t("decisionPlaceholder")}
          />
        </div>

        <p className="text-xs text-muted-foreground">{t("oneApproverHint")}</p>

        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            {tCommon("actions.cancel")}
          </Button>
          <Button
            variant="outline"
            onClick={() => void decide("REJECT")}
            disabled={busy}
          >
            <X className="me-1.5 h-4 w-4" aria-hidden="true" />
            {t("reject")}
          </Button>
          <Button onClick={() => void decide("APPROVE")} disabled={busy}>
            <Check className="me-1.5 h-4 w-4" aria-hidden="true" />
            {t("approve")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
