/**
 * API client for the School Portal backend.
 *
 * Uses fetch with credentials: "include" so the HttpOnly session cookie is sent.
 */
import { apiErrorFromResponse } from "@/lib/api-error";
import type { AuthUser, LoginRequest, LoginResponse } from "@/types/auth";

/**
 * Where the browser sends API calls.
 *
 * Set explicitly by NEXT_PUBLIC_API_URL where the portal is served from one
 * origin. When it is not set, derive it from the page's own host rather than
 * hard-coding `localhost`: the portal answers on both `localhost:3101` and
 * `127.0.0.1:3101`, and a browser treats those as different sites. With a
 * hard-coded `localhost` API base, signing in from `127.0.0.1` returned 200 and
 * then dropped the `SameSite=lax` cookie, because it belonged to a host the
 * page was not on — so the next request was unauthenticated and the user was
 * bounced back to the login form.
 */
function resolveApiBase(): string {
  if (typeof window === "undefined") {
    return process.env.API_INTERNAL_URL || "http://api:8001";
  }
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured) return configured;
  const { protocol, hostname } = window.location;
  return `${protocol}//${hostname}:${process.env.NEXT_PUBLIC_API_PORT || "8001"}`;
}

const API_BASE = resolveApiBase();

/**
 * Upper bound on a single API request.
 *
 * Without it a request that never answers leaves the calling screen in its
 * loading state forever — the page looks frozen and no retry is possible. The
 * bound is generous so genuine long operations (imports, uploads, exports)
 * still finish; it exists to fail a stalled connection, not to police latency.
 */
const REQUEST_TIMEOUT_MS = 120_000;

/**
 * Broadcast when the API says the session behind this browser is gone.
 *
 * A `401 UNAUTHORIZED` from a normal request is the one authoritative signal
 * that the cookie no longer resolves to a live session (expired, revoked by a
 * password change, role change or deactivation, or overwritten). The auth
 * provider listens for it and re-checks `/auth/me` once before clearing state:
 * the response that triggered it may itself have been answered by a racing
 * request, and clearing on a single failure is exactly the behaviour that made
 * the portal look randomly logged out.
 */
export const SESSION_ENDED_EVENT = "scu:session-ended";

/**
 * Endpoints whose own 401 must not start a re-check.
 *
 * `/auth/me` *is* the re-check, and a 401 from `/auth/login` means the
 * credentials were wrong — not that an existing session ended.
 */
const SESSION_PROBE_PATHS = ["/auth/me", "/auth/login"];

/** Perform an API request. */
async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    ...options,
    credentials: "include",
    signal: options.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await apiErrorFromResponse(response);
    if (
      response.status === 401 &&
      error.code === "UNAUTHORIZED" &&
      typeof window !== "undefined" &&
      !SESSION_PROBE_PATHS.some((path) => url.includes(path))
    ) {
      window.dispatchEvent(new CustomEvent(SESSION_ENDED_EVENT));
    }
    throw error;
  }

  // 204 No Content has no body to parse.
  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

class ApiClient {
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  private request<T>(path: string, options: RequestInit = {}): Promise<T> {
    return request<T>(`${this.baseUrl}${path}`, options);
  }

  /** Login with email and password */
  async login(data: LoginRequest): Promise<LoginResponse> {
    return this.request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    });
  }

  /** Logout (invalidate session) */
  async logout(): Promise<void> {
    await this.request<{ message: string }>("/api/v1/auth/logout", {
      method: "POST",
    });
  }

  /** Get current user from session */
  async getMe(): Promise<AuthUser> {
    return this.request<AuthUser>("/api/v1/auth/me");
  }

  /** Check if API is reachable */
  async healthCheck(): Promise<boolean> {
    try {
      await this.request<{ status: string }>("/api/v1/health");
      return true;
    } catch {
      return false;
    }
  }
}

export const api = new ApiClient(API_BASE);

/** Generic fetch wrapper for API calls. `path` is relative to the API base. */
export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  return request<T>(`${API_BASE}${path}`, options);
}

export { API_BASE };