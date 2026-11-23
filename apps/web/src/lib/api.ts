/**
 * API client for the School Portal backend.
 *
 * Uses fetch with credentials: "include" so the HttpOnly session cookie is sent.
 */

import { apiErrorFromResponse } from "@/lib/api-error";
import type { AuthUser, LoginRequest, LoginResponse } from "@/types/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
 * Perform an API request.
 *
 * @param url A COMPLETE url. Callers are responsible for prefixing the base —
 *            passing a path here would silently produce a doubled host.
 */
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
    throw await apiErrorFromResponse(response);
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
