"use client";

import { useId } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface FilterOption {
  value: string;
  label: string;
}

interface FilterSelectProps {
  /** Accessible label — rendered visually hidden unless `showLabel` is set. */
  label: string;
  value: string;
  options: FilterOption[];
  onChange: (value: string) => void;
  showLabel?: boolean;
  className?: string;
}

/**
 * Native select styled to match the design system.
 *
 * A native control is used deliberately: correct keyboard behaviour, screen
 * reader semantics and logical `start`/`end` placement in RTL all come for
 * free, and on mobile it opens the platform picker.
 */
export function FilterSelect({
  label,
  value,
  options,
  onChange,
  showLabel = false,
  className,
}: FilterSelectProps) {
  const id = useId();

  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <label
        htmlFor={id}
        className={cn(
          "text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground",
          !showLabel && "sr-only",
        )}
      >
        {label}
      </label>
      <div className="relative min-w-0">
        <select
          id={id}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className={cn(
            "h-9 w-full cursor-pointer appearance-none rounded-xl border border-input bg-muted/40",
            "ps-3 pe-8 text-[13px] text-foreground transition-[border-color,box-shadow] duration-150",
            "hover:border-primary/35",
            "focus-visible:border-primary/55 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/10",
          )}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute end-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
