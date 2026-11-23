import { defineRouting } from "next-intl/routing";

/**
 * Supported locales.
 *
 * `en` and `zh` are the two root languages of the institution and receive
 * comprehensive coverage across every module. `fr`, `ar` and `ru` are required
 * for student-facing functionality — the student body includes Russian
 * speakers, so Russian is a first-class locale rather than a partial one.
 *
 * Adding a locale is intentionally a three-line change: append it here, add a
 * `messages/<locale>.json`, and it appears in the language switcher. Nothing
 * else in the application needs to know.
 */
export const locales = ["en", "zh", "fr", "ar", "ru"] as const;

export type Locale = (typeof locales)[number];

/** Endonym — a language is always listed in its own language. */
export const localeLabels: Record<Locale, string> = {
  en: "English",
  zh: "中文",
  fr: "Français",
  ar: "العربية",
  ru: "Русский",
};

/** Locales written right-to-left. Drives `dir` and the RTL layout rules. */
export const rtlLocales: readonly Locale[] = ["ar"];

export const defaultLocale: Locale = "en";

export function isRtl(locale: string): boolean {
  return (rtlLocales as readonly string[]).includes(locale);
}

export function isLocale(value: string): value is Locale {
  return (locales as readonly string[]).includes(value);
}

export const LOCALE_COOKIE = "NEXT_LOCALE";

export const routing = defineRouting({
  locales,
  defaultLocale,
  // Always show the prefix so every URL is unambiguous and shareable.
  // `/` is redirected to the user's preferred locale by the middleware.
  localePrefix: "always",
  localeCookie: {
    name: LOCALE_COOKIE,
    maxAge: 60 * 60 * 24 * 365,
    sameSite: "lax",
  },
  // The cookie wins over Accept-Language; an explicit URL prefix wins over both.
  localeDetection: true,
});
