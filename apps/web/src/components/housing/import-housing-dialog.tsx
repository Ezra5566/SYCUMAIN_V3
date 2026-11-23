"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { FileSpreadsheet, Upload } from "lucide-react";
import {
  applyHousingImport,
  downloadHousingImportTemplate,
  previewHousingImport,
} from "@/lib/housing-api";
import { downloadBlob } from "@/lib/download";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import type { HousingImportReport } from "@/types/housing";

interface ImportHousingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: () => void;
}

/**
 * Housing allocation import.
 *
 * Preview is mandatory before writing: the operator must see which rows are
 * ready, which beds are already taken and which references do not resolve. The
 * server refuses the whole batch when any row is invalid, and this dialog says
 * so rather than implying a partial import happened.
 */
export function ImportHousingDialog({
  open,
  onOpenChange,
  onImported,
}: ImportHousingDialogProps) {
  const t = useTranslations("housing.import");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("errors");
  const localizeError = useErrorMessage();

  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [sourceReference, setSourceReference] = useState("");
  const [busy, setBusy] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [report, setReport] = useState<HousingImportReport | null>(null);

  const reset = () => {
    setFile(null);
    setReport(null);
    setError(null);
    setSourceReference("");
    if (inputRef.current) inputRef.current.value = "";
  };

  const handleClose = (next: boolean) => {
    if (busy) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const run = async (mode: "preview" | "apply") => {
    if (!file) return;
    setBusy(mode);
    setError(null);
    try {
      const result =
        mode === "preview"
          ? await previewHousingImport(file)
          : await applyHousingImport(file, sourceReference);
      setReport(result);
      if (mode === "apply" && result.created > 0) {
        toast.success(t("applied", { count: result.created }));
        onImported();
      }
    } catch (err) {
      setError(normalizeApiError(err, "housing import"));
    } finally {
      setBusy(null);
    }
  };

  const handleTemplate = async () => {
    try {
      downloadBlob(
        await downloadHousingImportTemplate(),
        "housing-import-template.csv",
      );
    } catch (err) {
      setError(normalizeApiError(err, "housing import template"));
    }
  };

  const localized = localizeError(error);
  const canApply = Boolean(report) && !report?.aborted && report?.valid !== 0;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="housing-import-file" className="block text-sm font-medium">
              {t("chooseFile")}
            </label>
            <input
              id="housing-import-file"
              ref={inputRef}
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setReport(null);
                setError(null);
              }}
              className="block w-full cursor-pointer rounded-md border border-input bg-background p-2 text-sm file:me-3 file:rounded file:border-0 file:bg-muted file:px-3 file:py-1.5 file:text-sm"
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={handleTemplate}>
                <FileSpreadsheet className="me-1.5 h-4 w-4" aria-hidden="true" />
                {t("template")}
              </Button>
              <p className="text-xs text-muted-foreground">{t("formatHint")}</p>
            </div>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="housing-import-source"
              className="block text-sm font-medium"
            >
              {t("sourceReference")}
            </label>
            <input
              id="housing-import-source"
              value={sourceReference}
              onChange={(event) => setSourceReference(event.target.value)}
              placeholder={t("sourceReferencePlaceholder")}
              maxLength={200}
              className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
            <p className="text-xs text-muted-foreground">{t("sourceReferenceHint")}</p>
          </div>

          {error && <ErrorState title={localized.message} hint={localized.hint} />}

          {report && (
            <div className="space-y-3">
              <p className="text-sm" role="status">
                {t("summary", {
                  total: report.total,
                  valid: report.valid,
                  created: report.created,
                  skipped: report.skipped,
                  failed: report.failed,
                })}
              </p>

              {report.aborted && (
                <p
                  role="alert"
                  className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm"
                >
                  {t("aborted")}
                </p>
              )}

              <div className="max-h-64 overflow-y-auto rounded-md border">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="p-2 text-start font-medium">{t("rowHeader")}</th>
                      <th className="p-2 text-start font-medium">{t("studentHeader")}</th>
                      <th className="p-2 text-start font-medium">{t("bedHeader")}</th>
                      <th className="p-2 text-start font-medium">{t("resultHeader")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows.map((row) => (
                      <tr key={row.row_number} className="border-t align-top">
                        <td className="p-2 tabular-nums">{row.row_number}</td>
                        <td className="p-2">
                          <span className="font-mono">
                            {row.student_number ?? "—"}
                          </span>
                          {row.student_name && (
                            <span className="block text-muted-foreground">
                              {row.student_name}
                            </span>
                          )}
                        </td>
                        <td className="p-2">
                          {[row.building, row.room, row.bed]
                            .filter(Boolean)
                            .join(" · ") || "—"}
                        </td>
                        <td className="p-2">
                          <span className="font-medium">
                            {t(`status.${row.status}`)}
                          </span>
                          {row.code && (
                            <span className="block text-muted-foreground">
                              {tErrors.has(`codes.${row.code}`)
                                ? tErrors(`codes.${row.code}`)
                                : row.message}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {report.dry_run && !report.aborted && report.valid > 0 && (
                <p className="text-xs text-muted-foreground">{t("confirmHint")}</p>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleClose(false)}>
            {tCommon("actions.close")}
          </Button>
          <Button
            variant="outline"
            onClick={() => run("preview")}
            disabled={!file || busy !== null}
          >
            {busy === "preview" ? t("running") : t("preview")}
          </Button>
          <Button
            onClick={() => run("apply")}
            disabled={!file || busy !== null || !canApply}
          >
            <Upload className="me-1.5 h-4 w-4" aria-hidden="true" />
            {busy === "apply" ? t("running") : t("apply")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
