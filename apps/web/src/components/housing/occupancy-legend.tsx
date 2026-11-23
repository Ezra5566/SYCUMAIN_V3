"use client";

import { useTranslations } from "next-intl";
import { occupancyDot, OCCUPANCY_ORDER } from "@/lib/occupancy";
import { cn } from "@/lib/utils";

/**
 * Occupancy legend.
 *
 * Required companion to the colour-coded room grid: it states in words what
 * each colour means, so the grid never depends on colour perception alone.
 */
export function OccupancyLegend({ className }: { className?: string }) {
  const t = useTranslations("housing");

  return (
    <div
      className={cn(
        "flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border bg-background px-3 py-2",
        className,
      )}
    >
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {t("legend")}
      </span>
      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        {OCCUPANCY_ORDER.map((status) => (
          <li key={status} className="flex items-center gap-1.5">
            <span
              className={cn("h-2.5 w-2.5 shrink-0 rounded-full", occupancyDot(status))}
              aria-hidden="true"
            />
            <span className="text-xs text-muted-foreground">
              {t(`occupancyStatus.${status}`)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
