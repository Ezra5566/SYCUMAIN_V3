"use client";

import { useTranslations } from "next-intl";
import { Inbox } from "lucide-react";
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title?: string;
  message?: string;
  /** Optional call to action rendered under the text. */
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({ title, message, action, className }: EmptyStateProps) {
  const t = useTranslations("common.states");
  return (
    <div className={cn("motion-enter flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      <span className="scu-empty__plate">
        <Inbox className="h-5 w-5" aria-hidden="true" />
      </span>
      <h3 className="mt-4 text-base font-semibold tracking-[-0.01em]">
        {title ?? t("empty")}
      </h3>
      <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted-foreground">
        {message ?? t("emptyHint")}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
