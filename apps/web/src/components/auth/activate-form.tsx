"use client";

import { useEffect, useState } from "react";
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

/** Mirrors `PASSWORD_MIN_LENGTH` in `app/schemas/account.py`. */
const MIN_PASSWORD_LENGTH = 12;

type LinkState = "CHECKING" | "VALID" | "EXPIRED" | "USED" | "UNKNOWN";

/**
 * First-login activation.
 *
 * A migrated account has no password: the only thing that can create one is
 * this single-use link. The page therefore never offers a "skip" or a default
 * password, and reports an unusable link before the student types anything.
 */
export function ActivateForm({ token }: { token: string }) {
  const t = useTranslations("auth.activate");
  const tCommon = useTranslations("common");
  const localizeError = useErrorMessage();

  const [state, setState] = useState<LinkState>("CHECKING");
  const [maskedEmail, setMaskedEmail] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<NormalizedError | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  const hasToken = token.trim() !== "";

  useEffect(() => {
    if (!hasToken) {
      setState("UNKNOWN");
      return;
    }
    let cancelled = false;
    recoveryApi
      .activationPreview(token)
      .then((preview) => {
        if (cancelled) return;
        setMaskedEmail(preview.email_masked);
        setState(preview.state as LinkState);
      })
      .catch(() => {
        if (!cancelled) setState("UNKNOWN");
      });
    return () => {
      cancelled = true;
    };
  }, [hasToken, token]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setFieldError(null);

    if (password.length < MIN_PASSWORD_LENGTH) {
      setFieldError(t("tooShort", { min: MIN_PASSWORD_LENGTH }));
      return;
    }
    if (password !== confirmation) {
      setFieldError(t("mismatch"));
      return;
    }

    setIsSubmitting(true);
    try {
      await recoveryApi.activate(token, password);
      setDone(true);
    } catch (err) {
      setError(normalizeApiError(err, "activation"));
    } finally {
      setIsSubmitting(false);
    }
  }

  const localized = localizeError(error);
  const unusable = state === "EXPIRED" || state === "USED" || state === "UNKNOWN";

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div className="flex items-center justify-end px-4 pt-4 sm:px-7 sm:pt-6">
        <LanguageSwitcher className="w-[8.25rem]" />
      </div>
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <Card className="w-full max-w-[27rem]">
          <CardHeader>
            <div className="mb-4 flex items-center gap-2.5">
              <GraduationCap className="h-6 w-6 text-primary" aria-hidden="true" />
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {tCommon("appShortName")}
              </p>
            </div>
            <CardTitle>{done ? t("successTitle") : t("title")}</CardTitle>
            <CardDescription>
              {done
                ? t("successNotice")
                : state === "VALID" && maskedEmail
                  ? t("forMasked", { email: maskedEmail })
                  : t("subtitle")}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {!hasToken && (
              <p role="alert" className="text-sm text-destructive">
                {t("missingToken")}
              </p>
            )}

            {state === "CHECKING" && hasToken && !done && (
              <p className="text-sm text-muted-foreground">{t("checking")}</p>
            )}

            {unusable && !done && (
              <p role="alert" className="text-sm text-destructive">
                {state === "USED" ? t("used") : t("invalid")}
              </p>
            )}

            {done && (
              <Button asChild className="w-full">
                <Link href="/login">{t("goToSignIn")}</Link>
              </Button>
            )}

            {!done && state === "VALID" && (
              <form onSubmit={handleSubmit} className="space-y-4" method="post" noValidate>
                <div className="space-y-2">
                  <label htmlFor="new-password" className="text-[13px] font-medium">
                    {t("newPassword")}
                  </label>
                  <Input
                    id="new-password"
                    type="password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    disabled={isSubmitting}
                    aria-describedby="password-requirements"
                  />
                  <p
                    id="password-requirements"
                    className="text-xs text-muted-foreground"
                  >
                    {t("requirements", { min: MIN_PASSWORD_LENGTH })}
                  </p>
                </div>

                <div className="space-y-2">
                  <label htmlFor="confirm-password" className="text-[13px] font-medium">
                    {t("confirmPassword")}
                  </label>
                  <Input
                    id="confirm-password"
                    type="password"
                    autoComplete="new-password"
                    value={confirmation}
                    onChange={(event) => setConfirmation(event.target.value)}
                    disabled={isSubmitting}
                  />
                </div>

                {fieldError && (
                  <p role="alert" className="text-xs text-destructive">
                    {fieldError}
                  </p>
                )}

                {error && (
                  <div role="alert" className="space-y-1 text-sm">
                    <p className="font-medium text-destructive">{localized.message}</p>
                    {localized.hint && (
                      <p className="text-xs text-destructive/80">{localized.hint}</p>
                    )}
                  </div>
                )}

                <Button type="submit" className="w-full" disabled={isSubmitting}>
                  {isSubmitting ? t("submitting") : t("submit")}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
