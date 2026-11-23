"use client";

import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

interface LoadingStateProps {
  /** Overrides the localized default. Pass a translated string when a more
   *  specific message helps, e.g. "Loading students". */
  message?: string;
  className?: string;
}

export function LoadingState({ message, className }: LoadingStateProps) {
  const t = useTranslations("common.states");
  return (
    <div
      className={cn("flex flex-col items-center justify-center p-8", className)}
      role="status"
      aria-live="polite"
    >
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" aria-hidden="true" />
      <p className="mt-4 text-sm text-muted-foreground">{message ?? t("loading")}</p>
    </div>
  );
}
