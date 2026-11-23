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
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import type { StudentDetail } from "@/types/student";

interface SelfServiceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  student: StudentDetail;
  onSaved: (updated: StudentDetail) => void;
}

interface FormState {
  preferredName: string;
  phone: string;
  emergencyContactName: string;
  emergencyContactPhone: string;
}

function toForm(student: StudentDetail): FormState {
  return {
    preferredName: student.preferred_name ?? "",
    phone: student.phone ?? "",
    emergencyContactName: student.emergency_contact_name ?? "",
    emergencyContactPhone: student.emergency_contact_phone ?? "",
  };
}

/**
 * A student's own editable fields.
 *
 * Only the four fields the backend allows are offered here. The institutional
 * values on the same record — student number, official name, status, programme
 * — are shown read-only, because changing them is a management action. The
 * server enforces this independently; this form simply does not pretend
 * otherwise.
 */
export function SelfServiceDialog({
  open,
  onOpenChange,
  student,
  onSaved,
}: SelfServiceDialogProps) {
  const t = useTranslations("studentProfile.selfService");
  const tStudents = useTranslations("students");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [form, setForm] = useState<FormState>(() => toForm(student));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);

  useEffect(() => {
    if (open) {
      setForm(toForm(student));
      setError(null);
    }
  }, [open, student]);

  const set = <K extends keyof FormState>(field: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [field]: value }));

  const handleSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await studentApi.updateSelf(student.id, {
        preferred_name: form.preferredName.trim(),
        phone: form.phone.trim(),
        emergency_contact_name: form.emergencyContactName.trim(),
        emergency_contact_phone: form.emergencyContactPhone.trim(),
      });
      toast.success(t("saved"));
      onSaved(updated);
      onOpenChange(false);
    } catch (err) {
      setError(normalizeApiError(err, "update own profile"));
    } finally {
      setSaving(false);
    }
  };

  const localized = localizeError(error);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-2 rounded-md border bg-muted/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {t("readOnlyHeading")}
            </p>
            <dl className="grid gap-1 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">
                  {tStudents("fields.studentNumber")}
                </dt>
                <dd className="font-mono">{student.student_id}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">
                  {tStudents("fields.status")}
                </dt>
                <dd>{tStudents(`status.${student.status}`)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{tStudents("fields.name")}</dt>
                <dd>
                  {student.first_name} {student.last_name}
                </dd>
              </div>
            </dl>
            <p className="text-xs text-muted-foreground">{t("readOnlyHint")}</p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              id="self-preferred-name"
              label={tStudents("fields.preferredName")}
              value={form.preferredName}
              onChange={(value) => set("preferredName", value)}
            />
            <Field
              id="self-phone"
              label={tStudents("fields.phone")}
              value={form.phone}
              onChange={(value) => set("phone", value)}
            />
            <Field
              id="self-emergency-name"
              label={tStudents("fields.emergencyContactName")}
              value={form.emergencyContactName}
              onChange={(value) => set("emergencyContactName", value)}
            />
            <Field
              id="self-emergency-phone"
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
          <Button onClick={handleSubmit} disabled={saving}>
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
}

function Field({ id, label, value, onChange }: FieldProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}
