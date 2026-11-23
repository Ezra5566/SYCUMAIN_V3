"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { studentApi } from "@/lib/student-api";
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
import { FilterSelect } from "@/components/ui/filter-select";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import type { StudentBulkResponse, StudentStatus } from "@/types/student";

const STATUSES: StudentStatus[] = [
  "ACTIVE",
  "INACTIVE",
  "GRADUATED",
  "WITHDRAWN",
  "SUSPENDED",
];

interface BulkStatusDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  studentIds: string[];
  onApplied: () => void;
}

/**
 * Apply one enrolment status to a selection of students.
 *
 * The backend reports each student individually, so a mixed selection still
 * applies where allowed. Any refusal is surfaced here with its reason rather
 * than being silently dropped.
 */
export function BulkStatusDialog({
  open,
  onOpenChange,
  studentIds,
  onApplied,
}: BulkStatusDialogProps) {
  const t = useTranslations("students.bulk");
  const tStudents = useTranslations("students");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [status, setStatus] = useState<StudentStatus>("ACTIVE");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [result, setResult] = useState<StudentBulkResponse | null>(null);

  const handleClose = (next: boolean) => {
    if (saving) return;
    if (!next) {
      setResult(null);
      setError(null);
    }
    onOpenChange(next);
  };

  const handleApply = async () => {
    setSaving(true);
    setError(null);
    try {
      const response = await studentApi.bulkSetStatus(studentIds, status);
      setResult(response);
      if (response.succeeded > 0) {
        toast.success(
          t("applied", { count: response.succeeded, total: response.requested }),
        );
        onApplied();
      }
    } catch (err) {
      setError(normalizeApiError(err, "bulk status change"));
    } finally {
      setSaving(false);
    }
  };

  const localized = localizeError(error);
  const failures = result?.results.filter((item) => !item.ok) ?? [];

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>
            {t("description", { count: studentIds.length })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <FilterSelect
            label={t("newStatus")}
            value={status}
            showLabel
            options={STATUSES.map((value) => ({
              value,
              label: tStudents(`status.${value}`),
            }))}
            onChange={(value) => setStatus(value as StudentStatus)}
          />

          {error && <ErrorState title={localized.message} hint={localized.hint} />}

          {result && (
            <div className="space-y-2 rounded-md border p-3 text-sm">
              <p>
                {t("summary", {
                  succeeded: result.succeeded,
                  failed: result.failed,
                })}
              </p>
              {failures.length > 0 && (
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {failures.map((item) => (
                    <li key={item.student_id} className="font-mono">
                      {item.student_number ?? item.student_id}: {item.error}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleClose(false)}>
            {result ? tCommon("actions.close") : tCommon("actions.cancel")}
          </Button>
          {!result && (
            <Button onClick={handleApply} disabled={saving || studentIds.length === 0}>
              {saving ? tCommon("states.saving") : tCommon("actions.apply")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
