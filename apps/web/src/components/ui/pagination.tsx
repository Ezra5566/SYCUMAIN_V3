"use client";

import { useTranslations } from "next-intl";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  className?: string;
}

/**
 * Server-side pagination control.
 *
 * Shows a "showing X–Y of Z" summary alongside the step buttons so the user can
 * always see where they are in the result set. Chevrons are mirrored in RTL.
 */
export function Pagination({
  page,
  pageSize,
  total,
  totalPages,
  onPageChange,
  className,
}: PaginationProps) {
  const t = useTranslations("common.pagination");

  if (totalPages <= 1) return null;

  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  return (
    <nav
      aria-label={t("pageOf", { page, total: totalPages })}
      className={cn(
        "mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {t("showing", { from, to, total })}
      </p>

      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">
          {t("pageOf", { page, total: totalPages })}
        </span>
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <ChevronLeft className="h-4 w-4 ltr:mr-1 rtl:ml-1 rtl:rotate-180" />
          {t("previous")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
        >
          {t("next")}
          <ChevronRight className="h-4 w-4 ltr:ml-1 rtl:mr-1 rtl:rotate-180" />
        </Button>
      </div>
    </nav>
  );
}
