"use client";

import { useCallback, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import {
  AlertTriangle,
  Check,
  Download,
  RefreshCw,
  Upload,
  X,
} from "lucide-react";
import { documentApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { formatFileSize } from "@/lib/format";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { UploadDocumentDialog } from "@/components/documents/upload-dialog";
import { PreviewTrigger } from "@/components/documents/document-preview-dialog";
import { FileTypeIcon } from "@/components/documents/file-type-icon";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { LoadingState } from "@/components/ui/loading-state";
import { toast } from "@/components/ui/toast";
import type { PortalDocument, RequiredDocumentStatus } from "@/types/platform";

/**
 * Student profile → Documents.
 *
 * The tab answers the question the international office actually asks — "is
 * this student's file complete?" — rather than listing files. Completeness is
 * the API's answer (`/documents/students/{id}/summary`): it knows which
 * categories are institutionally required and derives MISSING from the absence
 * of a current document, so a category the school adds tomorrow appears here
 * with no frontend change.
 *
 * Students see their own file and may add to it. Staff additionally see the
 * review controls. Both go through the same authorization-checked endpoints;
 * `canManage` only decides whether a button is offered, never whether the
 * request would be allowed.
 */

interface DocumentsTabProps {
  studentId: string;
  canUpload: boolean;
  canManage: boolean;
}

export function DocumentsTab({
  studentId,
  canUpload,
  canManage,
}: DocumentsTabProps) {
  const t = useTranslations("documents");
  const tInstitutional = useTranslations("institutional");
  const tCommon = useTranslations("common");
  const format = useFormatter();
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  const { data, loading, error, refetch } = useApi(
    () => documentApi.summary(studentId),
    [studentId],
    "student documents",
  );

  const download = useCallback(
    async (document: PortalDocument) => {
      setBusyId(document.id);
      setFailure(null);
      try {
        await documentApi.download(document.id, document.original_filename);
      } catch (err) {
        setFailure(normalizeApiError(err, "download"));
      } finally {
        setBusyId(null);
      }
    },
    [],
  );

  const review = useCallback(
    async (
      documentId: string,
      decision:
        | "APPROVED"
        | "REJECTED"
        | "UNDER_REVIEW"
        | "REPLACEMENT_REQUIRED",
      note?: string,
    ) => {
      await documentApi.review(documentId, { decision, note });
      toast.success(t("reviewSaved"));
      await refetch();
    },
    [refetch, t],
  );

  const localized = localizeError(error);

  if (loading) return <LoadingState />;
  if (error) {
    return <ErrorState message={localized.message} hint={localized.hint} onRetry={refetch} />;
  }
  if (!data) return <EmptyState title={t("empty")} message={t("emptyHint")} />;

  const documents = data.other;

  return (
    <div className="space-y-6">
      {failure && <ErrorState message={localizeError(failure).message} />}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {data.missing_count > 0 && (
            <StatusBadge tone="danger">
              {t("countMissing", { count: data.missing_count })}
            </StatusBadge>
          )}
          {data.pending_count > 0 && (
            <StatusBadge tone="warning">
              {t("countPending", { count: data.pending_count })}
            </StatusBadge>
          )}
          {data.expired_count + data.expiring_count > 0 && (
            <StatusBadge tone="warning">
              {t("countExpiring", { count: data.expired_count + data.expiring_count })}
            </StatusBadge>
          )}
        </div>
        {canUpload && (
          <Button onClick={() => setUploadOpen(true)}>
            <Upload className="me-1 h-4 w-4" aria-hidden="true" />
            {t("upload")}
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("requiredHeading")}</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {data.required.length === 0 ? (
            <EmptyState title={t("noRequired")} />
          ) : (
            <ul className="divide-y">
              {data.required.map((item) => (
                <RequiredRow
                  key={item.document_type}
                  item={item}
                  studentId={studentId}
                  canUpload={canUpload}
                  onUploaded={refetch}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("otherHeading")}</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {documents.length === 0 ? (
            <EmptyState title={t("empty")} message={t("emptyHint")} />
          ) : (
            <ul className="divide-y">
              {documents.map((document) => (
                <li
                  key={document.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3"
                >
                  <div className="flex min-w-0 items-start gap-3">
                    <FileTypeIcon
                      filename={document.original_filename}
                      contentType={document.content_type}
                    />
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{document.title}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {t(`types.${document.document_type}`)} ·{" "}
                        {document.original_filename} ·{" "}
                        {formatFileSize(document.file_size)}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {t("uploadedAt")}:{" "}
                        {format.dateTime(new Date(document.created_at), {
                          dateStyle: "medium",
                        })}
                      </p>
                      {document.review_note && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t("reviewNote")}: {document.review_note}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    <StatusBadge tone={toneForStatus(document.review_status)}>
                      {statusLabel(document.review_status, "documents.reviewStatus")}
                    </StatusBadge>
                    {document.expires_on && (
                      <StatusBadge
                        tone={
                          new Date(document.expires_on) < new Date()
                            ? "danger"
                            : "neutral"
                        }
                      >
                        {t("expiresOn", {
                          date: format.dateTime(new Date(document.expires_on), {
                            dateStyle: "medium",
                          }),
                        })}
                      </StatusBadge>
                    )}

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => void download(document)}
                      disabled={busyId === document.id}
                    >
                      <Download className="me-1 h-4 w-4" aria-hidden="true" />
                      {tCommon("actions.download")}
                    </Button>

                    {(document.content_type === "application/pdf" ||
                      document.content_type.startsWith("image/")) && (
                      <PreviewTrigger document={document} label={t("preview")} />
                    )}

                    {canUpload && (
                      <ReplaceDocumentButton
                        document={document}
                        onReplaced={refetch}
                      />
                    )}

                    {canManage &&
                      document.scan_status === "CLEAN" &&
                      document.review_status === "PENDING" && (
                      <ConfirmDialog
                        title={tInstitutional("startReviewTitle")}
                        description={tInstitutional("startReviewDescription", {
                          title: document.title,
                        })}
                        confirmLabel={tInstitutional("startReview")}
                        triggerLabel={tInstitutional("startReview")}
                        triggerIcon={<Check className="h-4 w-4" aria-hidden="true" />}
                        variant="outline"
                        onConfirm={() => review(document.id, "UNDER_REVIEW")}
                      />
                    )}

                    {canManage &&
                      document.scan_status === "CLEAN" &&
                      document.review_status === "UNDER_REVIEW" && (
                      <>
                        <ConfirmDialog
                          title={t("approveTitle")}
                          description={t("approveDescription", { title: document.title })}
                          confirmLabel={tCommon("actions.approve")}
                          triggerLabel={tCommon("actions.approve")}
                          triggerIcon={<Check className="h-4 w-4" aria-hidden="true" />}
                          variant="outline"
                          onConfirm={() => review(document.id, "APPROVED")}
                        />
                        <RejectDocumentButton
                          document={document}
                          onRejected={(note) => review(document.id, "REJECTED", note)}
                        />
                        <RequestReplacementButton
                          document={document}
                          onRequested={(note) =>
                            review(document.id, "REPLACEMENT_REQUIRED", note)
                          }
                        />
                      </>
                    )}
                    {document.scan_status !== "CLEAN" && (
                      <StatusBadge tone="warning">
                        {t(`scanStatus.${document.scan_status}`)}
                      </StatusBadge>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <UploadDocumentDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        onUploaded={refetch}
        studentId={studentId}
      />
    </div>
  );
}

/**
 * A required category.
 *
 * The state comes from the API; this only decides the wording and whether to
 * offer a way to satisfy it. `document_id` is present once anything has been
 * supplied, which is what makes "download what they sent" possible from here.
 */
function RequiredRow({
  item,
  studentId,
  canUpload,
  onUploaded,
}: {
  item: RequiredDocumentStatus;
  studentId: string;
  canUpload: boolean;
  onUploaded: () => Promise<void> | void;
}) {
  const t = useTranslations("documents");
  const statusLabel = useStatusLabel();

  const satisfied = item.state === "APPROVED";

  return (
    <li className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div className="flex min-w-0 items-center gap-3">
        {satisfied ? (
          <Check className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
        ) : (
          <AlertTriangle className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        )}
        <div className="min-w-0">
          <p className="text-sm font-medium">{t(`types.${item.document_type}`)}</p>
          {item.title && (
            <p className="truncate text-xs text-muted-foreground">{item.title}</p>
          )}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <StatusBadge tone={toneForStatus(item.state)}>
          {statusLabel(item.state, "documents.requirementState")}
        </StatusBadge>
        {canUpload &&
          ["MISSING", "REJECTED", "REPLACEMENT_REQUIRED"].includes(item.state) && (
          <UploadForStudentButton
            studentId={studentId}
            documentType={item.document_type}
            onUploaded={onUploaded}
          />
        )}
      </div>
    </li>
  );
}

/**
 * Uploading from the required list, pre-set to the category being filled.
 *
 * Without this a clerk has to remember which category the row was about and
 * re-pick it in the dialog, which is how a residence permit ends up filed as a
 * passport.
 */
function UploadForStudentButton({
  studentId,
  documentType,
  onUploaded,
}: {
  studentId: string;
  documentType: string;
  onUploaded: () => Promise<void> | void;
}) {
  const t = useTranslations("documents");
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Upload className="me-1 h-4 w-4" aria-hidden="true" />
        {t("upload")}
      </Button>
      <UploadDocumentDialog
        open={open}
        onOpenChange={setOpen}
        onUploaded={onUploaded}
        studentId={studentId}
        initialType={documentType}
      />
    </>
  );
}

function ReplaceDocumentButton({
  document,
  onReplaced,
}: {
  document: PortalDocument;
  onReplaced: () => Promise<void> | void;
}) {
  const t = useTranslations("documents");
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const localizeError = useErrorMessage();

  async function submit() {
    if (!file) return;
    setBusy(true);
    setFailure(null);
    try {
      await documentApi.replace(document.id, { file, title: document.title });
      toast.success(t("replaceSucceeded"));
      await onReplaced();
      setOpen(false);
      setFile(null);
    } catch (err) {
      setFailure(normalizeApiError(err, "upload"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <ConfirmDialog
      title={t("replaceTitle")}
      description={t("replaceDescription", { title: document.title })}
      confirmLabel={busy ? t("replacing") : t("replace")}
      triggerLabel={t("replace")}
      triggerIcon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
      onConfirm={submit}
      disabled={busy}
      confirmDisabled={!file}
      variant="outline"
    >
      <div className="space-y-2">
        <Input
          type="file"
          accept=".pdf,.jpg,.jpeg,.png"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          className="file:me-3 cursor-pointer"
          aria-label={t("selectFile")}
        />
        <p className="text-xs text-muted-foreground">{t("replaceKeepsHistory")}</p>
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {localizeError(failure).message}
          </p>
        )}
      </div>
    </ConfirmDialog>
  );
}

function RequestReplacementButton({
  document,
  onRequested,
}: {
  document: PortalDocument;
  onRequested: (note: string) => Promise<void>;
}) {
  const t = useTranslations("institutional");
  const tCommon = useTranslations("common");
  const [note, setNote] = useState("");

  return (
    <ConfirmDialog
      title={t("requestReplacementTitle")}
      description={t("requestReplacementDescription", { title: document.title })}
      confirmLabel={t("requestReplacement")}
      triggerLabel={t("requestReplacement")}
      triggerIcon={<RefreshCw className="h-4 w-4" aria-hidden="true" />}
      confirmDisabled={note.trim().length === 0}
      variant="outline"
      onConfirm={async () => {
        await onRequested(note.trim());
        setNote("");
      }}
    >
      <div className="space-y-1.5">
        <label htmlFor="replacement-note" className="text-sm font-medium">
          {t("replacementNoteLabel")}
        </label>
        <Input
          id="replacement-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          maxLength={2000}
        />
        <p className="text-xs text-muted-foreground">
          {t("replacementNoteHint")}
        </p>
      </div>
    </ConfirmDialog>
  );
}

function RejectDocumentButton({
  document,
  onRejected,
}: {
  document: PortalDocument;
  onRejected: (note: string) => Promise<void>;
}) {
  const t = useTranslations("documents");
  const tCommon = useTranslations("common");
  const [note, setNote] = useState("");

  return (
    <ConfirmDialog
      title={t("rejectTitle")}
      description={t("rejectDescription", { title: document.title })}
      confirmLabel={tCommon("actions.reject")}
      triggerLabel={tCommon("actions.reject")}
      triggerIcon={<X className="h-4 w-4" aria-hidden="true" />}
      // The API refuses a rejection with no reason, so the button stays
      // disabled rather than letting the user submit a request that must fail.
      confirmDisabled={note.trim().length === 0}
      variant="outline"
      onConfirm={async () => {
        await onRejected(note.trim());
        setNote("");
      }}
    >
      <div className="space-y-1.5">
        <label htmlFor="reject-note" className="text-sm font-medium">
          {t("rejectNoteLabel")}
        </label>
        <Input
          id="reject-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          maxLength={2000}
        />
        <p className="text-xs text-muted-foreground">{t("rejectNoteHint")}</p>
      </div>
    </ConfirmDialog>
  );
}
