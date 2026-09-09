// One loading/error/data lifecycle for every REST-backed page.
//
// Centralised so each page does not re-implement it (and re-implement the
// cleanup subtly differently). Three behaviours matter:
//
//   * Cancellation — a fetch in flight when the user navigates away must not
//     call setState on an unmounted component. Every page mounts one of these,
//     so getting it wrong once would leak on every route change.
//   * 401 handling — an access token expires after 15 minutes. A 401 means the
//     session is over, not that this particular page failed, so it is surfaced
//     distinctly and the caller signs the user out rather than showing a
//     confusing per-panel error.
//   * Optional polling — for endpoints with no WebSocket equivalent (health,
//     alerts). The timer is always cleared on unmount.
import { useCallback, useEffect, useState } from "react";

import { ApiError, isApiError } from "./api";

export type ResourceStatus = "loading" | "ready" | "error";

export interface ApiResource<T> {
  data: T | null;
  status: ResourceStatus;
  error: string | null;
  /** True when the failure was a 401 — the session, not this request. */
  unauthorized: boolean;
  /** Re-run the fetch immediately (used by "Retry" affordances). */
  refresh: () => void;
}

export interface UseApiResourceOptions {
  /** Poll every N ms. Omit for fetch-once. */
  pollMs?: number;
  /** Skip fetching entirely (e.g. no token yet, or admin-only and not admin). */
  enabled?: boolean;
}

export function useApiResource<T>(
  fetcher: () => Promise<T>,
  deps: ReadonlyArray<unknown>,
  { pollMs, enabled = true }: UseApiResourceOptions = {},
): ApiResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [status, setStatus] = useState<ResourceStatus>(enabled ? "loading" : "ready");
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!enabled) {
      setStatus("ready");
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function run(initial: boolean) {
      if (initial) setStatus("loading");
      try {
        const result = await fetcher();
        if (cancelled) return;
        setData(result);
        setError(null);
        setUnauthorized(false);
        setStatus("ready");
      } catch (err: unknown) {
        if (cancelled) return;
        const is401 = isApiError(err) && (err as ApiError).status === 401;
        setUnauthorized(is401);
        setError(
          isApiError(err) ? `HTTP ${err.status}: ${err.message}` : "Could not reach the backend",
        );
        // A poll that fails keeps the last good data on screen rather than
        // blanking a dashboard on one dropped request; the error is shown too.
        setStatus(pollMs && data !== null ? "ready" : "error");
      } finally {
        if (!cancelled && pollMs) timer = setTimeout(() => void run(false), pollMs);
      }
    }

    void run(true);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
    // NOTE: `fetcher` is intentionally NOT a dependency. Callers pass an inline
    // closure, which is a new function identity on every render, so depending
    // on it would refetch in an endless loop. `deps` is the explicit contract:
    // list whatever the fetcher actually closes over.
  }, [...deps, nonce, pollMs, enabled]);

  return { data, status, error, unauthorized, refresh };
}
