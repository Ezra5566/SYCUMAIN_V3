"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Download, Eye, Loader2, ZoomIn, ZoomOut } from "lucide-react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { documentApi } from "@/lib/platform-api";
import { formatFileSize } from "@/lib/format";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { PdfPreviewPages } from "@/components/documents/pdf-preview";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { PortalDocument } from "@/types/platform";

/**
 * Authorized inline preview.
 *
 * The bytes are fetched with the session cookie and displayed locally; no
 * public or presigned URL is created. PDFs are rendered to canvas by PDF.js
 * rather than handed to a browser plugin, because an embedded viewer is not
 * guaranteed to exist (and is commonly absent in Chromium automation). Only
 * server-validated PDF and image types reach this component, and the API
 * re-checks authorization, scan clearance and object presence on every
 * request.
 */
export function DocumentPreviewDialog({
  document,
  open,
  onOpenChange,
}: {
  document: PortalDocument;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("documents");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();
  const [url, setUrl] = useState<string | null>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);
  const [renderFailed, setRenderFailed] = useState(false);
  const [zoom, setZoom] = useState(1);

  const handlePdfError = useCallback(() => setRenderFailed(true), []);

  useEffect(() => {
    if (!open) return;
    let active = true;
    let objectUrl: string | null = null;
    let loadedPdf: PDFDocumentProxy | null = null;
    setLoading(true);
    setFailure(null);
    setRenderFailed(false);
    setUrl(null);
    setPdf(null);
    setZoom(1);

    const load = async () => {
      let blob: Blob;
      try {
        ({ blob } = await documentApi.preview(document.id));
      } catch (error) {
        if (active) {
          setFailure(normalizeApiError(error, "preview document"));
          setLoading(false);
        }
        return;
      }

      if (!active) return;

      try {
        if (document.content_type === "application/pdf") {
          // Load the browser ESM build directly from the public assets. Bundling
          // pdf.js through the development server's eval-based source maps
          // breaks its module wrapper before any document is parsed.
          const pdfjsUrl = "/pdfjs/pdf.min.mjs";
          const pdfjs = (await import(
            /* webpackIgnore: true */ pdfjsUrl
          )) as typeof import("pdfjs-dist");
          pdfjs.GlobalWorkerOptions.workerSrc = "/pdfjs/pdf.worker.min.mjs";
          const task = pdfjs.getDocument({
            data: new Uint8Array(await blob.arrayBuffer()),
            cMapUrl: "/pdfjs/cmaps/",
            cMapPacked: true,
            standardFontDataUrl: "/pdfjs/standard_fonts/",
          });
          loadedPdf = await task.promise;
          if (!active) {
            void loadedPdf.destroy();
            return;
          }
          setPdf(loadedPdf);
        } else if (document.content_type.startsWith("image/")) {
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
        } else {
          setRenderFailed(true);
        }
      } catch (error) {
        console.error("Document preview render failed", error);
        if (active) setRenderFailed(true);
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      if (loadedPdf) void loadedPdf.destroy();
    };
  }, [document.content_type, document.id, open]);

  const localized = failure ? localizeError(failure) : null;
  const isImage = document.content_type.startsWith("image/");
  const hasPreview = Boolean(pdf || url);
  const zoomPercent = `${Math.round(zoom * 100)}%`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* The preview area alone is 55vh; without a height bound the footer is
          pushed below the viewport on laptop screens and its Close and Download
          buttons cannot be reached, because the page behind is scroll-locked. */}
      <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("previewTitle", { title: document.title })}</DialogTitle>
          <DialogDescription>
            {document.original_filename} · {formatFileSize(document.file_size)}
            {pdf ? ` · ${t("previewPages", { count: pdf.numPages })}` : ""}
          </DialogDescription>
        </DialogHeader>

        {hasPreview && !renderFailed && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/20 px-2 py-1.5">
            <p className="text-xs text-muted-foreground">{t("previewZoomHint")}</p>
            <div className="flex items-center gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0"
                aria-label={t("zoomOut")}
                onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))}
                disabled={zoom <= 0.5}
              >
                <ZoomOut className="h-4 w-4" aria-hidden="true" />
              </Button>
              <button
                type="button"
                className="min-w-12 rounded px-1 text-xs tabular-nums text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => setZoom(1)}
                aria-label={t("zoomReset")}
              >
                {zoomPercent}
              </button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 w-8 p-0"
                aria-label={t("zoomIn")}
                onClick={() => setZoom((value) => Math.min(2.5, value + 0.25))}
                disabled={zoom >= 2.5}
              >
                <ZoomIn className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </div>
        )}

        <div className="min-h-[55vh] overflow-auto rounded-lg border bg-muted/20">
          {loading ? (
            <div className="flex h-[55vh] items-center justify-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              {tCommon("states.loading")}
            </div>
          ) : localized ? (
            <div className="flex h-[55vh] items-center justify-center p-6 text-center">
              <div>
                <p className="text-sm font-medium text-destructive">{localized.message}</p>
                <p className="mt-1 text-xs text-muted-foreground">{localized.hint}</p>
              </div>
            </div>
          ) : renderFailed ? (
            <div className="flex h-[55vh] items-center justify-center p-6 text-center">
              <div className="max-w-md">
                <p className="text-sm font-medium">{t("previewRenderFailed")}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("previewRenderFailedHint")}
                </p>
              </div>
            </div>
          ) : pdf ? (
            <div className="min-h-[55vh]">
              <PdfPreviewPages
                document={pdf}
                zoom={zoom}
                onError={handlePdfError}
              />
            </div>
          ) : url && isImage ? (
            <div className="flex min-h-[55vh] justify-center p-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={url}
                alt={document.title}
                className="h-auto max-w-none object-contain"
                style={{ width: `${zoom * 100}%` }}
              />
            </div>
          ) : (
            <div className="flex h-[55vh] items-center justify-center text-sm text-muted-foreground">
              {t("previewUnavailable")}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tCommon("actions.close")}
          </Button>
          <Button onClick={() => void documentApi.download(document.id, document.original_filename)}>
            <Download className="me-1.5 h-4 w-4" aria-hidden="true" />
            {tCommon("actions.download")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function PreviewTrigger({
  document,
  label,
}: {
  document: PortalDocument;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <Eye className="me-1 h-4 w-4" aria-hidden="true" />
        {label}
      </Button>
      <DocumentPreviewDialog
        document={document}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  );
}
