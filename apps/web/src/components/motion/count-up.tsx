"use client";

import { useCountUp } from "@/lib/motion";

interface CountUpProps {
  value: number;
  /** Formats the interpolated value; defaults to a rounded integer string. */
  format?: (value: number) => string;
  duration?: number;
  className?: string;
}

/**
 * Animated metric value.
 *
 * The server and the first client render both emit zero, so hydration stays
 * deterministic; the browser then counts up. The final frame always lands on
 * the exact integer the API returned.
 */
export function CountUp({
  value,
  format = (current) => String(Math.round(current)),
  duration = 950,
  className,
}: CountUpProps) {
  const display = useCountUp(value, duration);
  return <span className={className}>{format(display)}</span>;
}
