"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Download, RotateCw, X, ZoomIn, ZoomOut } from "lucide-react";
import { cn } from "@/lib/utils";

interface ImageLightboxProps {
  src: string;
  alt: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Small line under the image: file name, size, uploader — whatever the caller knows. */
  caption?: React.ReactNode;
  /** Offered only when the bytes are already in the browser. */
  downloadName?: string;
}

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;
const STEP = 0.25;

/**
 * Full-screen image viewer.
 *
 * Built directly on Radix Dialog primitives instead of the app Dialog so the
 * surface can be edge-to-edge without fighting the default padding, radius or
 * max-width. Zoom and pan live in transforms, so the image never reflows, and
 * every control is also reachable from the keyboard: +/- zoom, 0 resets, R
 * rotates, Escape closes (Radix). The scrim is darker than a normal dialog
 * because judging a photo or a scanned passport requires an uncluttered field.
 */
export function ImageLightbox({
  src,
  alt,
  open,
  onOpenChange,
  caption,
  downloadName,
}: ImageLightboxProps) {
  const [zoom, setZoom] = React.useState(1);
  const [rotation, setRotation] = React.useState(0);
  const [offset, setOffset] = React.useState({ x: 0, y: 0 });
  const [dragging, setDragging] = React.useState(false);
  const drag = React.useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const stageRef = React.useRef<HTMLDivElement>(null);

  const reset = React.useCallback(() => {
    setZoom(1);
    setRotation(0);
    setOffset({ x: 0, y: 0 });
  }, []);

  // Every opening starts from a clean frame; a previous zoom is not a setting.
  React.useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      if (event.key === "+" || event.key === "=") {
        setZoom((value) => Math.min(MAX_ZOOM, value + STEP));
      } else if (event.key === "-" || event.key === "_") {
        setZoom((value) => Math.max(MIN_ZOOM, value - STEP));
      } else if (event.key === "0") {
        reset();
      } else if (key === "r") {
        setRotation((value) => (value + 90) % 360);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, reset]);

  // Wheel zoom needs a non-passive listener; React's synthetic wheel handler
  // cannot prevent the page behind from scrolling.
  React.useEffect(() => {
    const stage = stageRef.current;
    if (!open || !stage) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const delta = event.deltaY < 0 ? STEP : -STEP;
      setZoom((value) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value + delta)));
    };
    stage.addEventListener("wheel", onWheel, { passive: false });
    return () => stage.removeEventListener("wheel", onWheel);
  }, [open]);

  const zoomPercent = `${Math.round(zoom * 100)}%`;

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="motion-overlay fixed inset-0 z-[70] bg-black/85 backdrop-blur-md" />
        <DialogPrimitive.Content
          className="motion-dialog fixed inset-0 z-[71] flex flex-col outline-none"
          aria-describedby={undefined}
        >
          <DialogPrimitive.Title className="sr-only">{alt}</DialogPrimitive.Title>

          <div className="flex items-center justify-between gap-3 px-4 py-3 text-white/90">
            <p className="min-w-0 truncate text-sm font-medium">{alt}</p>
            <div className="flex items-center gap-1.5">
              {downloadName && (
                <a
                  href={src}
                  download={downloadName}
                  className="scu-lightbox__btn"
                  aria-label={downloadName}
                  title={downloadName}
                >
                  <Download className="h-4 w-4" aria-hidden="true" />
                </a>
              )}
              <DialogPrimitive.Close className="scu-lightbox__btn" aria-label="Close">
                <X className="h-4 w-4" aria-hidden="true" />
              </DialogPrimitive.Close>
            </div>
          </div>

          <div
            ref={stageRef}
            className={cn(
              "relative flex flex-1 items-center justify-center overflow-hidden px-3",
              dragging ? "cursor-grabbing" : zoom > 1 ? "cursor-grab" : "cursor-zoom-in",
            )}
            onDoubleClick={() => (zoom > 1 ? reset() : setZoom(2))}
            onPointerDown={(event) => {
              if (zoom <= 1) return;
              drag.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y };
              setDragging(true);
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              const start = drag.current;
              if (!start) return;
              setOffset({
                x: start.ox + (event.clientX - start.x),
                y: start.oy + (event.clientY - start.y),
              });
            }}
            onPointerUp={(event) => {
              drag.current = null;
              setDragging(false);
              if (event.currentTarget.hasPointerCapture(event.pointerId)) {
                event.currentTarget.releasePointerCapture(event.pointerId);
              }
            }}
            onPointerCancel={() => {
              drag.current = null;
              setDragging(false);
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- the src is a session-fetched blob URL, never a public path. */}
            <img
              src={src}
              alt={alt}
              draggable={false}
              className="max-h-full max-w-full select-none object-contain shadow-[0_30px_80px_-40px_#000]"
              style={{
                transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom}) rotate(${rotation}deg)`,
                transition: dragging ? "none" : "transform 0.18s var(--ease)",
              }}
            />
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2 px-4 py-4">
            <div className="scu-lightbox__bar">
              <button
                type="button"
                className="scu-lightbox__btn"
                onClick={() => setZoom((value) => Math.max(MIN_ZOOM, value - STEP))}
                disabled={zoom <= MIN_ZOOM}
                aria-label="Zoom out"
              >
                <ZoomOut className="h-4 w-4" aria-hidden="true" />
              </button>
              <button
                type="button"
                className="min-w-14 rounded-md px-1 text-xs font-semibold tabular-nums text-white/85 hover:text-white"
                onClick={reset}
                aria-label="Reset zoom"
              >
                {zoomPercent}
              </button>
              <button
                type="button"
                className="scu-lightbox__btn"
                onClick={() => setZoom((value) => Math.min(MAX_ZOOM, value + STEP))}
                disabled={zoom >= MAX_ZOOM}
                aria-label="Zoom in"
              >
                <ZoomIn className="h-4 w-4" aria-hidden="true" />
              </button>
              <span className="mx-1 h-5 w-px bg-white/15" aria-hidden="true" />
              <button
                type="button"
                className="scu-lightbox__btn"
                onClick={() => setRotation((value) => (value + 90) % 360)}
                aria-label="Rotate"
              >
                <RotateCw className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            {caption && (
              <p className="w-full text-center text-xs text-white/60">{caption}</p>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
