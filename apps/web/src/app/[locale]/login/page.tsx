"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ShieldCheck } from "lucide-react";
import { Link, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { ThemeSwitcher } from "@/components/layout/theme-switcher";
import { ScuMark } from "@/components/brand/scu-mark";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const DEMO_ACCOUNTS = [
  "admin@school.portal",
  "management@school.portal",
  "teacher@school.portal",
  "student@school.portal",
];

export default function LoginPage() {
  const t = useTranslations("auth");
  const tCommon = useTranslations("common");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<NormalizedError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { login, isAuthenticated, isLoading } = useAuth();
  const localizeError = useErrorMessage();
  const router = useRouter();

  // Redirecting during render is a side effect and breaks under StrictMode /
  // concurrent rendering, so it belongs in an effect.
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/app");
    }
  }, [isLoading, isAuthenticated, router]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();

    const nextFieldErrors: { email?: string; password?: string } = {};
    if (!email.trim()) nextFieldErrors.email = t("emailRequired");
    if (!password) nextFieldErrors.password = t("passwordRequired");

    setFieldErrors(nextFieldErrors);
    if (Object.keys(nextFieldErrors).length > 0) return;

    setError(null);
    setIsSubmitting(true);

    try {
      await login({ email: email.trim(), password });
      // The authenticated state change triggers the redirect effect above.
      // Calling router.replace here as well produced two concurrent
      // navigations; the second aborted the first and left the form on screen
      // even though the session had been created.
    } catch (err) {
      setError(normalizeApiError(err, "login"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const localized = localizeError(error);

  return (
    <div className="relative grid min-h-screen lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div className="scu-backdrop" aria-hidden="true">
        <span className="scu-backdrop__glow scu-backdrop__glow--one" />
        <span className="scu-backdrop__glow scu-backdrop__glow--two" />
        <span className="scu-backdrop__grain" />
      </div>
      {/* Institutional identity panel. Hidden on small screens where the same
          information is carried by the compact brand above the form. */}
      <aside className="relative hidden overflow-hidden border-e border-border bg-card/40 backdrop-blur-xl lg:flex lg:flex-col">
        <div className="institutional-grid absolute inset-0 opacity-70" aria-hidden="true" />
        <div className="motion-ambient" aria-hidden="true">
          <div className="motion-ambient__glow motion-ambient__glow--one" />
          <div className="motion-ambient__glow motion-ambient__glow--two" />
        </div>
        <div
          className="absolute -start-32 -top-32 h-[28rem] w-[28rem] rounded-full border border-white/[0.06]"
          aria-hidden="true"
        />
        <div
          className="absolute -end-40 bottom-[-12rem] h-[34rem] w-[34rem] rounded-full border border-gold/10"
          aria-hidden="true"
        />
        <ScuMark className="absolute -end-12 bottom-20 h-72 w-72 opacity-[0.06]" />

        <div className="relative flex h-full flex-col p-10 xl:p-14">
          <div className="flex items-center gap-3">
            <span className="rounded-full bg-[#f7f4ec] p-1.5 ring-1 ring-border ring-offset-4 ring-offset-background">
              <ScuMark className="h-10 w-10" />
            </span>
            <div>
              <p className="text-sm font-semibold tracking-[0.01em]">
                {tCommon("universityName")}
              </p>
              <p className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
                {tCommon("appShortName")}
              </p>
            </div>
          </div>

          <div className="my-auto max-w-xl py-12">
            <p className="motion-head flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-gold">
              <span className="h-px w-8 bg-gold/70" aria-hidden="true" />
              {t("portalEyebrow")}
            </p>
            <h1 className="motion-title mt-6 max-w-lg text-balance font-display text-[2.6rem] leading-[1.12] tracking-[-0.02em] xl:text-[3.15rem]">
              {t("portalTagline")}
            </h1>
            <p className="motion-enter mt-6 max-w-md text-[15px] leading-7 text-muted-foreground">
              {t("portalSummary")}
            </p>
          </div>

          <div className="flex items-center gap-3 border-t border-border pt-6 text-xs text-muted-foreground">
            <ShieldCheck className="h-4 w-4 shrink-0 text-gold/80" aria-hidden="true" />
            <span>{t("secureAccess")}</span>
          </div>
        </div>
      </aside>

      <main className="relative flex min-h-screen flex-col">
        <div className="flex items-center justify-between px-4 pt-4 sm:px-7 sm:pt-6">
          <div className="flex items-center gap-2.5 lg:hidden">
            <ScuMark className="h-8 w-8" />
            <div className="min-w-0">
              <p className="truncate text-[12px] font-semibold">
                {tCommon("universityName")}
              </p>
              <p className="text-[9px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
                {tCommon("appShortName")}
              </p>
            </div>
          </div>
          <div className="ms-auto flex items-center gap-1.5">
            <ThemeSwitcher />
            <LanguageSwitcher className="w-[8.25rem]" />
          </div>
        </div>

        <div className="flex flex-1 items-center justify-center px-4 py-10 sm:px-7 sm:py-14">
          <div className="motion-hero w-full max-w-[27rem] rounded-[22px] border border-border bg-card/70 p-6 shadow-card backdrop-blur-xl sm:p-7">
            <div className="mb-8">
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary/70">
                {t("portalEyebrow")}
              </p>
              <h1 className="mt-2 text-[1.75rem] font-semibold tracking-[-0.03em]">
                {t("signInTitle")}
              </h1>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                {t("signInSubtitle")}
              </p>
            </div>

            {/* method="post" matters before hydration: with the default GET, a
                submit that lands before React attaches onSubmit puts the email
                and password in the URL, browser history and access logs. A
                pre-hydration POST fails harmlessly instead. */}
            <form onSubmit={handleSubmit} method="post" className="space-y-5" noValidate>
              <div className="space-y-2">
                <label htmlFor="email" className="text-[13px] font-medium">
                  {t("email")}
                </label>
                <Input
                  id="email"
                  name="email"
                  type="email"
                  placeholder={t("emailPlaceholder")}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  disabled={isSubmitting}
                  aria-required="true"
                  aria-invalid={Boolean(fieldErrors.email)}
                  aria-describedby={fieldErrors.email ? "email-error" : undefined}
                  className="h-11"
                />
                {fieldErrors.email && (
                  <p id="email-error" role="alert" className="text-xs text-destructive">
                    {fieldErrors.email}
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <label htmlFor="password" className="text-[13px] font-medium">
                  {t("password")}
                </label>
                <Input
                  id="password"
                  name="password"
                  type="password"
                  placeholder={t("passwordPlaceholder")}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  disabled={isSubmitting}
                  aria-required="true"
                  aria-invalid={Boolean(fieldErrors.password)}
                  aria-describedby={fieldErrors.password ? "password-error" : undefined}
                  className="h-11"
                />
                {fieldErrors.password && (
                  <p id="password-error" role="alert" className="text-xs text-destructive">
                    {fieldErrors.password}
                  </p>
                )}
              </div>

              {error && (
                <div
                  role="alert"
                  className="space-y-1 rounded-lg border border-destructive/20 bg-destructive/[0.06] p-3.5 text-sm"
                >
                  <p className="font-medium text-destructive">{localized.message}</p>
                  {localized.hint && (
                    <p className="text-xs leading-relaxed text-destructive/80">
                      {localized.hint}
                    </p>
                  )}
                </div>
              )}

              <Button
                type="submit"
                data-magnetic
                className="h-11 w-full"
                disabled={isSubmitting}
                aria-busy={isSubmitting}
              >
                {isSubmitting ? t("signingIn") : t("signInButton")}
              </Button>

              <div className="text-center">
                <Link
                  href="/forgot-password"
                  className="text-xs font-medium text-muted-foreground underline-offset-4 transition-colors hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t("forgotPassword")}
                </Link>
              </div>
            </form>

            {process.env.NODE_ENV !== "production" && (
              <div className="mt-8 rounded-xl border border-border/80 bg-muted/45 p-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
                  {t("demoNotice")}
                </p>
                <div className="mt-2.5 grid grid-cols-2 gap-1.5">
                  {DEMO_ACCOUNTS.map((account) => (
                    <button
                      key={account}
                      type="button"
                      onClick={() => {
                        setEmail(account);
                        setPassword("password123");
                      }}
                      className="truncate rounded-md bg-card px-2 py-1.5 text-start font-mono text-[10px] text-muted-foreground shadow-sm transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {account}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="mt-8 flex items-start gap-2.5 border-t border-border/70 pt-5 text-[11px] leading-relaxed text-muted-foreground lg:hidden">
              <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
              {t("secureAccess")}
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
