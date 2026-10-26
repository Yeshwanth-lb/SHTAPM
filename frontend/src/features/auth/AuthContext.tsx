// Auth state: tokens, login, logout, and restore-on-reload.
//
// Tokens live in localStorage so a page reload does not drop the session.
// That is a deliberate, documented trade-off for a single-operator dashboard
// on a local network: it is readable by any script on the origin (XSS), which
// httpOnly cookies would avoid. Switching to cookies is a backend change
// (api/auth.py returns tokens in the body today), so it is not something this
// layer can decide alone — flagged rather than silently accepted.
//
// SILENT REFRESH. The access token is short-lived (TRD §02.4: 15 min), so the
// provider renews it shortly before it expires. The backend rotates refresh
// tokens with reuse detection (auth_service.py): presenting a refresh token a
// second time revokes EVERY session the user has. So renewal must happen
// exactly once per refresh token:
//   * single-flight inside a tab: concurrent triggers share one request;
//   * across tabs: before refreshing, re-read storage -- if another tab has
//     already rotated the pair, adopt its tokens instead of reusing the old
//     refresh token; and the `storage` event keeps every tab in step;
//   * a 401 from /refresh means the session is genuinely over -> sign out
//     locally. A network error is not proof of that -> retry later.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import * as api from "../../lib/api";

const STORAGE_KEY = "shtapm.auth";

/** Renew this long before the access token's `exp`. */
export const REFRESH_LEAD_MS = 60_000;
/** Retry delay after a refresh that failed for a reason other than a 401. */
export const REFRESH_RETRY_MS = 30_000;

/** The access token's expiry (ms since epoch), or null if unreadable. Read
 * for scheduling only -- the backend verifies the signature. */
export function accessTokenExpiry(token: string): number | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const claims = JSON.parse(atob(padded)) as { exp?: unknown };
    return typeof claims.exp === "number" ? claims.exp * 1000 : null;
  } catch {
    return null;
  }
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

export interface AuthState {
  tokens: AuthTokens | null;
  isAuthenticated: boolean;
  /** True until the initial localStorage read completes — routing must wait. */
  isRestoring: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

function readStored(): AuthTokens | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AuthTokens>;
    if (typeof parsed.accessToken !== "string" || typeof parsed.refreshToken !== "string") {
      return null;
    }
    return { accessToken: parsed.accessToken, refreshToken: parsed.refreshToken };
  } catch {
    // Private mode, cleared storage, or corrupt JSON — treat as signed out.
    return null;
  }
}

function writeStored(tokens: AuthTokens | null): void {
  try {
    if (tokens) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable — session simply will not survive a reload */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [tokens, setTokens] = useState<AuthTokens | null>(null);
  const [isRestoring, setIsRestoring] = useState(true);
  const tokensRef = useRef<AuthTokens | null>(null);
  const inFlight = useRef<Promise<void> | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);

  const adopt = useCallback((next: AuthTokens | null) => {
    tokensRef.current = next;
    setTokens(next);
  }, []);

  useEffect(() => {
    adopt(readStored());
    setIsRestoring(false);
  }, [adopt]);

  // Another tab signed in, refreshed, or signed out: follow it.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return;
      const stored = readStored();
      if (stored?.refreshToken !== tokensRef.current?.refreshToken) adopt(stored);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [adopt]);

  const refreshSession = useCallback((): Promise<void> => {
    if (inFlight.current) return inFlight.current;
    const run = (async () => {
      const current = tokensRef.current;
      if (!current) return;
      const stored = readStored();
      if (stored && stored.refreshToken !== current.refreshToken) {
        adopt(stored); // another tab already rotated the pair
        return;
      }
      try {
        const response = await api.refresh(current.refreshToken);
        const next: AuthTokens = {
          accessToken: response.access_token,
          refreshToken: response.refresh_token,
        };
        if (tokensRef.current?.refreshToken !== current.refreshToken) return; // signed out meanwhile
        writeStored(next);
        adopt(next);
      } catch (err) {
        if (api.isApiError(err) && err.status === 401) {
          writeStored(null);
          adopt(null);
        } else {
          window.setTimeout(() => setRetryNonce((n) => n + 1), REFRESH_RETRY_MS);
        }
      }
    })().finally(() => {
      inFlight.current = null;
    });
    inFlight.current = run;
    return run;
  }, [adopt]);

  // Schedule the next renewal from the current access token's expiry.
  useEffect(() => {
    if (!tokens) return;
    const expiry = accessTokenExpiry(tokens.accessToken);
    if (expiry === null) return;
    const delay = Math.max(0, expiry - REFRESH_LEAD_MS - Date.now());
    const timer = window.setTimeout(() => void refreshSession(), delay);
    return () => window.clearTimeout(timer);
  }, [tokens, retryNonce, refreshSession]);

  // A laptop waking from sleep may hold an already-expired token: check on return.
  useEffect(() => {
    const onVisible = () => {
      const current = tokensRef.current;
      if (document.visibilityState !== "visible" || !current) return;
      const expiry = accessTokenExpiry(current.accessToken);
      if (expiry !== null && expiry - REFRESH_LEAD_MS <= Date.now()) void refreshSession();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refreshSession]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const response = await api.login(email, password);
      const next: AuthTokens = {
        accessToken: response.access_token,
        refreshToken: response.refresh_token,
      };
      writeStored(next);
      adopt(next);
    },
    [adopt],
  );

  const signOut = useCallback(async () => {
    const current = tokensRef.current;
    // Clear locally FIRST: the user is signed out of this browser even if the
    // server call fails, and a failed revoke must never trap them in the app.
    writeStored(null);
    adopt(null);
    if (current) {
      try {
        await api.logout(current.refreshToken, current.accessToken);
      } catch {
        /* already-revoked or unreachable backend — local sign-out stands */
      }
    }
  }, [adopt]);

  const value = useMemo<AuthState>(
    () => ({
      tokens,
      isAuthenticated: tokens !== null,
      isRestoring,
      signIn,
      signOut,
    }),
    [tokens, isRestoring, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (ctx === null) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
