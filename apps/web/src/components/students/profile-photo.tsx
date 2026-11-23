"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Maximize2, Upload, User, X } from "lucide-react";
import { studentApi } from "@/lib/student-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { ImageLightbox } from "@/components/ui/image-lightbox";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

/**
 * Student profile photo.
 *
 * The API serves the image only through `GET /students/{id}/photo`, behind the
 * same authorization check as the rest of the record, and returns no URL. So the
 * bytes are fetched with the session cookie and rendered from a blob URL that
 * this component creates and revokes — an `<img src>` pointing at a guessable
 * public path would make the photo exactly as private as the naming scheme.
 */

interface ProfilePhotoProps {
  studentId: string;
  hasPhoto: boolean;
  fullName: string;
  /** Caller decides this from `student.edit` / own-record self-service. */
  canEdit: boolean;
  onChanged: () => Promise<void> | void;
}

export function ProfilePhoto({
  studentId,
  hasPhoto,
  fullName,
  canEdit,
  onChanged,
}: ProfilePhotoProps) {
  const t = useTranslations("studentProfile");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<NormalizedError | null>(null);

  useEffect(() => {
    let revoked = false;
    let created: string | null = null;

    if (!hasPhoto) {
      setObjectUrl(null);
      return;
    }

    studentApi
      .fetchPhoto(studentId)
      .then((blob) => {
        if (revoked || !blob) return;
        created = URL.createObjectURL(blob);
        setObjectUrl(created);
      })
      .catch(() => {
        // A photo that cannot be fetched is not worth an error banner: the
        // initials fallback below is a perfectly good answer.
        if (!revoked) setObjectUrl(null);
      });

    return () => {
      revoked = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [studentId, hasPhoto]);

  const upload = useCallback(
    async (file: File) => {
      setBusy(true);
      setFailure(null);
      try {
        await studentApi.uploadPhoto(studentId, file);
        toast.success(t("photoUpdated"));
        await onChanged();
      } catch (error) {
        setFailure(normalizeApiError(error, "upload"));
      } finally {
        setBusy(false);
      }
    },
    [studentId, onChanged, t],
  );

  const initials = fullName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative h-28 w-28 shrink-0 overflow-hidden rounded-full border border-border bg-muted shadow-sm">
        {objectUrl ? (
          <button
            type="button"
            onClick={() => setViewerOpen(true)}
            className="group relative block h-full w-full cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
            aria-label={t("viewPhoto")}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- the blob URL is created at runtime. */}
            <img
              src={objectUrl}
              alt={fullName}
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]"
            />
            <span
              className="absolute inset-0 grid place-items-center bg-black/0 text-white opacity-0 transition-all duration-200 group-hover:bg-black/35 group-hover:opacity-100 group-focus-visible:bg-black/35 group-focus-visible:opacity-100"
              aria-hidden="true"
            >
              <Maximize2 className="h-5 w-5" />
            </span>
          </button>
        ) : (
          <div
            className="flex h-full w-full items-center justify-center"
            role="img"
            aria-label={t("noPhoto")}
          >
            {initials ? (
              <span className="text-3xl font-semibold tracking-wide text-gold">
                {initials}
              </span>
            ) : (
              <User className="h-10 w-10 text-gold/80" aria-hidden="true" />
            )}
          </div>
        )}
      </div>

      {objectUrl && (
        <ImageLightbox
          src={objectUrl}
          alt={fullName}
          open={viewerOpen}
          onOpenChange={setViewerOpen}
          caption={t("photoPreviewHint")}
          downloadName={`${fullName}.jpg`}
        />
      )}

      {canEdit && (
        <div className="flex flex-wrap items-center justify-center gap-2">
          <label
            className={cn(
              "inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-md border border-border/80 bg-card px-2.5 text-[11px] font-medium text-foreground shadow-sm transition-colors hover:border-primary/30 hover:bg-accent",
              busy && "pointer-events-none opacity-55",
            )}
          >
            <Upload className="h-3.5 w-3.5" aria-hidden="true" />
            {busy ? tCommon("states.uploading") : t("changePhoto")}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={busy}
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                // Reset so choosing the same file twice still fires a change.
                event.target.value = "";
                if (file) void upload(file);
              }}
            />
          </label>
          {hasPhoto && (
            <ConfirmDialog
              title={t("removePhotoTitle")}
              description={t("removePhotoDescription")}
              confirmLabel={tCommon("actions.remove")}
              triggerLabel={t("removePhoto")}
              triggerIcon={<X className="h-4 w-4" aria-hidden="true" />}
              variant="destructive"
              size="icon"
              disabled={busy}
              onConfirm={() => studentApi.removePhoto(studentId)}
              onDone={onChanged}
            />
          )}
        </div>
      )}

      {busy && (
        <p role="status" className="text-xs text-muted-foreground">
          {tCommon("states.uploading")}
        </p>
      )}
      {failure && (
        <p role="alert" className="text-xs text-destructive">
          {localizeError(failure).message}
        </p>
      )}
    </div>
  );
}
