/**
 * Account administration and self-service API client.
 *
 * Administrative account operations live under `/users`; the self-service
 * password and session operations live under `/auth`. Both go through the
 * shared `apiFetch` so cookie and error behaviour stay identical to every
 * other client.
 */

import { apiFetch } from "@/lib/api";
import type {
  Account,
  AccountCreatedResponse,
  AccountListResponse,
  PasswordChangeResponse,
  PasswordResetResponse,
  RoleName,
  SessionListResponse,
} from "@/types/account";

/** Administrative account management. */
export const accountApi = {
  list(params: {
    page?: number;
    page_size?: number;
    search?: string;
    role?: RoleName;
    is_active?: boolean;
  } = {}): Promise<AccountListResponse> {
    const search = new URLSearchParams();
    if (params.page) search.set("page", String(params.page));
    if (params.page_size) search.set("page_size", String(params.page_size));
    if (params.search) search.set("search", params.search);
    if (params.role) search.set("role", params.role);
    if (params.is_active !== undefined)
      search.set("is_active", String(params.is_active));
    const query = search.toString();
    return apiFetch<AccountListResponse>(`/api/v1/users/${query ? `?${query}` : ""}`);
  },

  get(userId: string): Promise<Account> {
    return apiFetch<Account>(`/api/v1/users/${userId}`);
  },

  /**
   * Provision an account.
   *
   * Omit `password` to have one generated; the response then carries the
   * one-time temporary password.
   */
  create(data: {
    email: string;
    full_name: string;
    username?: string;
    roles: RoleName[];
    password?: string;
    must_change_password?: boolean;
    staff_id?: string;
    department?: string;
    title?: string;
  }): Promise<AccountCreatedResponse> {
    return apiFetch<AccountCreatedResponse>("/api/v1/users/", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  update(
    userId: string,
    data: {
      full_name?: string;
      email?: string;
      staff_id?: string | null;
      department?: string | null;
      title?: string | null;
    },
  ): Promise<Account> {
    return apiFetch<Account>(`/api/v1/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },

  setRoles(
    userId: string,
    roles: RoleName[],
    reason: string,
  ): Promise<Account> {
    return apiFetch<Account>(`/api/v1/users/${userId}/roles`, {
      method: "PATCH",
      body: JSON.stringify({ roles, reason }),
    });
  },

  /** Activate or deactivate. Deactivation revokes live sessions server-side. */
  setActive(
    userId: string,
    isActive: boolean,
    invalidateSessions = true,
  ): Promise<Account> {
    return apiFetch<Account>(`/api/v1/users/${userId}/active`, {
      method: "PATCH",
      body: JSON.stringify({
        is_active: isActive,
        invalidate_sessions: invalidateSessions,
      }),
    });
  },

  resetPassword(
    userId: string,
    data: { new_password?: string; must_change_password?: boolean } = {},
  ): Promise<PasswordResetResponse> {
    return apiFetch<PasswordResetResponse>(
      `/api/v1/users/${userId}/reset-password`,
      { method: "POST", body: JSON.stringify(data) },
    );
  },

  sessions(userId: string): Promise<SessionListResponse> {
    return apiFetch<SessionListResponse>(`/api/v1/users/${userId}/sessions`);
  },

  revokeSessions(userId: string): Promise<{ sessions_revoked: number }> {
    return apiFetch<{ sessions_revoked: number }>(
      `/api/v1/users/${userId}/sessions/revoke`,
      { method: "POST" },
    );
  },
};

/**
 * Password recovery for a signed-out user.
 *
 * Separate from `selfServiceApi` because it is the one flow that runs without
 * a session — it is how a user gets one back.
 */
export const recoveryApi = {
  /**
   * Whether self-service recovery is usable at all.
   *
   * The login screen asks rather than assumes: with no delivery channel
   * configured, offering "Forgot password" would promise something the server
   * cannot do.
   */
  availability(): Promise<{ available: boolean; delivery: string }> {
    return apiFetch("/api/v1/auth/password/reset-availability");
  },

  /**
   * Ask for a reset link.
   *
   * The response is identical whether or not the address has an account, so
   * the UI must not treat it as a lookup. `dev_token` is populated only when
   * the development delivery channel is active.
   */
  request(
    email: string,
  ): Promise<{ accepted: boolean; dev_token: string | null; expires_in_minutes: number | null }> {
    return apiFetch("/api/v1/auth/password/reset-request", {
      method: "POST",
      body: JSON.stringify({ email }),
    });
  },

  /** Complete a reset. All existing sessions are revoked on success. */
  submit(
    token: string,
    newPassword: string,
  ): Promise<{ reset: boolean; sessions_revoked: boolean }> {
    return apiFetch("/api/v1/auth/password/reset", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  },
};

/** Self-service password and session management for the signed-in user. */
export const selfServiceApi = {
  changePassword(data: {
    current_password: string;
    new_password: string;
  }): Promise<PasswordChangeResponse> {
    return apiFetch<PasswordChangeResponse>("/api/v1/auth/password/change", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  sessions(): Promise<SessionListResponse> {
    return apiFetch<SessionListResponse>("/api/v1/auth/sessions");
  },

  revokeOtherSessions(): Promise<{ sessions_revoked: number }> {
    return apiFetch<{ sessions_revoked: number }>(
      "/api/v1/auth/sessions/revoke-others",
      { method: "POST" },
    );
  },
};
