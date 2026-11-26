"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, SESSION_ENDED_EVENT } from "@/lib/api";
import { HttpApiError } from "@/lib/api-error";
import type { AuthUser, LoginRequest } from "@/types/auth";

interface AuthContextType {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  /** The server rejected the session (expired, revoked, or replaced). */
  sessionExpired: boolean;
  /** The last authentication check failed at the network level. */
  authUnavailable: boolean;
  login: (data: LoginRequest) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (permission: string) => boolean;
  hasRole: (role: string) => boolean;
  refreshUser: () => Promise<void>;
  recheckSession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * Whether an error proves the session is gone.
 *
 * Only a `401` does. A timeout, an aborted request, a 5xx or a DNS failure says
 * nothing about the session: treating those as "signed out" is what made a
 * brief network hiccup send an authenticated user back to the login screen.
 */
function isUnauthorized(error: unknown): boolean {
  return error instanceof HttpApiError && error.status === 401;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [authUnavailable, setAuthUnavailable] = useState(false);

  // One re-check at a time. A page load fires several requests at once; if the
  // session really is gone they can all report 401, and re-checking per
  // response would stampede the API.
  const rechecking = useRef(false);
  const mounted = useRef(true);

  const recheckSession = useCallback(async () => {
    if (rechecking.current) return;
    rechecking.current = true;
    try {
      const me = await api.getMe();
      if (!mounted.current) return;
      setUser(me);
      setSessionExpired(false);
      setAuthUnavailable(false);
    } catch (error) {
      if (!mounted.current) return;
      // Only the API saying "no session" clears the user. A network failure
      // leaves the current state alone; the next request will re-check.
      if (isUnauthorized(error)) {
        setUser(null);
        setSessionExpired(true);
        setAuthUnavailable(false);
      }
    } finally {
      rechecking.current = false;
    }
  }, []);

  // Restore the session on mount. A network failure is retried before it is
  // reported: an authenticated user who refreshes during a brief outage should
  // not be shown the login screen (which would invite a needless second login
  // and overwrite a perfectly valid session).
  useEffect(() => {
    mounted.current = true;
    let cancelled = false;

    const restore = async () => {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        try {
          const me = await api.getMe();
          if (cancelled) return;
          setUser(me);
          setAuthUnavailable(false);
          setIsLoading(false);
          return;
        } catch (error) {
          if (cancelled) return;
          if (isUnauthorized(error)) {
            setUser(null);
            setAuthUnavailable(false);
            setIsLoading(false);
            return;
          }
          if (attempt < 2) {
            await sleep(600 * (attempt + 1));
            continue;
          }
          setUser(null);
          setAuthUnavailable(true);
          setIsLoading(false);
        }
      }
    };

    void restore();
    return () => {
      cancelled = true;
      mounted.current = false;
    };
  }, []);

  // A 401 from any normal request means the cookie no longer resolves to a
  // live session. Re-check once against the authoritative endpoint rather than
  // guessing: the client stays consistent with the server even when a session
  // was revoked elsewhere (password change, role change, deactivation) or the
  // cookie was replaced by another installation on the same host.
  useEffect(() => {
    const onSessionEnded = () => {
      void recheckSession();
    };
    window.addEventListener(SESSION_ENDED_EVENT, onSessionEnded);
    return () => window.removeEventListener(SESSION_ENDED_EVENT, onSessionEnded);
  }, [recheckSession]);

  const login = useCallback(async (data: LoginRequest) => {
    const response = await api.login(data);
    setUser(response.user);
    setSessionExpired(false);
    setAuthUnavailable(false);
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (error) {
      // The session survives if the server never heard the request, and a
      // reload would silently sign the user back in — the opposite of what
      // "sign out" means. One retry covers a dropped connection; if it still
      // fails the local state is cleared anyway so the browser leaves the
      // portal, and the server-side session expires on its own.
      if (!isUnauthorized(error)) {
        try {
          await api.logout();
        } catch {
          /* handled below */
        }
      }
    } finally {
      setUser(null);
      setSessionExpired(false);
      setAuthUnavailable(false);
    }
  }, []);

  const refreshUser = useCallback(async () => {
    try {
      const me = await api.getMe();
      setUser(me);
      setAuthUnavailable(false);
    } catch (error) {
      // Keeping the current user on a transient failure avoids a permission
      // flicker: the identity did not change, the request just did not land.
      if (isUnauthorized(error)) {
        setUser(null);
        setSessionExpired(true);
      }
    }
  }, []);

  const hasPermission = useCallback(
    (permission: string) => {
      if (!user) return false;
      // Superusers have all permissions
      if (user.is_superuser) return true;
      return user.permissions.includes(permission);
    },
    [user]
  );

  const hasRole = useCallback(
    (role: string) => {
      if (!user) return false;
      return user.roles.some((r) => r.name === role);
    },
    [user]
  );

  const value: AuthContextType = {
    user,
    isLoading,
    isAuthenticated: !!user,
    sessionExpired,
    authUnavailable,
    login,
    logout,
    hasPermission,
    hasRole,
    refreshUser,
    recheckSession,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
