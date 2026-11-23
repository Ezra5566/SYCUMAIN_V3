"use client";

import { useCallback, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Archive, Download, Upload } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { documentApi } from "@/lib/platform-api";
import { useApi } from "@/lib/use-api";
import { normalizeApiError } from "@/lib/api-error";
import { useErrorMessage } from "@/lib/use-error-message";
import { useStatusLabel } from "@/lib/use-status-label";
import { formatFileSize } from "@/lib/format";
import { AppShell } from "@/components/layout/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { FilterSelect } from "@/components/ui/filter-select";
import { DataTable, type Column } from "@/components/ui/data-table";
import { StatusBadge, toneForStatus } from "@/components/ui/status-badge";
import { Pagination } from "@/components/ui/pagination";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { toast } from "@/components/ui/toast";
import { UploadDocumentDialog } from "@/components/documents/upload-dialog";
import { FileTypeIcon } from "@/components/documents/file-type-icon";
import { PreviewTrigger } from "@/components/documents/document-preview-dialog";
import type { DocumentListResponse, PortalDocument } from "@/types/platform";

const DOCUMENT_TYPES = [
  "PASSPORT",
  "VISA",
  "RESIDENCE_PERMIT",
  "PHOTO",
  "TRANSCRIPT",
  "OTHER",
];

const PAGE_SIZE = 20;

