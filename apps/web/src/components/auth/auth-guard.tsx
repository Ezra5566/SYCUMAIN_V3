"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";
import { LoadingState } from "@/components/ui/loading-state";
import { ErrorState } from "@/components/ui/error-state";

/**
 * AuthGuard wraps protected pages and redirects unauthenticated users to the
 * localized login page.
 *
 * It also routes an account that still holds a temporary password to the
 * settings page, where the password can be changed. That is a convenience, not
 * the control: the API refuses every other endpoint with
 * `PASSWORD_CHANGE_REQUIRED` while `must_change_password` is set, so a client
 * that ignored this redirect would simply see 403s.
 *
 * The distinction between "signed out" and "cannot reach the server" matters:
 * a network failure is offered a retry, never a login screen, because signing
 * in again during an outage cannot work and a second login would replace a
 * valid session.
 *
 * IMPORTANT: This is UX protection only. The FastAPI backend is the
 * authoritative authorization boundary and rejects every unauthorized request
 * regardless of what the client renders.
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const t = useTranslations("auth");
  const tErrors = useTranslations("errors");
  const { isAuthenticated, isLoading, authUnavailable, user, recheckSession } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (isLoading || authUnavailable) return;

    if (!isAuthenticated) {
      router.replace("/login");
      return;
    }

    if (user?.must_change_password && pathname !== "/app/settings") {
      router.replace("/app/settings");
    }
  }, [isLoading, authUnavailable, isAuthenticated, user, pathname, router]);

  if (isLoading) {
    return <LoadingState message={t("checkingAuth")} />;
  }

  if (authUnavailable && !isAuthenticated) {
    return (
      <ErrorState
        title={tErrors("network")}
        message={tErrors("networkHint")}
        onRetry={() => void recheckSession()}
      />
    );
  }

  if (!isAuthenticated) {
    return <LoadingState message={t("checkingAuth")} />;
  }

  return <>{children}</>;
}
