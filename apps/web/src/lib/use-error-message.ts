"use client";

import { useCallback } from "react";
import { useTranslations } from "next-intl";
import {
  ERROR_CODE_PREFIX,
  ERROR_KIND_KEYS,
  type NormalizedError,
} from "@/lib/api-error";

export interface LocalizedError {
  /** Localized, user-safe headline. */
  message: string;
  /** Optional localized second line with guidance. */
  hint?: string;
}

/**
 * Localize a normalized API error.
 *
 * Resolution order, so a specific server code always beats a generic status:
 *   1. `errors.codes.<CODE>` — exact meaning, e.g. BED_OCCUPIED.
 *   2. `errors.<kind>`       — the HTTP-status-level fallback.
 *   3. `errors.generic`      — guaranteed to exist.
 *
 * Translation is done here rather than in `normalizeApiError` because that
 * module has no React context. Keeping the split means the backend can add a
 * new code and the UI renders it in the right language with no frontend change
 * beyond adding the message.
 */
export function useErrorMessage() {
  const t = useTranslations("errors");

  return useCallback(
    (error: NormalizedError | null | undefined): LocalizedError => {
      if (!error) return { message: "" };

      const codeKey = `${ERROR_CODE_PREFIX}${error.code}`;
      if (error.code && t.has(codeKey)) {
        return { message: t(codeKey) };
      }

      const kindKey = ERROR_KIND_KEYS[error.kind] ?? "generic";
      const hintKey = `${kindKey}Hint`;
      const message = t(kindKey);

      return {
        // A server that answered with an HTTP status is a different failure
        // from one that could not be reached, so the status travels with the
        // generic message. It is language-neutral and helps staff report the
        // exact request that failed.
        message:
          error.status && error.kind !== "network"
            ? `${message} (HTTP ${error.status})`
            : message,
        hint: t.has(hintKey) ? t(hintKey) : undefined,
      };
    },
    [t],
  );
}
