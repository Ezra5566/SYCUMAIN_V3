"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { useTheme, type Theme } from "@/components/theme/theme-provider";
import { Button } from "@/components/ui/button";

const OPTIONS: { value: Theme; labelKey: "light" | "dark" | "system"; Icon: typeof Sun }[] = [
  { value: "light", labelKey: "light", Icon: Sun },
  { value: "dark", labelKey: "dark", Icon: Moon },
  { value: "system", labelKey: "system", Icon: Monitor },
];

/**
 * Appearance selector with a compact header menu and a full settings control.
 * Both write the same preference, so changing it in either place is immediate.
 */
export function ThemeSwitcher({
  variant = "compact",
  className,
}: {
  variant?: "compact" | "full";
  className?: string;
}) {
  const t = useTranslations("theme");
  const { theme, resolvedTheme, setTheme } = useTheme();
  const CurrentIcon = resolvedTheme === "dark" ? Moon : Sun;

  if (variant === "full") {
    return (
      <div
        className={cn("grid grid-cols-3 gap-1 rounded-xl border border-border/80 bg-muted/30 p-1", className)}
        role="group"
        aria-label={t("label")}
      >
        {OPTIONS.map(({ value, labelKey, Icon }) => {
          const active = theme === value;
          return (
            <button
              key={value}
              type="button"
              aria-pressed={active}
              onClick={() => setTheme(value)}
              className={cn(
                "flex min-h-14 flex-col items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-medium transition-colors",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                active
                  ? "bg-card text-foreground shadow-sm ring-1 ring-border/80"
                  : "text-muted-foreground hover:bg-card/60 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {t(labelKey)}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className={cn("shrink-0 text-muted-foreground hover:text-foreground", className)}
          aria-label={`${t("label")}: ${t(theme)}`}
          title={`${t("label")}: ${t(theme)}`}
        >
          <CurrentIcon className="h-[18px] w-[18px]" aria-hidden="true" />
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 min-w-48 rounded-xl border border-border/80 bg-popover p-1.5 text-popover-foreground shadow-raised data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
        >
          <DropdownMenu.Label className="px-2.5 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {t("label")}
          </DropdownMenu.Label>
          <DropdownMenu.RadioGroup
            value={theme}
            onValueChange={(value) => setTheme(value as Theme)}
          >
            {OPTIONS.map(({ value, labelKey, Icon }) => (
              <DropdownMenu.RadioItem
                key={value}
                value={value}
                className="flex cursor-pointer select-none items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm outline-none transition-colors focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
              >
                <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                <span className="flex-1">{t(labelKey)}</span>
                <DropdownMenu.ItemIndicator>
                  <Check className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                </DropdownMenu.ItemIndicator>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
