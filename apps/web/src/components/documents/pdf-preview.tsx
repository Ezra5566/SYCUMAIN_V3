"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";

/**
 * Canvas-based PDF pages.
 *
 * Browsers do not guarantee an embedded PDF viewer (and headless Chromium
 * commonly has none), so an iframe can stay blank even when the API returns a
 * valid file. PDF.js renders the same authorized bytes to canvas instead.
 */
export function PdfPreviewPages({
  document,
  zoom,
  onError,
}: {
  document: PDFDocumentProxy;
  zoom: number;
  onError: () => void;
}) {
  const canvases = useRef<Array<HTMLCanvasElement | null>>([]);
  const [rendering, setRendering] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const tasks: Array<{ cancel: () => void }> = [];

    const render = async () => {
      setRendering(true);
      try {
        for (let index = 0; index < document.numPages; index += 1) {
          if (cancelled) return;
          const page = await document.getPage(index + 1);
          if (cancelled) return;

          const base = page.getViewport({ scale: 1 });
          const cssWidth = Math.min(960, base.width) * zoom;
          const ratio = Math.min(window.devicePixelRatio || 1, 2);
          const viewport = page.getViewport({
            scale: (cssWidth / base.width) * ratio,
          });
          const canvas = canvases.current[index];
          if (!canvas) continue;

          const context = canvas.getContext("2d");
          if (!context) continue;
          canvas.width = Math.floor(viewport.width);
          canvas.height = Math.floor(viewport.height);
          canvas.style.width = `${Math.floor(cssWidth)}px`;
          canvas.style.height = `${Math.floor(viewport.height / ratio)}px`;

          const task = page.render({ canvas, canvasContext: context, viewport });
          tasks.push(task);
          await task.promise;
        }
      } catch {
        if (!cancelled) onError();
      } finally {
        if (!cancelled) setRendering(false);
      }
    };

    void render();
    return () => {
      cancelled = true;
      for (const task of tasks) task.cancel();
    };
  }, [document, zoom, onError]);

  return (
    <div className="relative flex min-h-full flex-col items-center gap-3 p-3 sm:p-5">
      {Array.from({ length: document.numPages }, (_, index) => (
        <div
          key={index}
          className="max-w-full overflow-hidden rounded-sm bg-white shadow-sm ring-1 ring-border/70"
        >
          <canvas
            ref={(node) => {
              canvases.current[index] = node;
            }}
            aria-label={`Page ${index + 1}`}
            className="block max-w-full"
          />
        </div>
      ))}
      {rendering && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background/40">
          <span
            className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent"
            role="status"
            aria-label="Rendering PDF"
          />
        </div>
      )}
    </div>
  );
}