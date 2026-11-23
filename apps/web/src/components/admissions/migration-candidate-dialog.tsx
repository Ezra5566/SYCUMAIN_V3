"use client";

import { useCallback, useId, useState } from "react";
import { useTranslations } from "next-intl";
import { admissionApi } from "@/lib/admission-api";
import { listPeriods, listProgramOfferings } from "@/lib/academic-api";
import { studentApi } from "@/lib/student-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/search-input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";
import type { MigrationQueueItem } from "@/types/admission";
import type { AcademicPeriod, PaginatedList, ProgramOffering } from "@/types/academic";
import type { StudentListResponse } from "@/types/student";

interface MigrationCandidateDialogProps {
  /** Present when correcting a candidate; omitted when adding one. */
  candidate?: MigrationQueueItem;
  onClose: () => void;
  onSaved: () => void;
}

/**
 * Candidate creation and correction.
 *
 * Both modes call the existing migrated-admission endpoints. The form only
 * collects a student, intake and offering; the backend derives the admitted
 * programme, enforces intake/offering consistency and decides which candidates
 * are still editable.
 */
export function MigrationCandidateDialog({
  candidate,
  onClose,
  onSaved,
}: MigrationCandidateDialogProps) {
  const t = useTranslations("admissionVerification");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const editing = !!candidate;
  const studentSelectId = useId();
  const intakeSelectId = useId();
  const offeringSelectId = useId();

  const [studentSearch, setStudentSearch] = useState("");
  const [studentId, setStudentId] = useState(candidate?.student_id ?? "");
  const [intakeId, setIntakeId] = useState(
    candidate?.admission_intake_id ?? "",
  );
  const [offeringId, setOfferingId] = useState(
    candidate?.admitted_program_offering_id ?? "",
  );
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const fetchStudents = useCallback(() => {
    if (editing) return Promise.resolve(null);
    return studentApi.listStudents({
      search: studentSearch.trim() || undefined,
      page_size: 25,
    });
  }, [editing, studentSearch]);
  const students = useApi<StudentListResponse | null>(
    fetchStudents,
    [editing, studentSearch],
    "candidate student search",
  );

  const fetchPeriods = useCallback(() => listPeriods(1, 100), []);
  const periods = useApi<PaginatedList<AcademicPeriod>>(
    fetchPeriods,
    [],
    "candidate intakes",
  );

  const fetchOfferings = useCallback(
    () =>
      intakeId
        ? listProgramOfferings(intakeId, undefined, 1, 100)
        : Promise.resolve(null),
    [intakeId],
  );
  const offerings = useApi<PaginatedList<ProgramOffering> | null>(
    fetchOfferings,
    [intakeId],
    "candidate offerings",
  );

  const canSubmit = !!studentId && !!intakeId && !!offeringId && !busy;

  async function submit() {
    setBusy(true);
    setFailure(null);
    try {
      if (candidate) {
        await admissionApi.updateCandidate(candidate.student_id, candidate.admission_id, {
          admission_intake_id: intakeId,
          program_offering_id: offeringId,
        });
        toast.success(t("candidate.successEdit"));
      } else {
        await admissionApi.createCandidate(studentId, {
          admission_intake_id: intakeId,
          program_offering_id: offeringId,
        });
        toast.success(t("candidate.successCreate"));
      }
      onSaved();
      onClose();
    } catch (error) {
      setFailure(normalizeApiError(error, "migration candidate form"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {editing ? t("candidate.editTitle") : t("candidate.createTitle")}
          </DialogTitle>
          <DialogDescription>
            {editing
              ? t("candidate.editDescription")
              : t("candidate.createDescription")}
          </DialogDescription>
        </DialogHeader>

        {editing && candidate ? (
          <div className="rounded-lg border border-border/80 bg-muted/25 p-3 text-sm">
            <p className="font-medium">{candidate.student_name}</p>
            <p className="font-mono text-xs text-muted-foreground" dir="ltr">
              {candidate.student_number}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="space-y-1.5 text-sm">
              <span className="font-medium">{t("candidate.findStudent")}</span>
              <SearchInput
                value={studentSearch}
                onChange={setStudentSearch}
                label={t("candidate.findStudent")}
                placeholder={t("candidate.searchStudent")}
              />
            </div>
            <div className="space-y-1.5 text-sm">
              <label htmlFor={studentSelectId} className="font-medium">
                {t("candidate.student")}
              </label>
              <select
                id={studentSelectId}
                value={studentId}
                onChange={(event) => setStudentId(event.target.value)}
                className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm"
              >
                <option value="">{t("candidate.selectStudent")}</option>
                {(students.data?.items ?? []).map((student) => (
                  <option key={student.id} value={student.id}>
                    {student.first_name} {student.last_name} ·{" "}
                    {student.student_id}
                  </option>
                ))}
              </select>
            </div>
            {students.data && students.data.items.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t("candidate.noStudents")}
              </p>
            )}
          </div>
        )}

        <div className="space-y-1.5 text-sm">
          <label htmlFor={intakeSelectId} className="font-medium">
            {t("candidate.intake")}
          </label>
          <select
            id={intakeSelectId}
            value={intakeId}
            onChange={(event) => {
              setIntakeId(event.target.value);
              setOfferingId("");
            }}
            className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm"
          >
            <option value="">{t("candidate.selectIntake")}</option>
            {(periods.data?.items ?? []).map((period) => (
              <option key={period.id} value={period.id}>
                {period.name} · {period.code}
              </option>
            ))}
          </select>
        </div>

        <div className="space-y-1.5 text-sm">
          <label htmlFor={offeringSelectId} className="font-medium">
            {t("candidate.offering")}
          </label>
          <select
            id={offeringSelectId}
            value={offeringId}
            onChange={(event) => setOfferingId(event.target.value)}
            disabled={!intakeId || offerings.loading}
            className="h-10 w-full rounded-lg border border-input bg-card px-3 text-sm disabled:cursor-not-allowed disabled:opacity-60"
          >
            <option value="">{t("candidate.selectOffering")}</option>
            {(offerings.data?.items ?? []).map((offering) => (
              <option
                key={offering.id}
                value={offering.id}
                disabled={!offering.selectable}
              >
                {offering.name}
                {offering.selectable ? "" : ` · ${t("candidate.offeringUnavailable")}`}
              </option>
            ))}
          </select>
          {intakeId &&
            offerings.data &&
            offerings.data.items.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t("candidate.noOfferings")}
              </p>
            )}
        </div>

        {(periods.error || offerings.error || students.error) && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(
              periods.error ?? offerings.error ?? students.error,
            ).message}
          </p>
        )}
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={() => void submit()} disabled={!canSubmit}>
            {busy
              ? tCommon("states.saving")
              : editing
                ? t("candidate.submitEdit")
                : t("candidate.submitCreate")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
