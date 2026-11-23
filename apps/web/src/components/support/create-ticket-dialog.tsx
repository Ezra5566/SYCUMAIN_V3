"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { supportApi } from "@/lib/platform-api";
import { studentApi } from "@/lib/student-api";
import { useApi } from "@/lib/use-api";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { useAuth } from "@/lib/auth-context";
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
import { Textarea } from "@/components/ui/textarea";
import { FilterSelect } from "@/components/ui/filter-select";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import type { SupportTicketCategory } from "@/types/platform";

const CATEGORIES: SupportTicketCategory[] = [
  "VISA_IMMIGRATION",
  "HOUSING",
  "ACADEMIC",
  "FINANCE",
  "IT",
  "GENERAL",
];

interface CreateTicketDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

/**
 * Open a support ticket.
 *
 * A student always files for themselves — the backend resolves their student
 * record from the session. Staff may file on behalf of a student, which is the
 * only case where a student selector appears. The selected id is still
 * re-validated server-side.
 */
export function CreateTicketDialog({
  open,
  onOpenChange,
  onCreated,
}: CreateTicketDialogProps) {
  const t = useTranslations("support");
  const tCommon = useTranslations("common");
  const { hasRole } = useAuth();
  const localizeError = useErrorMessage();

  const isStaff = hasRole("ADMIN") || hasRole("MANAGEMENT") || hasRole("TEACHER");

  const [category, setCategory] = useState<SupportTicketCategory>("GENERAL");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [studentSearch, setStudentSearch] = useState("");
  const [studentId, setStudentId] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);

  const fetchStudents = useCallback(
    () =>
      studentApi.listStudents({
        page: 1,
        page_size: 25,
        search: studentSearch || undefined,
      }),
    [studentSearch],
  );

  const { data: students } = useApi(
    fetchStudents,
    [studentSearch],
    "student picker",
  );

  const studentOptions = useMemo(
    () => [
      { value: "", label: tCommon("labels.selectPlaceholder") },
      ...(students?.items ?? []).map((student) => ({
        value: student.id,
        label: `${student.last_name}, ${student.first_name} (${student.student_id})`,
      })),
    ],
    [students, tCommon],
  );

  const canSubmit =
    subject.trim().length >= 3 && description.trim().length >= 10 && !saving;

  const handleSubmit = async () => {
    setSaving(true);
    setError(null);
    try {
      await supportApi.create({
        category,
        subject: subject.trim(),
        description: description.trim(),
        student_id: isStaff && studentId ? studentId : undefined,
      });
      toast.success(t("createSucceeded"));
      setSubject("");
      setDescription("");
      setStudentId("");
      onCreated();
    } catch (err) {
      setError(normalizeApiError(err, "create support ticket"));
    } finally {
      setSaving(false);
    }
  };

  const localized = localizeError(error);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("newTicketTitle")}</DialogTitle>
          <DialogDescription>{t("subtitle")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <FilterSelect
            label={t("category")}
            value={category}
            showLabel
            options={CATEGORIES.map((value) => ({
              value,
              label: t(`categories.${value}`),
            }))}
            onChange={(value) => setCategory(value as SupportTicketCategory)}
          />

          {isStaff && (
            <div className="space-y-2">
              <Input
                value={studentSearch}
                onChange={(event) => setStudentSearch(event.target.value)}
                placeholder={tCommon("labels.searchPlaceholder")}
                aria-label={tCommon("labels.search")}
              />
              <FilterSelect
                label={tCommon("labels.name")}
                value={studentId}
                options={studentOptions}
                showLabel
                onChange={setStudentId}
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="ticket-subject" className="text-sm font-medium">
              {t("subject")}
            </label>
            <Input
              id="ticket-subject"
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              placeholder={t("subjectPlaceholder")}
              maxLength={255}
              required
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="ticket-description" className="text-sm font-medium">
              {t("description")}
            </label>
            <Textarea
              id="ticket-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t("descriptionPlaceholder")}
              rows={6}
              maxLength={5000}
              required
            />
          </div>

          {error && <ErrorState title={localized.message} hint={localized.hint} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {saving ? tCommon("states.submitting") : tCommon("actions.submit")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
