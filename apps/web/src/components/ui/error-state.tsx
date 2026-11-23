"use client";

import { useTranslations } from "next-intl";
import { AlertCircle, LockKeyhole } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface ErrorStateProps {
  title?: string;
  message?: string;
  /** Optional second line with guidance. */
  hint?: string;
  /** HTTP status, so a permission failure is not offered a retry. */
  status?: number;
  onRetry?: () => void;
  className?: string;
}

export function ErrorState({
  title,
  message,
  hint,
  status,
  onRetry,
  className,
}: ErrorStateProps) {
  const t = useTranslations("errors");
  const tCommon = useTranslations("common.actions");
  const forbidden = status === 403;
  const Icon = forbidden ? LockKeyhole : AlertCircle;

  return (
    <div
      className={cn("motion-enter flex flex-col items-center justify-center px-6 py-12 text-center", className)}
      role="alert"
    >
      <span
        className={cn(
          "flex h-12 w-12 items-center justify-center rounded-full",
          forbidden
            ? "bg-primary/[0.08] text-primary"
            : "bg-destructive/[0.08] text-destructive",
        )}
      >
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <h3 className="mt-4 text-base font-semibold tracking-[-0.01em]">
        {title ?? t(forbidden ? "forbidden" : "generic")}
      </h3>
      <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted-foreground">
        {message ?? t("genericHint")}
      </p>
      {hint && <p className="mt-1 max-w-sm text-xs leading-relaxed text-muted-foreground/85">{hint}</p>}
      {!forbidden && onRetry && (
        <Button variant="outline" size="sm" className="mt-5" onClick={onRetry}>
          {tCommon("retry")}
        </Button>
      )}
    </div>
  );
}
