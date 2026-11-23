"use client";

import { useTranslations } from "next-intl";
import { LogIn } from "lucide-react";
import { StatusPage } from "@/components/ui/status-page";

export default function UnauthorizedPage() {
  const t = useTranslations("errors");
  const tAuth = useTranslations("auth");

  return (
    <StatusPage
      title={t("signInRequired")}
      description={t("unauthorizedHint")}
      icon={LogIn}
      primaryAction={{ label: tAuth("signIn"), href: "/login" }}
      secondaryAction={{ label: t("backToDashboard"), href: "/app" }}
    />
  );
}
