"use client";

import { useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  label?: string;
  /** Debounce in ms before onChange fires. Pass 0 for immediate updates. */
  debounceMs?: number;
  className?: string;
}

/**
 * Search box with debounce, a clear button, and a proper accessible label.
 */
export function SearchInput({
  value,
  onChange,
  placeholder,
  label,
  debounceMs = 300,
  className,
}: SearchInputProps) {
  const t = useTranslations("common");
  const resolvedPlaceholder = placeholder ?? t("labels.searchPlaceholder");
  const resolvedLabel = label ?? t("actions.search");
  const [local, setLocal] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputId = useId();

  // Keep in sync when the parent resets the value (e.g. filter clearing).
  useEffect(() => {
    setLocal(value);
  }, [value]);

  const handleChange = (next: string) => {
    setLocal(next);
    if (timer.current) clearTimeout(timer.current);
    if (debounceMs <= 0) {
      onChange(next);
      return;
    }
    timer.current = setTimeout(() => onChange(next), debounceMs);
  };

  return (
    <div className={cn("scu-search relative", className)}>
      <label htmlFor={inputId} className="sr-only">
        {resolvedLabel}
      </label>
      <Search
        className="pointer-events-none absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <Input
        id={inputId}
        type="search"
        value={local}
        placeholder={resolvedPlaceholder}
        onChange={(e) => handleChange(e.target.value)}
        className="ps-9 pe-9"
      />
      {local && (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={t("actions.clear")}
          onClick={() => {
            setLocal("");
            onChange("");
          }}
          className="absolute end-1 top-1/2 h-7 w-7 -translate-y-1/2 p-0"
        >
          <X className="h-3.5 w-3.5" />
        </Button>
      )}
    </div>
  );
}