export default function DocumentsPage() {
  const t = useTranslations("documents");
  const tCommon = useTranslations("common");
  const locale = useLocale();
  const { hasPermission } = useAuth();
  const localizeError = useErrorMessage();
  const statusLabel = useStatusLabel();

  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [uploading, setUploading] = useState(false);

  const canUpload = hasPermission("documents.upload");
  const canManage = hasPermission("documents.manage");

  const fetchDocuments = useCallback(
    () =>
      documentApi.list({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        document_type: typeFilter || undefined,
      }),
    [page, search, typeFilter],
  );

  const { data, loading, error, refetch } = useApi<DocumentListResponse>(
    fetchDocuments,
    [page, search, typeFilter],
    "documents",
  );

  const typeOptions = useMemo(
    () => [
      { value: "", label: `${t("documentType")} — ${tCommon("labels.all")}` },
      ...DOCUMENT_TYPES.map((value) => ({ value, label: t(`types.${value}`) })),
    ],
    [t, tCommon],
  );

  const localized = localizeError(error);
  const documents = data?.items ?? [];
  const totalPages =
    data && data.page_size > 0
      ? Math.max(1, Math.ceil(data.total / data.page_size))
      : 1;

  const download = async (document: PortalDocument) => {
    try {
      await documentApi.download(document.id, document.original_filename);
      toast.success(t("downloadStarted"));
    } catch (err) {
      const normalized = normalizeApiError(err, "download document");
      toast.error(
        normalized.kind === "forbidden"
          ? t("downloadDenied")
          : localizeError(normalized).message,
      );
    }
  };

  const archive = async (id: string) => {
    try {
      await documentApi.archive(id);
      toast.success(tCommon("actions.archive"));
      refetch();
    } catch (err) {
      toast.error(localizeError(normalizeApiError(err, "archive document")).message);
    }
  };

  const previewable = (document: PortalDocument) =>
    document.content_type === "application/pdf" ||
    document.content_type.startsWith("image/");

  const columns: Column<PortalDocument>[] = [
    {
      key: "title",
      header: tCommon("labels.name"),
      cell: (document) => (
        <div className="flex min-w-0 items-center gap-3">
          <FileTypeIcon
            filename={document.original_filename}
            contentType={document.content_type}
          />
          <div className="min-w-0">
            <p className="truncate font-medium">{document.title}</p>
            <p className="truncate text-xs text-muted-foreground" dir="ltr">
              {document.original_filename}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: "type",
      header: t("documentType"),
      cell: (document) => statusLabel(document.document_type, "documents.types"),
    },
    {
      key: "student",
      header: t("studentName"),
      hideOnMobile: true,
      cell: (document) => document.student_name ?? tCommon("states.notSet"),
    },
    {
      key: "size",
      header: t("fileSize"),
      hideOnMobile: true,
      cell: (document) => (
        <span className="tabular-nums">{formatFileSize(document.file_size)}</span>
      ),
    },
    {
      key: "review",
      header: t("reviewStatusHeading"),
      cell: (document) => (
        <StatusBadge tone={toneForStatus(document.review_status)}>
          {statusLabel(document.review_status, "documents.reviewStatus")}
        </StatusBadge>
      ),
    },
    {
      key: "status",
      header: tCommon("labels.status"),
      cell: (document) => (
        <StatusBadge tone={toneForStatus(document.status)}>
          {t(`status.${document.status}`)}
        </StatusBadge>
      ),
    },
    {
      key: "uploaded",
      header: t("uploadedAt"),
      hideOnMobile: true,
      cell: (document) =>
        new Date(document.created_at).toLocaleDateString(locale),
    },
    {
      key: "actions",
      header: tCommon("labels.actions"),
      className: "text-end",
      cell: (document) => (
        <div className="flex justify-end gap-1">
          {previewable(document) && (
            <PreviewTrigger document={document} label={t("preview")} />
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => download(document)}
            aria-label={`${t("download")} ${document.title}`}
          >
            <Download className="h-4 w-4" aria-hidden="true" />
          </Button>
          {canManage && document.review_status !== "APPROVED" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => archive(document.id)}
              aria-label={`${tCommon("actions.archive")} ${document.title}`}
            >
              <Archive className="h-4 w-4" aria-hidden="true" />
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
        actions={
          canUpload ? (
            <Button size="sm" onClick={() => setUploading(true)}>
              <Upload className="me-1.5 h-4 w-4" aria-hidden="true" />
              {t("upload")}
            </Button>
          ) : undefined
        }
      />

      <p className="mb-4 text-sm text-muted-foreground">{t("privateNotice")}</p>

      <Card className="mb-4">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setPage(1);
            }}
            placeholder={tCommon("labels.searchPlaceholder")}
            className="sm:max-w-sm sm:flex-1"
          />
          <FilterSelect
            label={t("documentType")}
            value={typeFilter}
            options={typeOptions}
            onChange={(value) => {
              setTypeFilter(value);
              setPage(1);
            }}
            className="sm:w-64"
          />
        </CardContent>
      </Card>

      {error?.kind === "forbidden" ? (
        <EmptyState title={t("downloadDenied")} />
      ) : error ? (
        <ErrorState
          title={localized.message}
          hint={localized.hint}
          onRetry={refetch}
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={documents}
            rowKey={(document) => document.id}
            loading={loading}
            error={null}
            emptyTitle={t("empty")}
            emptyMessage={t("emptyHint")}
            mobileCard={(document) => (
              <div className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <FileTypeIcon
                      filename={document.original_filename}
                      contentType={document.content_type}
                    />
                    <div className="min-w-0">
                      <p className="truncate font-medium">{document.title}</p>
                      <p className="truncate text-xs text-muted-foreground" dir="ltr">
                        {document.original_filename}
                      </p>
                    </div>
                  </div>
                  <StatusBadge tone={toneForStatus(document.status)}>
                    {t(`status.${document.status}`)}
                  </StatusBadge>
                </div>
                <p className="text-sm text-muted-foreground">
                  {statusLabel(document.document_type, "documents.types")} ·{" "}
                  {formatFileSize(document.file_size)}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => download(document)}
                >
                  <Download className="me-1.5 h-4 w-4" aria-hidden="true" />
                  {t("download")}
                </Button>
                {previewable(document) && (
                  <PreviewTrigger document={document} label={t("preview")} />
                )}
              </div>
            )}
          />

          {data && data.total > PAGE_SIZE && (
            <Pagination
              page={data.page}
              pageSize={data.page_size}
              total={data.total}
              totalPages={totalPages}
              onPageChange={setPage}
            />
          )}
        </>
      )}

      {canUpload && (
        <UploadDocumentDialog
          open={uploading}
          onOpenChange={setUploading}
          onUploaded={() => {
            setUploading(false);
            refetch();
          }}
        />
      )}
    </AppShell>
  );
}
