// Auth state: tokens, login, logout, and restore-on-reload.
//
// Tokens live in localStorage so a page reload does not drop the session.
// That is a deliberate, documented trade-off for a single-operator dashboard
// on a local network: it is readable by any script on the origin (XSS), which
// httpOnly cookies would avoid. Switching to cookies is a backend change
// (api/auth.py returns tokens in the body today), so it is not something this
// layer can decide alone — flagged rather than silently accepted.
//
// Silent refresh-on-expiry is NOT implemented in this foundation slice. The
// backend rotates refresh tokens with reuse-detection (auth_service.py), so
// getting it wrong revokes every token a user holds. A 401 currently signs the
// user out cleanly rather than risking that.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as api from "../../lib/api";

const STORAGE_KEY = "shtapm.auth";

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

  useEffect(() => {
    setTokens(readStored());
    setIsRestoring(false);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const response = await api.login(email, password);
    const next: AuthTokens = {
      accessToken: response.access_token,
      refreshToken: response.refresh_token,
    };
    writeStored(next);
    setTokens(next);
  }, []);

  const signOut = useCallback(async () => {
    const current = tokens;
    // Clear locally FIRST: the user is signed out of this browser even if the
    // server call fails, and a failed revoke must never trap them in the app.
    writeStored(null);
    setTokens(null);
    if (current) {
      try {
        await api.logout(current.refreshToken, current.accessToken);
      } catch {
        /* already-revoked or unreachable backend — local sign-out stands */
      }
    }
  }, [tokens]);

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
