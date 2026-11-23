"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { AlertTriangle, ArrowRight } from "lucide-react";
import { admissionApi } from "@/lib/admission-api";
import { admissionChangeApi } from "@/lib/admission-change-api";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { Button } from "@/components/ui/button";
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
import type { AdmissionForPlacement } from "@/types/placement";

const STATUSES = [
  "PENDING",
  "ADMITTED",
  "ACTIVE",
  "COMPLETED",
  "WITHDRAWN",
  "CANCELLED",
] as const;

/**
 * Phase 7 terminal-status correction.
 *
 * ADMIN performs the correction; MANAGEMENT can only submit the same target
 * and reason as a change request. Both paths show the recorded status and end
 * state before anything changes, and require an explicit confirmation that
 * this is erroneous-data correction rather than a programme change or a new
 * admission.
 */
export function StatusCorrectionDialog({
  studentId,
  admission,
  mode,
  onClose,
  onSaved,
}: {
  studentId: string;
  admission: AdmissionForPlacement;
  mode: "direct" | "request";
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useTranslations("studentProfile.programmeChange.statusCorrection");
  const tStatus = useTranslations("studentProfile.programmeChange.status");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();

  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const canSubmit =
    target !== "" && reason.trim().length >= 20 && confirmed && !busy;
  const localized = localizeError(failure);

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setFailure(null);
    try {
      if (mode === "direct") {
        await admissionApi.correctStatus(
          studentId,
          admission.id,
          target,
          reason.trim(),
        );
        toast.success(t("success"));
      } else {
        await admissionChangeApi.request(studentId, admission.id, {
          change_type: "STATUS_CORRECTION",
          proposed_data: { status: target },
          reason: reason.trim(),
        });
        toast.success(t("requestSuccess"));
      }
      onSaved();
      onClose();
    } catch (error) {
      setFailure(normalizeApiError(error, "admission status correction"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {mode === "direct" ? t("title") : t("requestTitle")}
          </DialogTitle>
          <DialogDescription>
            {mode === "direct" ? t("description") : t("requestDescription")}
          </DialogDescription>
        </DialogHeader>

        <div className="rounded-lg border border-border/80 bg-muted/25 p-3 text-sm">
          <p className="text-xs text-muted-foreground">{t("currentRecord")}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <StatusBadge tone={toneForStatus(admission.status)}>
              {tStatus(admission.status)}
            </StatusBadge>
            <span className="font-medium">
              {admission.admission_intake_name ?? tCommon("states.notSet")}
            </span>
            <span className="text-muted-foreground">·</span>
            <span>{admission.admitted_program_name ?? tCommon("states.notSet")}</span>
          </div>
          {admission.activated_at && (
            <p className="mt-2 text-xs text-muted-foreground">
              {t("activatedAt", {
                date: format.dateTime(new Date(admission.activated_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </p>
          )}
          {admission.ended_at && (
            <p className="mt-1 text-xs text-muted-foreground">
              {t("endedAt", {
                date: format.dateTime(new Date(admission.ended_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                }),
              })}
            </p>
          )}
          {admission.end_reason && (
            <p className="mt-1 text-xs">
              <span className="text-muted-foreground">{t("recordedReason")}: </span>
              {admission.end_reason}
            </p>
          )}
        </div>

        <div className="space-y-1.5 text-sm">
          <label htmlFor="corrected-status" className="font-medium">
            {t("newStatus")}
          </label>
          <select
            id="corrected-status"
            value={target}
            onChange={(event) => setTarget(event.target.value)}
            className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm"
          >
            <option value="">{t("selectStatus")}</option>
            {STATUSES.filter((status) => status !== admission.status).map((status) => (
              <option key={status} value={status}>
                {tStatus(status)}
              </option>
            ))}
          </select>
        </div>

        {target && (
          <p className="flex flex-wrap items-center gap-2 rounded-lg border border-warning/35 bg-warning-soft/30 p-3 text-sm">
            <AlertTriangle className="h-4 w-4 text-warning" aria-hidden="true" />
            <span>{tStatus(admission.status)}</span>
            <ArrowRight className="h-4 w-4 rtl:rotate-180" aria-hidden="true" />
            <span className="font-semibold">{tStatus(target)}</span>
          </p>
        )}

        <label className="space-y-1.5 text-sm">
          <span className="font-medium">{t("reason")}</span>
          <Textarea
            value={reason}
            rows={4}
            maxLength={2000}
            placeholder={t("reasonHint")}
            onChange={(event) => setReason(event.target.value)}
          />
          <span className="block text-xs text-muted-foreground">
            {t("reasonRule")}
          </span>
        </label>

        <label className="flex items-start gap-2 rounded-lg border border-border/80 p-3 text-sm">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
          />
          <span>{t("confirm")}</span>
        </label>

        {failure && (
          <div
            role="alert"
            className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
          >
            <p className="font-medium">{localized.message}</p>
            {localized.hint && <p className="mt-1 text-xs">{localized.hint}</p>}
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={!canSubmit}>
            {busy
              ? tCommon("states.saving")
              : mode === "direct"
                ? t("submit")
                : t("requestSubmit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}