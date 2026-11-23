"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { ACCENTS, useTheme, type Accent } from "@/components/theme/theme-provider";

/** Swatch colours are the accent's identity, not a themed surface. */
const SWATCH: Record<Accent, string> = {
  institution: "hsl(211 68% 45%)",
  sky: "hsl(201 90% 52%)",
  teal: "hsl(168 62% 40%)",
  violet: "hsl(262 62% 58%)",
  amber: "hsl(32 88% 48%)",
  rose: "hsl(344 68% 55%)",
};

const LABEL_KEY: Record<Accent, string> = {
  institution: "accentInstitution",
  sky: "accentSky",
  teal: "accentTeal",
  violet: "accentViolet",
  amber: "accentAmber",
  rose: "accentRose",
};

/**
 * Accent palette picker.
 *
 * Native radios keep arrow-key navigation, focus handling and screen-reader
 * semantics without a custom roving tabindex. Selecting an option writes the
 * preference and re-themes the document immediately, with no navigation.
 */
export function AccentPicker({ className }: { className?: string }) {
  const t = useTranslations("settings");
  const { accent, setAccent } = useTheme();

  return (
    <fieldset className={cn("min-w-0", className)}>
      <legend className="sr-only">{t("appearance.accentHeading")}</legend>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {ACCENTS.map((option) => {
          const active = accent === option;
          return (
            <label
              key={option}
              className={cn(
                "scu-accent-option flex cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2.5 text-[13px] font-medium transition-colors",
                "focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 focus-within:ring-offset-background",
                active
                  ? "border-primary/60 bg-primary/[0.08] text-foreground"
                  : "border-border bg-card/40 text-muted-foreground hover:border-border/80 hover:text-foreground",
              )}
            >
              <input
                type="radio"
                name="accent"
                value={option}
                checked={active}
                onChange={() => setAccent(option)}
                className="sr-only"
              />
              <span
                className="h-5 w-5 shrink-0 rounded-full ring-1 ring-black/20 ring-offset-2 ring-offset-background"
                style={{ backgroundColor: SWATCH[option] }}
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1 leading-tight">
                {t(`appearance.${LABEL_KEY[option]}`)}
              </span>
              {active && <Check className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
