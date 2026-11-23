"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { studentApi } from "@/lib/student-api";
import { listPeriods, listProgramOfferings } from "@/lib/academic-api";
import { useApi } from "@/lib/use-api";
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
import { Input } from "@/components/ui/input";
import { FilterSelect } from "@/components/ui/filter-select";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import type { StudentOnboardedResponse } from "@/types/student";

interface OnboardStudentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

interface FormState {
  studentId: string;
  firstName: string;
  lastName: string;
  email: string;
  preferredName: string;
  nationality: string;
  phone: string;
  periodId: string;
  offeringId: string;
}

const EMPTY: FormState = {
  studentId: "",
  firstName: "",
  lastName: "",
  email: "",
  preferredName: "",
  nationality: "",
  phone: "",
  periodId: "",
  offeringId: "",
};

/** Matches the backend rule: something@domain.tld, no spaces. */
const EMAIL_PATTERN = /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/;

/**
 * Onboard a student and their login account in one step.
 *
 * The backend creates both in a single transaction and returns a one-time
 * temporary password. That password is shown here once and cannot be retrieved
 * again — the administrator hands it to the student, who must change it on
 * first sign-in.
 */
export function OnboardStudentDialog({
  open,
  onOpenChange,
  onCreated,
}: OnboardStudentDialogProps) {
  const t = useTranslations("students.onboard");
  const tStudents = useTranslations("students");
  const tCommon = useTranslations("common");
  const tValidation = useTranslations("validation");
  const localizeError = useErrorMessage();

  const [form, setForm] = useState<FormState>(EMPTY);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [result, setResult] = useState<StudentOnboardedResponse | null>(null);
  const periods = useApi(() => listPeriods(1, 100), [], "intake periods");
  const fetchOfferings = useCallback(
    () =>
      form.periodId
        ? listProgramOfferings(form.periodId, undefined, 1, 100)
        : Promise.resolve(null),
    [form.periodId],
  );
  const offerings = useApi(fetchOfferings, [form.periodId], "program offerings");

  const set = (field: keyof FormState, value: string) =>
    setForm((current) => ({ ...current, [field]: value }));

  const errors = {
    studentId: form.studentId.trim() ? "" : tValidation("required"),
    firstName: form.firstName.trim() ? "" : tValidation("required"),
    lastName: form.lastName.trim() ? "" : tValidation("required"),
    email: !form.email.trim()
      ? tValidation("required")
      : EMAIL_PATTERN.test(form.email.trim())
        ? ""
        : tValidation("email"),
  };

  const activePeriods = (periods.data?.items ?? []).filter(
    (period) => period.status === "ACTIVE" || period.status === "PLANNED",
  );
  const canSubmit =
    Object.values(errors).every((message) => !message) && !saving;

  const offeringOptions = (offerings.data?.items ?? [])
    .filter((offering) => offering.selectable !== false)
    .map((offering) => ({ value: offering.id, label: offering.name }));

  const reset = () => {
    setForm(EMPTY);
    setTouched({});
    setError(null);
    setResult(null);
  };

  const handleClose = (next: boolean) => {
    if (saving) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const handleSubmit = async () => {
    setTouched({
      studentId: true,
      firstName: true,
      lastName: true,
      email: true,
    });
    if (!canSubmit) return;

    setSaving(true);
    setError(null);
    try {
      const created = await studentApi.onboardStudent({
        student_id: form.studentId.trim(),
        first_name: form.firstName.trim(),
        last_name: form.lastName.trim(),
        email: form.email.trim().toLowerCase(),
        preferred_name: form.preferredName.trim() || undefined,
        nationality: form.nationality.trim() || undefined,
        phone: form.phone.trim() || undefined,
        program_offering_id: form.offeringId || undefined,
        // Onboarding creates an active student record; a first admission with
        // an offering must be explicitly ADMITTED or ACTIVE on the backend.
        initial_admission_status: form.offeringId ? "ACTIVE" : undefined,
      });
      setResult(created);
      toast.success(t("created"));
      onCreated();
    } catch (err) {
      setError(normalizeApiError(err, "onboard student"));
    } finally {
      setSaving(false);
    }
  };

  const localized = localizeError(error);

  /** Second phase: show the credential that must be handed over. */
  if (result) {
    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("credentialsTitle")}</DialogTitle>
            <DialogDescription>{t("credentialsNotice")}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <dl className="space-y-2 rounded-md border bg-muted/40 p-3 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">
                  {tStudents("fields.studentNumber")}
                </dt>
                <dd className="font-mono">{result.student.student_id}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">
                  {tStudents("fields.email")}
                </dt>
                <dd className="truncate font-mono">{result.account.email}</dd>
              </div>
            </dl>

            <div className="space-y-1.5">
              <p className="text-sm font-medium">{t("temporaryPassword")}</p>
              <p
                // A credential is a value to copy verbatim, so pin it LTR even
                // when the interface is Arabic.
                dir="ltr"
                data-testid="temporary-password"
                className="select-all break-all rounded-md border border-dashed bg-background px-3 py-2 font-mono text-sm"
              >
                {result.temporary_password}
              </p>
              <p className="text-xs text-muted-foreground">
                {t("passwordShownOnce")}
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button onClick={() => handleClose(false)}>
              {tCommon("actions.done")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="onboard-student-id"
              label={tStudents("fields.studentNumber")}
              value={form.studentId}
              error={touched.studentId ? errors.studentId : ""}
              onBlur={() => setTouched((c) => ({ ...c, studentId: true }))}
              onChange={(value) => set("studentId", value)}
              required
            />
            <Field
              id="onboard-nationality"
              label={tStudents("fields.nationality")}
              value={form.nationality}
              onChange={(value) => set("nationality", value)}
            />
            <Field
              id="onboard-first-name"
              label={tStudents("fields.firstName")}
              value={form.firstName}
              error={touched.firstName ? errors.firstName : ""}
              onBlur={() => setTouched((c) => ({ ...c, firstName: true }))}
              onChange={(value) => set("firstName", value)}
              required
            />
            <Field
              id="onboard-last-name"
              label={tStudents("fields.lastName")}
              value={form.lastName}
              error={touched.lastName ? errors.lastName : ""}
              onBlur={() => setTouched((c) => ({ ...c, lastName: true }))}
              onChange={(value) => set("lastName", value)}
              required
            />
            <Field
              id="onboard-preferred-name"
              label={tStudents("fields.preferredName")}
              value={form.preferredName}
              onChange={(value) => set("preferredName", value)}
            />
            <Field
              id="onboard-phone"
              label={tStudents("fields.phone")}
              value={form.phone}
              onChange={(value) => set("phone", value)}
            />
          </div>

          <Field
            id="onboard-email"
            label={tStudents("fields.email")}
            type="email"
            value={form.email}
            error={touched.email ? errors.email : ""}
            onBlur={() => setTouched((c) => ({ ...c, email: true }))}
            onChange={(value) => set("email", value)}
            hint={t("emailHint")}
            required
          />

          <div className="grid gap-4 sm:grid-cols-2">
            <FilterSelect
              label={t("intakePeriod")}
              value={form.periodId}
              showLabel
              options={[
                { value: "", label: tCommon("labels.selectPlaceholder") },
                ...activePeriods.map((period) => ({
                  value: period.id,
                  label: `${period.name} (${period.code})`,
                })),
              ]}
              onChange={(value) =>
                setForm((current) => ({
                  ...current,
                  periodId: value,
                  offeringId: "",
                }))
              }
            />
            <FilterSelect
              label={t("programOffering")}
              value={form.offeringId}
              showLabel
              options={[
                {
                  value: "",
                  label: offerings.loading
                    ? tCommon("states.loading")
                    : tCommon("labels.selectPlaceholder"),
                },
                ...offeringOptions,
              ]}
              onChange={(value) => set("offeringId", value)}
            />
          </div>
          {activePeriods.length > 0 && offeringOptions.length === 0 && (
            <p className="text-xs text-muted-foreground">{t("noOfferings")}</p>
          )}

          {error && <ErrorState title={localized.message} hint={localized.hint} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => handleClose(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {saving ? tCommon("states.saving") : tCommon("actions.create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface FieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  required?: boolean;
  error?: string;
  hint?: string;
  onBlur?: () => void;
}

/**
 * One labelled input with inline validation messaging.
 *
 * Errors are wired through `aria-describedby` so a screen reader announces the
 * reason a field was rejected, not just that it was.
 */
function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  required,
  error,
  hint,
  onBlur,
}: FieldProps) {
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
        {required && (
          <span aria-hidden="true" className="ms-0.5 text-destructive">
            *
          </span>
        )}
      </label>
      <Input
        id={id}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        aria-required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
      />
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
