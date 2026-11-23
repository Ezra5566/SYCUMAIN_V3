"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { AlertCircle } from "lucide-react";
import { StatusPage } from "@/components/ui/status-page";

/**
 * Locale-level error boundary.
 *
 * `error.message` is deliberately not rendered: the API and server diagnostics
 * can contain implementation detail. The developer still gets the full error
 * in the console during development, and server logs retain the trace.
 */
export default function LocaleError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("errors");

  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      console.error("[ui] route error", error);
    }
  }, [error]);

  return (
    <StatusPage
      title={t("generic")}
      description={t("genericHint")}
      icon={AlertCircle}
      primaryAction={{ label: t("backToDashboard"), href: "/app" }}
      secondaryAction={{ label: t("contactSupport"), href: "/app/support" }}
    >
      <button
        type="button"
        onClick={reset}
        className="mt-3 inline-flex h-9 items-center justify-center rounded-lg px-3 text-xs font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {t("retry")}
      </button>
    </StatusPage>
  );
}
