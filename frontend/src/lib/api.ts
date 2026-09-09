// REST client. Every shape here mirrors an endpoint that actually exists in
// backend/app/api/*.py — nothing is invented or anticipated.
//
//   POST /api/auth/login    LoginRequest  -> TokenResponse   (api/auth.py)
//   POST /api/auth/refresh  RefreshRequest -> TokenResponse  (api/auth.py)
//   POST /api/auth/logout   LogoutRequest -> 204             (api/auth.py)
//   GET  /api/devices                     -> DeviceOut[]     (api/devices.py)
//   GET  /api/devices/:id/channels        -> ChannelOut[]    (api/devices.py)

/** Host port the backend is published on (.env.example: container stays 8000). */
export const DEFAULT_BACKEND_PORT = 8002;

/**
 * Resolve the API base URL.
 *
 * `VITE_API_BASE_URL` (the name .env.example documents) wins when set.
 * Otherwise the base is derived from the page's own origin, keeping the
 * backend's host in step with wherever the UI was loaded from: served from
 * the Pi at 192.168.1.20:5173, the API resolves to 192.168.1.20:8002; opened
 * on the Pi itself, it resolves to localhost:8002. A hardcoded host would be
 * wrong for one of those two cases, and `localhost` in particular is the
 * BROWSER's machine, not the Pi — the bug this replaces.
 */
export function resolveApiBase(
  env: { VITE_API_BASE_URL?: string },
  location?: { protocol: string; hostname: string },
): string {
  const configured = env.VITE_API_BASE_URL;
  if (configured) return configured.replace(/\/$/, "");
  if (!location) return `http://localhost:${DEFAULT_BACKEND_PORT}`;
  return `${location.protocol}//${location.hostname}:${DEFAULT_BACKEND_PORT}`;
}

export function apiBase(): string {
  return resolveApiBase(
    import.meta.env as { VITE_API_BASE_URL?: string },
    typeof window === "undefined" ? undefined : window.location,
  );
}

/** Mirrors backend TokenResponse (api/auth.py). */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

/** Mirrors backend DeviceOut (api/devices.py). */
export interface DeviceOut {
  id: string;
  device_id: string;
  name: string;
  location: string | null;
  owner_user_id: string | null;
  status: "online" | "offline" | "degraded";
  health_state: "healthy" | "warning" | "critical";
  last_seen_at: string | null;
  sample_rate_hz: number;
  created_at: string;
}

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${apiBase()}${path}`, { ...init, headers });
  if (!response.ok) {
    // FastAPI returns {"detail": "..."} — fall back to the status text when a
    // proxy or network error produces something else.
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body — keep statusText */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function refresh(refreshToken: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
}

export function logout(refreshToken: string, accessToken: string): Promise<void> {
  return request<void>(
    "/api/auth/logout",
    { method: "POST", body: JSON.stringify({ refresh_token: refreshToken }) },
    accessToken,
  );
}

export function getDevices(accessToken: string): Promise<DeviceOut[]> {
  return request<DeviceOut[]>("/api/devices", { method: "GET" }, accessToken);
}

export function apiGet<T>(path: string, accessToken: string): Promise<T> {
  return request<T>(path, { method: "GET" }, accessToken);
}
