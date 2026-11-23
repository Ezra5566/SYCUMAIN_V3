"use client";

import { useTranslations } from "next-intl";
import { Clock3 } from "lucide-react";
import { StatusPage } from "@/components/ui/status-page";

export default function SessionExpiredPage() {
  const t = useTranslations("errors");
  const tAuth = useTranslations("auth");

  return (
    <StatusPage
      title={tAuth("sessionExpired")}
      description={t("unauthorizedHint")}
      icon={Clock3}
      primaryAction={{ label: tAuth("signIn"), href: "/login" }}
      secondaryAction={{ label: t("backToDashboard"), href: "/app" }}
    />
  );
}
