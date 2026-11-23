import { cn } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";

export type StatTone = "default" | "success" | "warning" | "danger" | "info";

const TONE_CLASSES: Record<
  StatTone,
  { value: string; icon: string; rail: string }
> = {
  default: {
    value: "text-foreground",
    icon: "bg-primary/[0.07] text-primary",
    rail: "bg-primary",
  },
  success: {
    value: "text-success",
    icon: "bg-success-soft text-success",
    rail: "bg-success",
  },
  warning: {
    value: "text-warning",
    icon: "bg-warning-soft text-warning",
    rail: "bg-warning",
  },
  danger: {
    value: "text-destructive",
    icon: "bg-destructive/10 text-destructive",
    rail: "bg-destructive",
  },
  info: {
    value: "text-info",
    icon: "bg-info-soft text-info",
    rail: "bg-info",
  },
};

interface StatCardProps {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: StatTone;
  icon?: React.ReactNode;
  className?: string;
}

/**
 * Dense metric tile. The icon is an orientation cue, while the value, label and
 * semantic rail carry the meaning without depending on colour alone.
 */
export function StatCard({
  label,
  value,
  hint,
  tone = "default",
  icon,
  className,
}: StatCardProps) {
  const toneClasses = TONE_CLASSES[tone];

  return (
    <Card className={cn("motion-stat group relative overflow-hidden", className)}>
      <span
        className={cn("absolute inset-y-0 start-0 w-[3px]", toneClasses.rail)}
        aria-hidden="true"
      />
      <CardContent className="flex items-start justify-between gap-3 p-4 ps-5">
        <div className="min-w-0">
          <p className="truncate text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {label}
          </p>
          <p
            className={cn(
              "mt-2 text-[1.95rem] font-semibold leading-none tracking-[-0.045em] tabular-nums",
              toneClasses.value,
            )}
          >
            {value}
          </p>
          {hint && (
            <p className="mt-1.5 truncate text-xs text-muted-foreground">{hint}</p>
          )}
        </div>
        {icon && (
          <div
            className={cn(
              "motion-stat__icon flex h-9 w-9 shrink-0 items-center justify-center rounded-xl",
              toneClasses.icon,
            )}
            aria-hidden="true"
          >
            {icon}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface StatGridProps {
  children: React.ReactNode;
  className?: string;
}

/** Responsive metric grid that avoids awkward gaps at intermediate widths. */
export function StatGrid({ children, className }: StatGridProps) {
  return (
    <div
      className={cn(
        "motion-kpis mb-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5",
        className,
      )}
    >
      {children}
    </div>
  );
}
