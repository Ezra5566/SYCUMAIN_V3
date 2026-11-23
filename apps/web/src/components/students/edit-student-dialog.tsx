"use client";

import { useEffect, useState } from "react";
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
import { Input } from "@/components/ui/input";
import { FilterSelect } from "@/components/ui/filter-select";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import type { StudentDetail, StudentStatus, StudentUpdate } from "@/types/student";

const STATUSES: StudentStatus[] = [
  "ACTIVE",
  "INACTIVE",
  "GRADUATED",
  "WITHDRAWN",
  "SUSPENDED",
];

interface EditStudentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  student: StudentDetail;
  onSaved: (updated: StudentDetail) => void;
}

interface FormState {
  firstName: string;
  lastName: string;
  preferredName: string;
  dateOfBirth: string;
  gender: string;
  nationality: string;
  phone: string;
  emergencyContactName: string;
  emergencyContactPhone: string;
  status: StudentStatus;
}

const GENDERS = ["", "FEMALE", "MALE", "OTHER"];

/** `datetime` input value (yyyy-mm-dd) from an ISO timestamp. */
function toDateInput(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "";
}

function toForm(student: StudentDetail): FormState {
  return {
    firstName: student.first_name,
    lastName: student.last_name,
    preferredName: student.preferred_name ?? "",
    dateOfBirth: toDateInput(student.date_of_birth),
    gender: student.gender ?? "",
    nationality: student.nationality ?? "",
    phone: student.phone ?? "",
    emergencyContactName: student.emergency_contact_name ?? "",
    emergencyContactPhone: student.emergency_contact_phone ?? "",
    status: student.status,
  };
}

/**
 * Edit a student record as staff.
 *
 * Only changed fields are sent. The student number is deliberately not
 * editable: it is an institutional identifier that other records reference, so
 * treating it as mutable would break the trail. Status is edited here too, but
 * through the dedicated status endpoint so the change is audited separately.
 */
export function EditStudentDialog({
  open,
  onOpenChange,
  student,
  onSaved,
}: EditStudentDialogProps) {
  const t = useTranslations("students.edit");
  const tCommon = useTranslations("common");
  const tValidation = useTranslations("validation");
  const tStudents = useTranslations("students");
  const localizeError = useErrorMessage();

  const [form, setForm] = useState<FormState>(() => toForm(student));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);
  // Re-seed the form whenever a different student is opened, so a stale draft
  // from the previous record can never be submitted.
  useEffect(() => {
    if (!open) return;
    setForm(toForm(student));
    setError(null);
  }, [open, student]);

  const set = <K extends keyof FormState>(field: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [field]: value }));

  const nameMissing = !form.firstName.trim() || !form.lastName.trim();
  const canSubmit = !nameMissing && !saving;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSaving(true);
    setError(null);

    try {
      const original = toForm(student);
      const payload: StudentUpdate = {};

      if (form.firstName !== original.firstName)
        payload.first_name = form.firstName.trim();
      if (form.lastName !== original.lastName)
        payload.last_name = form.lastName.trim();
      if (form.preferredName !== original.preferredName)
        payload.preferred_name = form.preferredName.trim();
      if (form.dateOfBirth !== original.dateOfBirth)
        payload.date_of_birth = form.dateOfBirth
          ? new Date(form.dateOfBirth).toISOString()
          : undefined;
      if (form.gender !== original.gender)
        payload.gender = form.gender || undefined;
      if (form.nationality !== original.nationality)
        payload.nationality = form.nationality.trim();
      if (form.phone !== original.phone) payload.phone = form.phone.trim();
      if (form.emergencyContactName !== original.emergencyContactName)
        payload.emergency_contact_name = form.emergencyContactName.trim();
      if (form.emergencyContactPhone !== original.emergencyContactPhone)
        payload.emergency_contact_phone = form.emergencyContactPhone.trim();

      const statusChanged = form.status !== original.status;

      // A no-op save is not an error, but it is also not worth a request.
      if (
        Object.keys(payload).length === 0 &&
        !statusChanged
      ) {
        toast.info(tStudents("noChanges"));
        setSaving(false);
        onOpenChange(false);
        return;
      }

      let updated = student;
      if (Object.keys(payload).length > 0) {
        updated = await studentApi.updateStudent(student.id, payload);
      }
      if (statusChanged) {
        updated = await studentApi.setStatus(student.id, form.status);
      }

      toast.success(tStudents("updated"));
      onSaved(updated);
      onOpenChange(false);
    } catch (err) {
      setError(normalizeApiError(err, "update student"));
    } finally {
      setSaving(false);
    }
  };

  const localized = localizeError(error);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>
            {t("studentNumberNotice", { number: student.student_id })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="edit-first-name"
              label={tStudents("fields.firstName")}
              value={form.firstName}
              onChange={(value) => set("firstName", value)}
              error={!form.firstName.trim() ? tValidation("required") : ""}
              required
            />
            <Field
              id="edit-last-name"
              label={tStudents("fields.lastName")}
              value={form.lastName}
              onChange={(value) => set("lastName", value)}
              error={!form.lastName.trim() ? tValidation("required") : ""}
              required
            />
            <Field
              id="edit-preferred-name"
              label={tStudents("fields.preferredName")}
              value={form.preferredName}
              onChange={(value) => set("preferredName", value)}
            />
            <Field
              id="edit-dob"
              label={tStudents("fields.dateOfBirth")}
              type="date"
              value={form.dateOfBirth}
              onChange={(value) => set("dateOfBirth", value)}
            />
            <FilterSelect
              label={tStudents("fields.gender")}
              value={form.gender}
              showLabel
              options={GENDERS.map((value) => ({
                value,
                label: value
                  ? tStudents(`gender.${value}`)
                  : tCommon("states.notSet"),
              }))}
              onChange={(value) => set("gender", value)}
            />
            <Field
              id="edit-nationality"
              label={tStudents("fields.nationality")}
              value={form.nationality}
              onChange={(value) => set("nationality", value)}
            />
            <Field
              id="edit-phone"
              label={tStudents("fields.phone")}
              value={form.phone}
              onChange={(value) => set("phone", value)}
            />
            <FilterSelect
              label={tStudents("fields.status")}
              value={form.status}
              showLabel
              options={STATUSES.map((value) => ({
                value,
                label: tStudents(`status.${value}`),
              }))}
              onChange={(value) => set("status", value as StudentStatus)}
            />
            <Field
              id="edit-emergency-name"
              label={tStudents("fields.emergencyContactName")}
              value={form.emergencyContactName}
              onChange={(value) => set("emergencyContactName", value)}
            />
            <Field
              id="edit-emergency-phone"
              label={tStudents("fields.emergencyContactPhone")}
              value={form.emergencyContactPhone}
              onChange={(value) => set("emergencyContactPhone", value)}
            />
          </div>

          {error && <ErrorState title={localized.message} hint={localized.hint} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {saving ? tCommon("states.saving") : tCommon("actions.save")}
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
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  required,
  error,
}: FieldProps) {
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
        aria-required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
      />
      {error && (
        <p id={`${id}-error`} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
