"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { GraduationCap } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { recoveryApi } from "@/lib/account-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

/**
 * Request a password reset link.
 *
 * Two rules shape this screen:
 *
 * 1. The response is identical for a known and an unknown address, so the
 *    confirmation must not differ either — telling only real accounts "we sent
 *    you an email" would turn this page into an account-enumeration oracle.
 * 2. Self-service recovery is offered only when the server reports a working
 *    delivery channel. A "Forgot password" button that cannot deliver anything
 *    is worse than no button at all: the user waits for mail that never comes.
 */
export default function ForgotPasswordPage() {
  const t = useTranslations("auth.recovery");
  const tAuth = useTranslations("auth");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [sent, setSent] = useState(false);
  // `null` until the server answers: the form must not flash "unavailable" on
  // its way to a perfectly usable state.
  const [available, setAvailable] = useState<boolean | null>(null);
  const [devToken, setDevToken] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    recoveryApi
      .availability()
      .then((result) => {
        if (!cancelled) setAvailable(result.available);
      })
      .catch(() => {
        // An unreachable availability probe is treated as "not offered" rather
        // than "offered", because the failure mode of a false promise is worse.
        if (!cancelled) setAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      setError(null);
      setIsSubmitting(true);
      try {
        const result = await recoveryApi.request(email.trim());
        setSent(true);
        // Populated only under the development delivery channel; in production
        // the token travels out of band and this stays null.
        setDevToken(result.dev_token);
      } catch (err) {
        setError(normalizeApiError(err, "password reset request"));
      } finally {
        setIsSubmitting(false);
      }
    },
    [email],
  );

  const localized = localizeError(error);

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/50 p-4">
      <div className="w-full max-w-md space-y-4">
        <div className="flex justify-end">
          <LanguageSwitcher className="w-40" />
        </div>

        <Card>
          <CardHeader className="space-y-3 text-center">
            <span className="mx-auto flex h-11 w-11 items-center justify-center rounded-xl bg-primary/10">
              <GraduationCap className="h-6 w-6 text-primary" aria-hidden="true" />
            </span>
            <div className="space-y-1">
              <CardTitle className="text-xl">{t("title")}</CardTitle>
              <CardDescription>{t("subtitle")}</CardDescription>
            </div>
          </CardHeader>

          <CardContent className="space-y-4">
            {available === false && (
              <p role="status" className="rounded-md border bg-muted/50 p-3 text-sm">
                {t("unavailable")}
              </p>
            )}

            {sent ? (
              <div className="space-y-3" role="status">
                <p className="text-sm">{t("sentNotice", { email })}</p>
                <p className="text-xs text-muted-foreground">{t("sentHint")}</p>

                {devToken && (
                  <div className="space-y-1 rounded-md border border-dashed p-3">
                    <p className="text-xs font-medium">{t("devChannelTitle")}</p>
                    <p className="text-xs text-muted-foreground">
                      {t("devChannelHint")}
                    </p>
                    <Link
                      href={`/reset-password?token=${encodeURIComponent(devToken)}`}
                      className="block break-all text-xs text-primary underline underline-offset-2"
                    >
                      {t("devChannelLink")}
                    </Link>
                  </div>
                )}
              </div>
            ) : (
              <form className="space-y-4" onSubmit={handleSubmit} noValidate>
                <div className="space-y-2">
                  <label htmlFor="reset-email" className="text-sm font-medium">
                    {tAuth("email")}
                  </label>
                  <Input
                    id="reset-email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    placeholder={tAuth("emailPlaceholder")}
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    disabled={isSubmitting || available === false}
                    aria-required="true"
                    dir="ltr"
                  />
                </div>

                {error && (
                  <div
                    role="alert"
                    className="space-y-1 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm"
                  >
                    <p className="font-medium text-destructive">{localized.message}</p>
                    {localized.hint && (
                      <p className="text-xs text-destructive/80">{localized.hint}</p>
                    )}
                  </div>
                )}

                <Button
                  type="submit"
                  className="w-full"
                  disabled={
                    isSubmitting || available === false || email.trim() === ""
                  }
                  aria-busy={isSubmitting}
                >
                  {isSubmitting ? tCommon("states.submitting") : t("submit")}
                </Button>
              </form>
            )}

            <Button asChild variant="ghost" size="sm" className="w-full">
              <Link href="/login">{t("backToSignIn")}</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
