import { CheckCircle2, AlertTriangle, XCircle, Info, Circle, MinusCircle } from "lucide-react";
import { cn } from "@/lib/utils";

export type StatusTone = "success" | "warning" | "danger" | "info" | "neutral" | "muted";

const TONES: Record<StatusTone, { classes: string; Icon: typeof CheckCircle2 }> = {
  success: {
    classes: "border-success/20 bg-success-soft text-success",
    Icon: CheckCircle2,
  },
  warning: {
    classes: "border-warning/25 bg-warning-soft text-warning",
    Icon: AlertTriangle,
  },
  danger: {
    classes: "border-destructive/20 bg-destructive/[0.07] text-destructive",
    Icon: XCircle,
  },
  info: {
    classes: "border-info/20 bg-info-soft text-info",
    Icon: Info,
  },
  neutral: {
    classes: "border-border bg-muted/70 text-secondary-foreground",
    Icon: Circle,
  },
  muted: {
    classes: "border-border/70 bg-muted/50 text-muted-foreground",
    Icon: MinusCircle,
  },
};

interface StatusBadgeProps {
  tone?: StatusTone;
  children: React.ReactNode;
  /** Optional leading icon override; pass null to hide the icon. */
  icon?: React.ReactNode | null;
  className?: string;
}

/**
 * Status chip with an icon plus text so meaning never depends on colour alone
 * (WCAG 1.4.1 — Use of Colour).
 */
export function StatusBadge({
  tone = "neutral",
  children,
  icon,
  className,
}: StatusBadgeProps) {
  const { classes, Icon } = TONES[tone];
  const showIcon = icon !== null;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] font-semibold leading-none",
        classes,
        className,
      )}
    >
      {showIcon && (icon ?? <Icon className="h-3 w-3 shrink-0" aria-hidden="true" />)}
      {children}
    </span>
  );
}

/** Map a domain status string to a tone. Unknown values fall back to neutral. */
export function toneForStatus(status: string | null | undefined): StatusTone {
  if (!status) return "muted";
  const normalized = status.toUpperCase();

  if (["ACTIVE", "VALID", "ENROLLED", "PRESENT", "AVAILABLE", "APPROVED"].includes(normalized)) {
    return "success";
  }
  if (
    [
      "EXPIRING",
      "EXPIRING_SOON",
      "PENDING",
      "UNDER_REVIEW",
      "PARTIAL",
      "LATE",
      "PLANNED",
      "RESERVED",
    ].includes(normalized)
  ) {
    return "warning";
  }
  if (
    [
      "EXPIRED",
      "SUSPENDED",
      "ABSENT",
      "FULL",
      "REJECTED",
      "REPLACEMENT_REQUIRED",
      "OUT_OF_SERVICE",
      "CANCELLED",
    ].includes(normalized)
  ) {
    return "danger";
  }
  if (["GRADUATED", "COMPLETED", "WITHDRAWN", "MAINTENANCE", "EXCUSED"].includes(normalized)) {
    return "info";
  }
  if (["INACTIVE", "DROPPED", "NOT_PROVIDED", "UNAVAILABLE", "UNKNOWN"].includes(normalized)) {
    return "muted";
  }
  return "neutral";
}
