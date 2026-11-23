"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { AlertCircle, LockKeyhole } from "lucide-react";
import { HttpApiError } from "@/lib/api-error";
import { StatusPage } from "@/components/ui/status-page";

/** Error boundary for the authenticated app routes. */
export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("errors");

  // A page that the account is not allowed to read is not a crash. Showing
  // "Something went wrong" and a retry button for a 403 leaves the user
  // retrying a request that will never succeed; name the real condition and
  // offer a route they can actually use.
  const status =
    error instanceof HttpApiError
      ? error.status
      : (error as Error & { status?: number }).status;
  const forbidden = status === 403;

  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      console.error("[ui] app route error", error);
    }
  }, [error]);

  return (
    <StatusPage
      title={forbidden ? t("forbidden") : t("generic")}
      description={forbidden ? t("forbiddenHint") : t("genericHint")}
      icon={forbidden ? LockKeyhole : AlertCircle}
      primaryAction={{ label: t("backToDashboard"), href: "/app" }}
      secondaryAction={{ label: t("contactSupport"), href: "/app/support" }}
    >
      {!forbidden && (
        <button
          type="button"
          onClick={reset}
          className="mt-3 inline-flex h-9 items-center justify-center rounded-lg px-3 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {t("retry")}
        </button>
      )}
    </StatusPage>
  );
}
