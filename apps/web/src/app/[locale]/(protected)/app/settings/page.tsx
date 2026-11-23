"use client";

import { useCallback, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { AppShell } from "@/components/layout/app-shell";
import { LanguageSwitcher } from "@/components/layout/language-switcher";
import { ThemeSwitcher } from "@/components/layout/theme-switcher";
import { AccentPicker } from "@/components/theme/accent-picker";
import { useAuth } from "@/lib/auth-context";
import { selfServiceApi } from "@/lib/account-api";
import { useApi } from "@/lib/use-api";
import { useErrorMessage } from "@/lib/use-error-message";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { DetailList } from "@/components/ui/detail-list";
import { ErrorState } from "@/components/ui/error-state";
import { EmptyState } from "@/components/ui/empty-state";
import { LoadingState } from "@/components/ui/loading-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { toast } from "@/components/ui/toast";
import type { SessionListResponse } from "@/types/account";

/**
 * Personal settings.
 *
 * Every control on this page has a real effect: the language choice changes the
 * interface, the password change re-hashes the credential and evicts other
 * sessions server-side, and session revocation signs other devices out. Nothing
 * here is presented as configurable unless changing it actually does something.
 */
export default function SettingsPage() {
  const t = useTranslations("settings");
  const tCommon = useTranslations("common");
  const { user, hasPermission, refreshUser } = useAuth();
  const localizeError = useErrorMessage();
  const format = useFormatter();

  const fetchSessions = useCallback(() => selfServiceApi.sessions(), []);
  const sessions = useApi<SessionListResponse>(fetchSessions, [], "own sessions");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState<NormalizedError | null>(null);
  const [revoking, setRevoking] = useState(false);

  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;
  const canSubmitPassword =
    currentPassword.length > 0 &&
    newPassword.length > 0 &&
    newPassword === confirmPassword &&
    !savingPassword;

  const handleChangePassword = async () => {
    if (!canSubmitPassword) return;
    setSavingPassword(true);
    setPasswordError(null);
    try {
      const result = await selfServiceApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      toast.success(
        result.sessions_revoked > 0
          ? t("security.changedRevoked", { count: result.sessions_revoked })
          : t("security.changed"),
      );
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      await refreshUser();
      sessions.refetch();
    } catch (err) {
      setPasswordError(normalizeApiError(err, "change password"));
    } finally {
      setSavingPassword(false);
    }
  };

  const handleRevokeOthers = async () => {
    setRevoking(true);
    try {
      const result = await selfServiceApi.revokeOtherSessions();
      toast.success(t("sessions.revokedOthers", { count: result.sessions_revoked }));
      sessions.refetch();
    } catch (err) {
      toast.error(localizeError(normalizeApiError(err, "revoke sessions")).message);
    } finally {
      setRevoking(false);
    }
  };

  const localizedPasswordError = localizeError(passwordError);

  const sessionRows = sessions.data?.items ?? [];
  const otherSessions = sessionRows.filter((session) => !session.is_current).length;

  return (
    <AppShell>
      <PageHeader
        title={t("title")}
        description={t("subtitle")}
        breadcrumbs={[
          { label: tCommon("labels.overview"), href: "/app" },
          { label: t("title") },
        ]}
      />

      {user?.must_change_password && (
        <Card className="mb-6 border-warning/40">
          <CardContent className="pt-6">
            <StatusBadge tone="warning">{t("security.temporaryNotice")}</StatusBadge>
            <p className="mt-2 text-sm text-muted-foreground">
              {t("security.temporaryDetail")}
            </p>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("profile.heading")}</CardTitle>
          </CardHeader>
          <CardContent>
            <DetailList
              columns={2}
              items={[
                { label: t("profile.name"), value: user?.full_name ?? "—" },
                {
                  label: t("profile.email"),
                  value: <span dir="ltr">{user?.email ?? "—"}</span>,
                },
                {
                  label: t("profile.username"),
                  value: <span dir="ltr" className="font-mono">{user?.username ?? "—"}</span>,
                },
                {
                  label: t("profile.roles"),
                  value: (user?.roles ?? []).map((role) => (
                    <Badge key={role.id} variant="secondary" className="me-1">
                      {role.name}
                    </Badge>
                  )),
                },
              ]}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("language.heading")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">{t("language.description")}</p>
            <LanguageSwitcher className="max-w-xs" />
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm">{t("appearance.heading")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              {t("appearance.description")}
            </p>
            <ThemeSwitcher variant="full" className="max-w-md" />
            <div className="space-y-3 border-t border-border/70 pt-4">
              <div>
                <h3 className="text-sm font-medium">
                  {t("appearance.accentHeading")}
                </h3>
                <p className="text-xs text-muted-foreground">
                  {t("appearance.accentDescription")}
                </p>
              </div>
              <AccentPicker className="max-w-xl" />
            </div>
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="text-sm">{t("security.heading")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <form
              className="grid gap-4 sm:grid-cols-3"
              onSubmit={(event) => {
                event.preventDefault();
                void handleChangePassword();
              }}
            >
              <div className="space-y-1.5">
                <label htmlFor="current-password" className="text-sm font-medium">
                  {t("security.currentPassword")}
                </label>
                <Input
                  id="current-password"
                  type="password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={(event) => setCurrentPassword(event.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="new-password" className="text-sm font-medium">
                  {t("security.newPassword")}
                </label>
                <Input
                  id="new-password"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(event) => setNewPassword(event.target.value)}
                  aria-describedby="new-password-hint"
                />
                <p id="new-password-hint" className="text-xs text-muted-foreground">
                  {t("security.passwordRule")}
                </p>
              </div>
              <div className="space-y-1.5">
                <label htmlFor="confirm-password" className="text-sm font-medium">
                  {t("security.confirmPassword")}
                </label>
                <Input
                  id="confirm-password"
                  type="password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  aria-invalid={mismatch || undefined}
                  aria-describedby={mismatch ? "confirm-password-error" : undefined}
                />
                {mismatch && (
                  <p
                    id="confirm-password-error"
                    role="alert"
                    className="scu-invalid text-xs text-destructive"
                  >
                    {t("security.mismatch")}
                  </p>
                )}
              </div>

              {passwordError && (
                <div className="sm:col-span-3">
                  <ErrorState
                    title={localizedPasswordError.message}
                    hint={localizedPasswordError.hint}
                  />
                </div>
              )}

              <div className="sm:col-span-3">
                <Button type="submit" disabled={!canSubmitPassword}>
                  {savingPassword
                    ? tCommon("states.saving")
                    : t("security.changePassword")}
                </Button>
              </div>
            </form>

            <div className="border-t pt-6">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-medium">{t("sessions.heading")}</h3>
                  <p className="text-xs text-muted-foreground">
                    {t("sessions.description")}
                  </p>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRevokeOthers}
                  disabled={revoking || otherSessions === 0}
                >
                  {t("sessions.revokeOthers")}
                </Button>
              </div>

              {sessions.loading ? (
                <LoadingState />
              ) : sessions.error ? (
                <ErrorState
                  title={localizeError(sessions.error).message}
                  onRetry={sessions.refetch}
                />
              ) : sessionRows.length === 0 ? (
                <EmptyState title={t("sessions.empty")} />
              ) : (
                <ul className="min-w-0 divide-y rounded-md border">
                  {sessionRows.map((session) => (
                    <li
                      key={session.id}
                      className="flex min-w-0 flex-wrap items-center justify-between gap-2 px-3 py-2.5 text-sm"
                    >
                      <div className="min-w-0">
                        <p className="truncate">
                          {session.user_agent ?? t("sessions.unknownDevice")}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {t("sessions.started", {
                            date: format.dateTime(new Date(session.created_at), {
                              dateStyle: "medium",
                              timeStyle: "short",
                            }),
                          })}
                          {session.ip_address && (
                            <span dir="ltr" className="ms-2 font-mono">
                              {session.ip_address}
                            </span>
                          )}
                        </p>
                      </div>
                      {session.is_current && (
                        <StatusBadge tone="success">
                          {t("sessions.thisDevice")}
                        </StatusBadge>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </CardContent>
        </Card>

        {hasPermission("users.view") && (
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle className="text-sm">{t("administration.heading")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {t("administration.description")}
              </p>
              <Button asChild variant="outline" size="sm">
                <Link href="/app/students">{t("administration.link")}</Link>
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </AppShell>
  );
}
