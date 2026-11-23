"use client";

import { useTranslations } from "next-intl";
import { ShieldX } from "lucide-react";
import { StatusPage } from "@/components/ui/status-page";

export default function ForbiddenPage() {
  const t = useTranslations("errors");

  return (
    <StatusPage
      title={t("forbidden")}
      description={t("forbiddenHint")}
      icon={ShieldX}
      primaryAction={{ label: t("backToDashboard"), href: "/app" }}
      secondaryAction={{ label: t("contactSupport"), href: "/app/support" }}
    />
  );
}
