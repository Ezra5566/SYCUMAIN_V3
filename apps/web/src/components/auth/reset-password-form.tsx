"use client";

import { useState } from "react";
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
 * Minimum accepted password length.
 *
 * Mirrors `PASSWORD_MIN_LENGTH` in `app/schemas/account.py`. Kept as a local
 * constant rather than fetched: the server re-validates regardless, so a stale
 * value can only ever produce a friendlier-than-necessary message, never an
 * accepted weak password.
 */
const MIN_PASSWORD_LENGTH = 12;

/**
 * Form for choosing a new password from a one-time reset link.
 *
 * A missing or malformed token is reported before the user types anything: the
 * link is the only thing standing between them and a useless form submission.
 */
export function ResetPasswordForm({ token }: { token: string }) {
  const t = useTranslations("auth.reset");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const hasToken = token.trim() !== "";

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    // Client-side checks are for the user's benefit only; the server re-validates
    // everything, including the token's single use.
    if (password.length < MIN_PASSWORD_LENGTH) {
      setFieldError(t("tooShort", { min: MIN_PASSWORD_LENGTH }));
      return;
    }
    if (password !== confirmation) {
      setFieldError(t("mismatch"));
      return;
    }
    setFieldError(null);

    setIsSubmitting(true);
    try {
      await recoveryApi.submit(token, password);
      setDone(true);
    } catch (err) {
      setError(normalizeApiError(err, "password reset"));
    } finally {
      setIsSubmitting(false);
    }
  }

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
              <CardDescription>
                {done ? t("successSubtitle") : t("subtitle")}
              </CardDescription>
            </div>
          </CardHeader>

          <CardContent className="space-y-4">
            {!hasToken && (
              <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                {t("missingToken")}
              </p>
            )}

            {done ? (
              <div className="space-y-3" role="status">
                <p className="text-sm">{t("successNotice")}</p>
                <p className="text-xs text-muted-foreground">
                  {t("sessionsRevoked")}
                </p>
                <Button asChild className="w-full">
                  <Link href="/login">{t("goToSignIn")}</Link>
                </Button>
              </div>
            ) : (
              hasToken && (
                <form className="space-y-4" onSubmit={handleSubmit} noValidate>
                  <div className="space-y-2">
                    <label htmlFor="new-password" className="text-sm font-medium">
                      {t("newPassword")}
                    </label>
                    <Input
                      id="new-password"
                      name="new-password"
                      type="password"
                      autoComplete="new-password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      disabled={isSubmitting}
                      aria-required="true"
                    />
                  </div>

                  <div className="space-y-2">
                    <label htmlFor="confirm-password" className="text-sm font-medium">
                      {t("confirmPassword")}
                    </label>
                    <Input
                      id="confirm-password"
                      name="confirm-password"
                      type="password"
                      autoComplete="new-password"
                      value={confirmation}
                      onChange={(event) => setConfirmation(event.target.value)}
                      disabled={isSubmitting}
                      aria-required="true"
                      aria-invalid={Boolean(fieldError)}
                    />
                  </div>

                  <p className="text-xs text-muted-foreground">
                    {t("requirements", { min: MIN_PASSWORD_LENGTH })}
                  </p>

                  {fieldError && (
                    <p role="alert" className="text-sm text-destructive">
                      {fieldError}
                    </p>
                  )}

                  {error && (
                    <div
                      role="alert"
                      className="space-y-1 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm"
                    >
                      <p className="font-medium text-destructive">
                        {localized.message}
                      </p>
                      {localized.hint && (
                        <p className="text-xs text-destructive/80">
                          {localized.hint}
                        </p>
                      )}
                    </div>
                  )}

                  <Button
                    type="submit"
                    className="w-full"
                    disabled={isSubmitting}
                    aria-busy={isSubmitting}
                  >
                    {isSubmitting ? tCommon("states.submitting") : t("submit")}
                  </Button>
                </form>
              )
            )}

            {!done && (
              <Button asChild variant="ghost" size="sm" className="w-full">
                <Link href="/forgot-password">{t("requestNewLink")}</Link>
              </Button>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
