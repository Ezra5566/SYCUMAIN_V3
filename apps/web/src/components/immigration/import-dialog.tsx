"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FileUp, Loader2 } from "lucide-react";
import {
  applyImmigrationImport,
  previewImmigrationImport,
} from "@/lib/immigration-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
import type {
  ImmigrationImportPreview,
  ImmigrationImportRecord,
} from "@/types/immigration";

/**
 * Normalized import review.
 *
 * This deliberately does not parse an SCU spreadsheet format: the institution
 * has not supplied one. It accepts only the existing immigration field names,
 * previews conflicts, and requires a second explicit confirmation before the
 * non-conflicting values are written. Imported values remain UNVERIFIED.
 */
export function ImmigrationImportDialog({
  onImported,
}: {
  onImported: () => Promise<void> | void;
}) {
  const t = useTranslations("immigration");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [open, setOpen] = useState(false);
  const [sourceReference, setSourceReference] = useState("");
  const [payload, setPayload] = useState("");
  const [preview, setPreview] = useState<ImmigrationImportPreview | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  function parseRecords(): ImmigrationImportRecord[] | null {
    try {
      const parsed: unknown = JSON.parse(payload);
      const records = Array.isArray(parsed)
        ? parsed
        : typeof parsed === "object" && parsed !== null && "records" in parsed
          ? (parsed as { records?: unknown }).records
          : null;
      if (!Array.isArray(records) || records.length === 0) {
        setFailure(normalizeApiError(new Error(t("importNoRecords")), "import"));
        return null;
      }
      return records as ImmigrationImportRecord[];
    } catch {
      setFailure(normalizeApiError(new Error(t("importParseError")), "import"));
      return null;
    }
  }

  async function runPreview() {
    const records = parseRecords();
    if (!records) return;
    if (!sourceReference.trim()) {
      setFailure(
        normalizeApiError(new Error(t("importSourceRequired")), "import"),
      );
      return;
    }
    setBusy(true);
    setFailure(null);
    setPreview(null);
    setConfirmed(false);
    try {
      const result = await previewImmigrationImport({
        source_reference: sourceReference.trim(),
        records,
      });
      setPreview(result);
    } catch (error) {
      setFailure(normalizeApiError(error, "preview import"));
    } finally {
      setBusy(false);
    }
  }

  async function apply() {
    if (!preview || !confirmed) return;
    const records = parseRecords();
    if (!records) return;
    setBusy(true);
    setFailure(null);
    try {
      const result = await applyImmigrationImport({
        source_reference: sourceReference.trim(),
        records,
        confirm: true,
      });
      toast.success(
        t("importApplied", {
          applied: result.applied,
          skipped: result.skipped,
        }),
      );
      setOpen(false);
      setPreview(null);
      setPayload("");
      setConfirmed(false);
      await onImported();
    } catch (error) {
      setFailure(normalizeApiError(error, "apply import"));
    } finally {
      setBusy(false);
    }
  }

  const localized = failure ? localizeError(failure) : null;

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <FileUp className="me-1.5 h-4 w-4" aria-hidden="true" />
        {t("importRecords")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[92vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("importTitle")}</DialogTitle>
            <DialogDescription>{t("importDescription")}</DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">{t("importSourceReference")}</span>
              <Input
                value={sourceReference}
                onChange={(event) => setSourceReference(event.target.value)}
                maxLength={500}
                placeholder={t("importSourcePlaceholder")}
              />
            </label>
            <label className="space-y-1.5 text-sm sm:col-span-2">
              <span className="font-medium">{t("importPayload")}</span>
              <Textarea
                value={payload}
                onChange={(event) => setPayload(event.target.value)}
                rows={9}
                spellCheck={false}
                className="font-mono text-xs"
                placeholder={t("importPayloadPlaceholder")}
                aria-label={t("importPayload")}
              />
              <span className="block text-xs text-muted-foreground">
                {t("importPayloadHint")}
              </span>
            </label>
          </div>

          {localized && (
            <p role="alert" className="text-sm text-destructive">
              {localized.message}
            </p>
          )}

          {preview && (
            <div className="space-y-3 rounded-lg border p-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <StatusBadge tone="success">
                  {t("importApplyable", { count: preview.applyable })}
                </StatusBadge>
                <StatusBadge tone={preview.conflicts ? "warning" : "muted"}>
                  {t("importConflicts", { count: preview.conflicts })}
                </StatusBadge>
                <StatusBadge tone={preview.invalid ? "danger" : "muted"}>
                  {t("importInvalid", { count: preview.invalid })}
                </StatusBadge>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b text-muted-foreground">
                    <tr>
                      <th className="py-2 pe-3">{tCommon("labels.name")}</th>
                      <th className="py-2 pe-3">{t("importStatus")}</th>
                      <th className="py-2 pe-3">{t("importAppliedFields")}</th>
                      <th className="py-2">{t("importConflictFields")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.records.map((record) => (
                      <tr key={record.student_id} className="border-b last:border-0">
                        <td className="py-2 pe-3">
                          <p className="font-medium">
                            {record.student_name ?? record.student_id}
                          </p>
                          <p className="text-muted-foreground">
                            {record.student_number ?? "—"}
                          </p>
                        </td>
                        <td className="py-2 pe-3">
                          <StatusBadge
                            tone={
                              record.status === "INVALID"
                                ? "danger"
                                : record.status === "CONFLICT"
                                  ? "warning"
                                  : "success"
                            }
                          >
                            {record.status}
                          </StatusBadge>
                        </td>
                        <td className="py-2 pe-3">
                          {(record.applied_fields ?? []).join(", ") || "—"}
                        </td>
                        <td className="py-2">
                          {(record.conflicts ?? []).join(", ") || "—"}
                          {(record.errors ?? []).length > 0 && (
                            <p className="text-destructive">
                              {(record.errors ?? []).join("; ")}
                            </p>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                {t("importVerificationNotice")}
              </p>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-input"
                />
                <span>{t("importConfirmCheckbox")}</span>
              </label>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {tCommon("actions.cancel")}
            </Button>
            <Button variant="outline" onClick={() => void runPreview()} disabled={busy}>
              {busy ? (
                <Loader2 className="me-1.5 h-4 w-4 animate-spin" aria-hidden="true" />
              ) : null}
              {t("importPreview")}
            </Button>
            <Button
              onClick={() => void apply()}
              disabled={busy || !preview || preview.invalid > 0 || !confirmed}
            >
              {t("importApply")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
