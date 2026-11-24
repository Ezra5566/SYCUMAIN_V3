"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { studentApi } from "@/lib/student-api";
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
import type { StudentImportReport } from "@/types/student";

interface ImportStudentsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: () => void;
}

/**
 * Bulk intake from a spreadsheet.
 *
 * Validation is a first-class step rather than an error path: the operator can
 * run the file through the same server-side rules with `dry_run`, see every row
 * and its reason, and only then write. The server refuses the whole file when a
 * row is invalid, and this dialog says so plainly instead of implying a partial
 * import happened.
 */
export function ImportStudentsDialog({
  open,
  onOpenChange,
  onImported,
}: ImportStudentsDialogProps) {
  const t = useTranslations("students.intake");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("errors");
  const localizeError = useErrorMessage();

  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState<"validate" | "import" | null>(null);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [report, setReport] = useState<StudentImportReport | null>(null);

  const reset = () => {
    setFile(null);
    setReport(null);
    setError(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const handleClose = (next: boolean) => {
    if (busy) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const run = async (dryRun: boolean) => {
    if (!file) return;
    setBusy(dryRun ? "validate" : "import");
    setError(null);
    try {
      const result = await studentApi.importStudents(file, { dryRun });
      setReport(result);
      if (!dryRun && result.created > 0) {
        toast.success(
          t("summary", {
            total: result.total,
            valid: result.valid,
            created: result.created,
            skipped: result.skipped,
            failed: result.failed,
          }),
        );
        onImported();
      }
    } catch (err) {
      setReport(null);
      setError(normalizeApiError(err, "student import"));
    } finally {
      setBusy(null);
    }
  };

  const handleTemplate = async () => {
    try {
      downloadBlob(await studentApi.importTemplate(), "student-import-template.csv");
    } catch (err) {
      setError(normalizeApiError(err, "import template"));
    }
  };

  const localized = localizeError(error);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2">
            <label
              htmlFor="student-import-file"
              className="block text-sm font-medium"
            >
              {t("chooseFile")}
            </label>
            <input
              id="student-import-file"
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
            <Button type="button" variant="ghost" size="sm" onClick={handleTemplate}>
              {t("template")}
            </Button>
          </div>

          {error && <ErrorState title={localized.message} hint={localized.hint} />}

          {report && (
            <div className="space-y-3">
              <p className="text-sm">{t("summary", {
                total: report.total,
                valid: report.valid,
                created: report.created,
                skipped: report.skipped,
                failed: report.failed,
              })}</p>

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
                  <thead className="bg-muted/50 text-start">
                    <tr>
                      <th className="p-2 text-start font-medium">{t("rowHeader")}</th>
                      <th className="p-2 text-start font-medium">{t("numberHeader")}</th>
                      <th className="p-2 text-start font-medium">{t("resultHeader")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows.map((row) => (
                      <tr key={row.row_number} className="border-t">
                        <td className="p-2 tabular-nums">{row.row_number}</td>
                        <td className="p-2 font-mono">{row.student_number ?? "—"}</td>
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

              {report.accounts && report.created > 0 && (
                <div className="space-y-1.5 rounded-md border p-3">
                  <p className="text-sm font-medium">{t("accountsHeading")}</p>
                  <p className="text-xs text-muted-foreground">
                    {t("accountsHint")}
                  </p>
                  <ul className="space-y-0.5 text-xs">
                    <li>
                      {t("accountsCreated", {
                        count: report.accounts.created ?? 0,
                      })}
                    </li>
                    <li>
                      {t("accountsAwaitingActivation", {
                        count: report.accounts.activation_required ?? 0,
                      })}
                    </li>
                    {(report.accounts.matched ?? 0) > 0 && (
                      <li>
                        {t("accountsMatched", {
                          count: report.accounts.matched,
                        })}
                      </li>
                    )}
                    {(report.accounts.missing_contact ?? 0) > 0 && (
                      <li className="text-destructive">
                        {t("accountsMissingContact", {
                          count: report.accounts.missing_contact,
                        })}
                      </li>
                    )}
                    {(report.accounts.ambiguous ?? 0) > 0 && (
                      <li className="text-destructive">
                        {t("accountsAmbiguous", {
                          count: report.accounts.ambiguous,
                        })}
                      </li>
                    )}
                  </ul>
                </div>
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
            onClick={() => run(true)}
            disabled={!file || busy !== null}
          >
            {busy === "validate" ? t("running") : t("validate")}
          </Button>
          <Button onClick={() => run(false)} disabled={!file || busy !== null}>
            {busy === "import" ? t("running") : t("run")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
