import type { ApiError } from "@/types/auth";

/**
 * Central API error normalization.
 *
 * Design rule (multilingual contract): the backend returns a stable, machine
 * readable `code`. This module never invents an English sentence for the user —
 * it only decides *which translation key* applies. Localization happens at the
 * edge, in `useErrorMessage()`, so every error is rendered in the user's
 * language rather than in whatever language the API happened to use.
 *
 * Developers still get the raw detail: status, code and body are logged to the
 * browser console. Nothing internal reaches the UI.
 */

export type ErrorKind =
  | "unauthorized"
  | "forbidden"
  | "not-found"
  | "validation"
  | "conflict"
  | "rate-limited"
  | "server"
  | "network"
  | "unknown";

export interface NormalizedError {
  kind: ErrorKind;
  /**
   * Stable code from the API envelope (`error.code`), e.g. `BED_OCCUPIED`.
   * Empty when the failure never reached the application layer.
   */
  code: string;
  status?: number;
  /** Raw detail for the console only. Never render this. */
  diagnostic: string;
}

/** Namespace prefix for machine-readable code translations. */
export const ERROR_CODE_PREFIX = "codes.";

/** Fallback translation key for each error kind, within the `errors` namespace. */
export const ERROR_KIND_KEYS: Record<ErrorKind, string> = {
  unauthorized: "unauthorized",
  forbidden: "forbidden",
  "not-found": "notFound",
  validation: "validation",
  conflict: "conflict",
  "rate-limited": "rateLimited",
  server: "serverError",
  network: "network",
  unknown: "generic",
};

/** Error thrown by the shared API clients, carrying the HTTP status. */
export class HttpApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly body: unknown;

  constructor(status: number, code: string, body: unknown, message?: string) {
    super(message ?? code);
    this.name = "HttpApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

function extractServerDetail(payload: unknown): string | undefined {
  if (payload && typeof payload === "object") {
    const maybe = payload as Partial<ApiError> & { detail?: unknown };
    if (maybe.error && typeof maybe.error.message === "string") {
      return maybe.error.message;
    }
    if (typeof maybe.detail === "string") {
      return maybe.detail;
    }
  }
  return undefined;
}

/** Map an HTTP status to the error kind used for display fallback. */
function kindFromStatus(status: number): ErrorKind {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not-found";
  if (status === 409) return "conflict";
  if (status === 429) return "rate-limited";
  if (status === 422 || status === 400) return "validation";
  if (status >= 500) return "server";
  return "unknown";
}

/**
 * Turn any thrown value into a normalized error plus a developer diagnostic.
 *
 * @param error   The caught value.
 * @param context Short label for the console, e.g. "immigration overview".
 */
export function normalizeApiError(error: unknown, context: string): NormalizedError {
  // The shared client bounds every request, so a hung connection surfaces as a
  // timeout rather than as a screen that never stops loading.
  if (
    error instanceof DOMException &&
    (error.name === "TimeoutError" || error.name === "AbortError")
  ) {
    const diagnostic = `${context}: request ${error.name === "TimeoutError" ? "timed out" : "aborted"}`;
    console.warn(`[api] ${diagnostic}`);
    return { kind: "network", code: "REQUEST_TIMEOUT", diagnostic };
  }

  // Network / DNS / CORS failure — fetch rejects with a TypeError.
  if (error instanceof TypeError) {
    const diagnostic = `${context}: network request failed — ${error.message}`;
    console.error(`[api] ${diagnostic}`);
    return { kind: "network", code: "NETWORK_ERROR", diagnostic };
  }

  if (error instanceof HttpApiError) {
    const detail = extractServerDetail(error.body);
    const diagnostic = `${context}: HTTP ${error.status} ${error.code}${
      detail ? ` — ${detail}` : ""
    }`;

    // A 5xx is a defect worth surfacing loudly; a 4xx is ordinary traffic.
    if (error.status >= 500) {
      console.error(`[api] ${diagnostic}`, error.body);
    } else {
      console.warn(`[api] ${diagnostic}`);
    }

    return {
      kind: kindFromStatus(error.status),
      code: error.code,
      status: error.status,
      diagnostic,
    };
  }

  const diagnostic = `${context}: ${error instanceof Error ? error.message : String(error)}`;
  console.error(`[api] ${diagnostic}`, error);
  return { kind: "unknown", code: "UNKNOWN_ERROR", diagnostic };
}

/**
 * Build an error from a non-OK response body.
 *
 * Shared by every API client so status, code and body are always extracted the
 * same way — a client that forgets this would silently degrade every message to
 * the generic fallback.
 */
export async function apiErrorFromResponse(response: Response): Promise<HttpApiError> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    body = {
      error: { code: "UNKNOWN_ERROR", message: "An unexpected error occurred." },
    } satisfies ApiError;
  }

  const code = (body as Partial<ApiError>)?.error?.code ?? `HTTP_${response.status}`;
  return new HttpApiError(response.status, code, body);
}
