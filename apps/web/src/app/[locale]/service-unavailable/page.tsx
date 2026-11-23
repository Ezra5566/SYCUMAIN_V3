"use client";

import { useTranslations } from "next-intl";
import { ServerOff } from "lucide-react";
import { StatusPage } from "@/components/ui/status-page";

export default function ServiceUnavailablePage() {
  const t = useTranslations("errors");
  const tAuth = useTranslations("auth");

  return (
    <StatusPage
      title={t("serverError")}
      description={t("serverErrorHint")}
      icon={ServerOff}
      primaryAction={{ label: tAuth("signIn"), href: "/login" }}
      secondaryAction={{ label: t("backToDashboard"), href: "/app" }}
    />
  );
}
