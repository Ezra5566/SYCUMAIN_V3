"use client";

import { useTransition } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Globe } from "lucide-react";
import { usePathname, useRouter } from "@/i18n/navigation";
import { locales, localeLabels, type Locale } from "@/i18n/routing";
import { cn } from "@/lib/utils";

/**
 * Language switcher.
 *
 * Switching rewrites the locale segment of the current URL, so the user stays
 * on the same page. The choice is also persisted by next-intl's locale cookie
 * (see `routing.ts`), so the next visit — including a bare `/` — lands in the
 * chosen language.
 *
 * A native `<select>` is used deliberately: it is keyboard accessible, works
 * with screen readers, behaves correctly under `dir="rtl"`, and needs no
 * custom focus trap to get right.
 */
export function LanguageSwitcher({ className }: { className?: string }) {
  const t = useTranslations("locale");
  const activeLocale = useLocale() as Locale;
  const router = useRouter();
  const pathname = usePathname();
  const [isPending, startTransition] = useTransition();

  const handleChange = (next: string) => {
    if (next === activeLocale) return;
    // `pathname` is locale-free, so this preserves the current page.
    startTransition(() => {
      router.replace(pathname, { locale: next as Locale });
    });
  };

  return (
    <div className={cn("relative", className)}>
      <Globe
        className="pointer-events-none absolute start-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <select
        value={activeLocale}
        onChange={(event) => handleChange(event.target.value)}
        aria-label={t("switchLanguage")}
        aria-busy={isPending}
        disabled={isPending}
        className={cn(
          "h-9 w-full cursor-pointer appearance-none rounded-lg border border-border bg-card shadow-sm",
          "ps-8 pe-7 text-[12px] font-medium text-foreground",
          "transition-[border-color,box-shadow] hover:border-primary/30",
          "focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-primary/10",
          "disabled:cursor-wait disabled:opacity-60",
        )}
      >
        {locales.map((locale) => (
          <option key={locale} value={locale}>
            {localeLabels[locale]}
          </option>
        ))}
      </select>
      <svg
        className="pointer-events-none absolute end-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground"
        viewBox="0 0 12 12"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M3 4.5L6 7.5L9 4.5"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
