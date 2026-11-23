"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Upload } from "lucide-react";
import { documentApi } from "@/lib/platform-api";
import { studentApi } from "@/lib/student-api";
import { useApi } from "@/lib/use-api";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { useAuth } from "@/lib/auth-context";
import { formatFileSize } from "@/lib/format";
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

interface UploadDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded: () => void;
  /**
   * Pre-selects the student the file belongs to.
   *
   * Opening the dialog from a student's profile must not require re-finding
   * that student in the picker — that is how a student's file ends up attached
   * to whichever record the picker happened to list first.
   */
  studentId?: string;
  /** Pre-selects the category, e.g. when filled from a required-document row. */
  initialType?: string;
}

/**
 * Upload a document into private storage.
 *
 * The file is validated again on the server (size, magic number, declared
 * type), so nothing here is a security control — these checks only avoid an
 * obviously doomed round trip.
 */
export function UploadDocumentDialog({
  open,
  onOpenChange,
  onUploaded,
  studentId: presetStudentId,
  initialType,
}: UploadDialogProps) {
  const t = useTranslations("documents");
  const tCommon = useTranslations("common");
  const { hasRole } = useAuth();
  const localizeError = useErrorMessage();

  const isStaff = hasRole("ADMIN") || hasRole("MANAGEMENT") || hasRole("TEACHER");
  // With the student already known, the picker is only shown to staff who are
  // filing on someone else's behalf from the global documents list.
  const showStudentPicker = isStaff && !presetStudentId;

  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<string>("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [studentSearch, setStudentSearch] = useState("");
  const [studentId, setStudentId] = useState(presetStudentId ?? "");
  const [studentVisible, setStudentVisible] = useState(true);
  const [uploading, setUploading] = useState(false);
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
    showStudentPicker ? fetchStudents : () => Promise.resolve(null),
    [studentSearch, showStudentPicker],
    "student picker",
  );

  // The category vocabulary is served by the API rather than hard-coded here:
  // the column is a free string that never needed a migration to extend, and a
  // second copy of the list in the browser is exactly how a new category ends
  // up unreachable from the form that is supposed to create it.
  const { data: typeData } = useApi(
    () => documentApi.types(),
    [],
    "document types",
  );

  const typeOptions = useMemo(
    () =>
      (typeData?.items ?? []).map((option) => ({
        value: option.value,
        label: t(option.label_key),
      })),
    [typeData, t],
  );

  // Prefer the caller's choice, then the first category the API offers, so the
  // form is valid as soon as it opens without the UI picking a favourite.
  const effectiveType =
    documentType || initialType || typeOptions[0]?.value || "";

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
    Boolean(file) && title.trim().length > 0 && effectiveType !== "" && !uploading;

  const handleSubmit = async () => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      await documentApi.upload({
        file,
        document_type: effectiveType,
        title: title.trim(),
        description: description.trim() || undefined,
        student_id: studentId || undefined,
        student_visible: isStaff ? studentVisible : true,
      });
      toast.success(t("uploadSucceeded"));
      setFile(null);
      setTitle("");
      setDescription("");
      setStudentId("");
      onUploaded();
    } catch (err) {
      setError(normalizeApiError(err, "upload document"));
    } finally {
      setUploading(false);
    }
  };

  const localized = localizeError(error);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("uploadTitle")}</DialogTitle>
          <DialogDescription>{t("privateNotice")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="document-file"
              className="flex cursor-pointer items-center justify-between gap-3 rounded-md border border-input bg-background px-3 py-2 shadow-sm transition-colors hover:border-primary/30 hover:bg-accent/40 focus-within:ring-2 focus-within:ring-ring"
            >
              <span className="flex min-w-0 items-center gap-2.5">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/5 text-primary">
                  <Upload className="h-3.5 w-3.5" aria-hidden="true" />
                </span>
                <span className="truncate text-sm font-medium">
                  {file ? file.name : t("selectFile")}
                </span>
              </span>
              <span className="shrink-0 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                PDF · JPG · PNG
              </span>
              <input
                id="document-file"
                type="file"
                accept=".pdf,.jpg,.jpeg,.png"
                className="sr-only"
                onChange={(event) => {
                  const selected = event.target.files?.[0] ?? null;
                  setFile(selected);
                  if (selected && !title) {
                    setTitle(selected.name.replace(/\.[^.]+$/, ""));
                  }
                }}
              />
            </label>
            {file && (
              <p className="text-xs text-muted-foreground">
                {t("selectedFile")}: {file.name} · {formatFileSize(file.size)}
              </p>
            )}
          </div>

          <FilterSelect
            label={t("documentType")}
            value={effectiveType}
            showLabel
            options={typeOptions}
            onChange={setDocumentType}
          />

          <div className="space-y-1.5">
            <label htmlFor="document-title" className="text-sm font-medium">
              {tCommon("labels.name")}
            </label>
            <Input
              id="document-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              maxLength={255}
              required
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="document-description" className="text-sm font-medium">
              {tCommon("labels.description")}
            </label>
            <Textarea
              id="document-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              maxLength={2000}
            />
          </div>

          {showStudentPicker && (
            <div className="space-y-2 rounded-md border p-3">
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
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={studentVisible}
                  onChange={(event) => setStudentVisible(event.target.checked)}
                  className="h-4 w-4 rounded border-input"
                />
                {t("studentVisible")}
              </label>
            </div>
          )}

          {error && <ErrorState title={localized.message} hint={localized.hint} />}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.cancel")}
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            <Upload className="me-1.5 h-4 w-4" aria-hidden="true" />
            {uploading ? tCommon("states.uploading") : tCommon("actions.upload")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
