"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FilePenLine, Send, ShieldCheck } from "lucide-react";
import {
  submitChangeRequest,
  updateStudentImmigration,
} from "@/lib/immigration-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import type { ImmigrationProfile } from "@/types/immigration";

type FieldKey =
  | "passport_number"
  | "passport_issuing_country"
  | "passport_issue_date"
  | "passport_expiry_date"
  | "passport_name_as_shown"
  | "visa_type"
  | "visa_number"
  | "visa_issue_date"
  | "visa_expiry_date"
  | "visa_entries"
  | "visa_issuing_authority"
  | "residence_permit_number"
  | "residence_permit_issue_date"
  | "residence_permit_expiry_date"
  | "residence_permit_issuing_authority";

const GROUPS: { key: string; fields: { key: FieldKey; labelKey: string; type?: string }[] }[] = [
  {
    key: "PASSPORT",
    fields: [
      { key: "passport_number", labelKey: "passportNumber" },
      { key: "passport_issuing_country", labelKey: "issuingCountry" },
      { key: "passport_issue_date", labelKey: "issueDate", type: "date" },
      { key: "passport_expiry_date", labelKey: "expiryDate", type: "date" },
      { key: "passport_name_as_shown", labelKey: "nameOnDocument" },
    ],
  },
  {
    key: "VISA",
    fields: [
      { key: "visa_type", labelKey: "visaType" },
      { key: "visa_number", labelKey: "visaNumber" },
      { key: "visa_issue_date", labelKey: "issueDate", type: "date" },
      { key: "visa_expiry_date", labelKey: "expiryDate", type: "date" },
      { key: "visa_entries", labelKey: "visaEntries" },
      { key: "visa_issuing_authority", labelKey: "issuingAuthority" },
    ],
  },
  {
    key: "RESIDENCE_PERMIT",
    fields: [
      { key: "residence_permit_number", labelKey: "permitNumber" },
      {
        key: "residence_permit_issue_date",
        labelKey: "issueDate",
        type: "date",
      },
      {
        key: "residence_permit_expiry_date",
        labelKey: "expiryDate",
        type: "date",
      },
      {
        key: "residence_permit_issuing_authority",
        labelKey: "issuingAuthority",
      },
    ],
  },
];

function currentValue(profile: ImmigrationProfile, key: FieldKey): string {
  const value = (profile as unknown as Record<string, unknown>)[key];
  return value === null || value === undefined ? "" : String(value);
}

export function ImmigrationActions({
  profile,
  studentId,
  isOwnRecord,
  canEdit,
  onChanged,
}: {
  profile: ImmigrationProfile;
  studentId: string;
  isOwnRecord: boolean;
  canEdit: boolean;
  onChanged: () => Promise<void> | void;
}) {
  const t = useTranslations("institutional");
  const [editing, setEditing] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const verified = profile.verification_status === "VERIFIED";

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/80 bg-muted/20 p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <StatusBadge tone={verified ? "success" : "warning"}>
          {verified ? t("verified") : t("unverified")}
        </StatusBadge>
        <span className="text-xs text-muted-foreground">
          {t("verificationHint")}
        </span>
      </div>
      <div className="flex flex-wrap gap-2">
        {isOwnRecord && (
          <Button variant="outline" size="sm" onClick={() => setSubmitting(true)}>
            <Send className="me-1 h-4 w-4" aria-hidden="true" />
            {t("submitChange")}
          </Button>
        )}
        {canEdit && (
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            <FilePenLine className="me-1 h-4 w-4" aria-hidden="true" />
            {t("updateRecord")}
          </Button>
        )}
      </div>

      {submitting && (
        <ImmigrationFormDialog
          mode="student"
          profile={profile}
          studentId={studentId}
          open={submitting}
          onOpenChange={setSubmitting}
          onSaved={onChanged}
        />
      )}
      {editing && (
        <ImmigrationFormDialog
          mode="staff"
          profile={profile}
          studentId={studentId}
          open={editing}
          onOpenChange={setEditing}
          onSaved={onChanged}
        />
      )}
    </div>
  );
}

function ImmigrationFormDialog({
  mode,
  profile,
  studentId,
  open,
  onOpenChange,
  onSaved,
}: {
  mode: "student" | "staff";
  profile: ImmigrationProfile;
  studentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void> | void;
}) {
  const t = useTranslations("institutional");
  const tImmigration = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [group, setGroup] = useState(GROUPS[0].key);
  const [changeReason, setChangeReason] = useState("");
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const item of GROUPS.flatMap((entry) => entry.fields)) {
      initial[item.key] = currentValue(profile, item.key);
    }
    return initial;
  });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const changed = GROUPS.flatMap((entry) => entry.fields).filter(
    (field) => values[field.key].trim() !== currentValue(profile, field.key),
  );
  const visibleGroup = GROUPS.find((entry) => entry.key === group) ?? GROUPS[0];

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      if (mode === "student") {
        const proposed: Record<string, string> = {};
        for (const field of changed) {
          if (values[field.key].trim()) proposed[field.key] = values[field.key].trim();
        }
        await submitChangeRequest(studentId, group, proposed);
        toast.success(tImmigration("submitSucceeded"));
      } else {
        if (changeReason.trim().length < 3) return;
        const payload: Record<string, unknown> = {
          change_reason: changeReason.trim(),
        };
        for (const field of changed) {
          payload[field.key] = values[field.key].trim() || null;
        }
        await updateStudentImmigration(studentId, payload);
        toast.success(t("updateSucceeded"));
      }
      await onSaved();
      onOpenChange(false);
    } catch (error) {
      setFailure(normalizeApiError(error, "immigration update"));
    } finally {
      setBusy(false);
    }
  }

  const canSubmit =
    changed.length > 0 && (mode === "student" || changeReason.trim().length >= 3);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {mode === "student" ? tImmigration("submitChangeTitle") : t("updateRecord")}
          </DialogTitle>
          <DialogDescription>
            {mode === "student"
              ? tImmigration("submitChangeSubtitle")
              : t("updateRecordDescription")}
          </DialogDescription>
        </DialogHeader>

        {mode === "student" && (
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("changeType")}</span>
            <select
              value={group}
              onChange={(event) => setGroup(event.target.value)}
              className="h-10 w-full rounded-md border border-input bg-background px-3"
            >
              {GROUPS.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {tImmigration(
                    entry.key === "PASSPORT"
                      ? "passport"
                      : entry.key === "VISA"
                        ? "visa"
                        : "residencePermit",
                  )}
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          {visibleGroup.fields.map((field) => (
            <label key={field.key} className="space-y-1.5 text-sm">
              <span className="font-medium">{tImmigration(field.labelKey)}</span>
              <Input
                type={field.type ?? "text"}
                value={values[field.key] ?? ""}
                onChange={(event) =>
                  setValues((current) => ({
                    ...current,
                    [field.key]: event.target.value,
                  }))
                }
              />
            </label>
          ))}
        </div>

        {mode === "staff" && (
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">{t("changeReason")}</span>
            <Input
              value={changeReason}
              onChange={(event) => setChangeReason(event.target.value)}
              placeholder={t("changeReasonHint")}
              maxLength={500}
            />
            <span className="block text-xs text-muted-foreground">
              {t("updateRecordAuditHint")}
            </span>
          </label>
        )}

        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={busy || !canSubmit}>
            {busy
              ? tCommon("states.saving")
              : mode === "student"
                ? tImmigration("submitChange")
                : tCommon("actions.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
