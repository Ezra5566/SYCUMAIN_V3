import { NextIntlClientProvider } from "next-intl";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { AuthProvider } from "@/lib/auth-context";
import { ThemeProvider } from "@/components/theme/theme-provider";
import { Toaster } from "@/components/ui/toast";
import { MotionProvider } from "@/components/motion/motion-provider";
import { isRtl, isLocale, locales, type Locale } from "@/i18n/routing";
import "../globals.css";
import "../solvik.css";
import "../motion.css";

/**
 * Localized root layout.
 *
 * This is the application root layout (there is no `app/layout.tsx`), so it owns
 * `<html>`. `lang` and `dir` are derived from the active locale, which is what
 * makes Arabic render as a genuine RTL document rather than a mirrored skin.
 */

type LayoutProps = {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
};

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export async function generateMetadata({ params }: LayoutProps): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "common" });

  return {
    title: {
      default: t("appName"),
      template: `%s · ${t("appShortName")}`,
    },
    description: t("appName"),
  };
}

export default async function LocaleLayout({ children, params }: LayoutProps) {
  const { locale } = await params;

  // The middleware only routes known locales, but a hand-edited URL can still
  // reach here. Render a real 404 instead of a half-translated page.
  if (!isLocale(locale)) notFound();

  // Opts this request into static rendering where possible.
  setRequestLocale(locale);

  // The Solvik interface is dark-first; a saved light preference still wins.
  const themeScript = `(() => {try {const saved = localStorage.getItem("scu-theme"); const dark = saved !== "light"; const accent = localStorage.getItem("scu-accent") || "institution"; document.documentElement.classList.toggle("dark", dark); document.documentElement.dataset.theme = saved || "dark"; document.documentElement.dataset.accent = accent; document.documentElement.style.colorScheme = dark ? "dark" : "light";} catch (_) {}})();`;

  return (
    <html lang={locale} dir={isRtl(locale) ? "rtl" : "ltr"} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Urbanist:wght@400..800&display=swap"
        />
      </head>
      <body className="min-h-screen bg-background font-sans text-foreground antialiased">
        <NextIntlClientProvider>
          <ThemeProvider>
            <MotionProvider />
            <AuthProvider>
              {children}
              <Toaster />
            </AuthProvider>
          </ThemeProvider>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
