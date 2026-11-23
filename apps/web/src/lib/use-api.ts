"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { normalizeApiError, type NormalizedError } from "@/lib/api-error";

export interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: NormalizedError | null;
  refetch: () => void;
}

/**
 * Fetch data once (and on dependency change) with consistent loading and
 * error handling.
 *
 * Uses an incrementing request id so a slow response from a previous request
 * can never overwrite a newer one, and ignores results after unmount.
 *
 * @param fetcher Called on mount and whenever `deps` change.
 * @param deps    Dependency list, like useEffect.
 * @param context Short label used in developer-facing console diagnostics.
 */
export function useApi<T>(
  fetcher: () => Promise<T>,
  deps: unknown[] = [],
  context = "request",
): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<NormalizedError | null>(null);

  const requestId = useRef(0);
  const mounted = useRef(true);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      if (!mounted.current || id !== requestId.current) return;
      setData(result);
    } catch (err) {
      if (!mounted.current || id !== requestId.current) return;
      setData(null);
      setError(normalizeApiError(err, context));
    } finally {
      if (mounted.current && id === requestId.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [context, ...deps]);

  useEffect(() => {
    void run();
  }, [run]);

  return { data, loading, error, refetch: run };
}
