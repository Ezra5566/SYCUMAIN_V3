"use client";

import { useTranslations } from "next-intl";
import { Compass } from "lucide-react";
import { StatusPage } from "@/components/ui/status-page";

/**
 * Localized 404.
 *
 * Lives under `[locale]` so it renders inside the locale layout and therefore
 * has translations and the correct `dir` available. Middleware rewrites an
 * unknown locale prefix into a known locale, so this is the page users actually
 * land on for a bad URL.
 */
export default function NotFoundPage() {
  const t = useTranslations("errors");

  return (
    <StatusPage
      title={t("notFound")}
      description={t("notFoundHint")}
      icon={Compass}
      primaryAction={{ label: t("backToDashboard"), href: "/app" }}
      secondaryAction={{ label: t("contactSupport"), href: "/app/support" }}
    />
  );
}
