// REST client. Every shape here mirrors an endpoint that actually exists in
// backend/app/api/*.py — nothing is invented or anticipated.
//
//   POST /api/auth/login    LoginRequest  -> TokenResponse   (api/auth.py)
//   POST /api/auth/refresh  RefreshRequest -> TokenResponse  (api/auth.py)
//   POST /api/auth/logout   LogoutRequest -> 204             (api/auth.py)
//   GET  /api/devices                     -> DeviceOut[]     (api/devices.py)
//   GET  /api/devices/:id/channels        -> ChannelOut[]    (api/devices.py)
//   GET  /api/devices/:id/readings        -> SensorReadingOut[] (api/devices.py)
//   GET  /api/alerts                      -> AlertOut[]      (api/alerts.py)
//   GET  /api/users                       -> UserOut[]       (api/users.py, admin)
//   GET  /api/system/health               -> SystemHealthOut (api/system.py, admin)
//   GET  /healthz                         -> HealthzOut      (app/main.py, no auth)

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
  /** Brand: see isApiError(). */
  readonly isApiError = true as const;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Prefer this over `err instanceof ApiError`.
 *
 * `instanceof` compares class identity, which breaks if this module is ever
 * evaluated twice (a stale Vite HMR graph, or the same file reached through
 * two different specifiers). The failure is silent and nasty: a real HTTP
 * error stops being recognised as one and gets reported as a network outage,
 * which is precisely the confusion this codebase already hit once. A branded
 * property survives duplicate module instances.
 */
export function isApiError(err: unknown): err is ApiError {
  return typeof err === "object" && err !== null && (err as ApiError).isApiError === true;
}

/** Non-sensitive description of a thrown value, safe to show or log. */
export function describeRequestFailure(err: unknown): string {
  if (isApiError(err)) return `HTTP ${err.status}: ${err.message}`;
  if (err instanceof TypeError) {
    // What fetch throws for DNS failure, connection refused, and CORS blocks.
    // The browser deliberately withholds which, so say so rather than guess.
    return `Network or CORS failure (${err.message})`;
  }
  if (err instanceof Error) return `${err.name}: ${err.message}`;
  return String(err);
}

async function request<T>(path: string, init: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const url = `${apiBase()}${path}`;
  let response: Response;
  try {
    response = await fetch(url, { ...init, headers });
  } catch (err) {
    // Log the URL actually used: the commonest cause of an unreachable API is
    // the base resolving to the wrong host, and that is invisible otherwise.
    // Method and URL only -- never the body (passwords) or the token.
    console.error(`[shtapm] ${init.method ?? "GET"} ${url} failed:`, describeRequestFailure(err));
    throw err;
  }
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

/** Mirrors backend AlertOut (api/alerts.py). */
export interface AlertOut {
  id: string;
  device_id: string;
  ts: string;
  severity: "info" | "warning" | "critical";
  type: "fault" | "attack" | "system";
  channel: string | null;
  message: string;
  reason: string | null;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
}

/** Mirrors backend UserOut (api/users.py). */
export interface UserOut {
  id: string;
  email: string;
  full_name: string | null;
  role: "operator" | "analyst" | "admin";
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

/** Mirrors backend SystemHealthOut (api/system.py). Admin-only. */
export interface SystemHealthOut {
  mqtt_connected: boolean;
  db_connected: boolean;
  ws_clients: number;
  telemetry_count: number;
  e2e_latency_ms: number | null;
}

/** Mirrors the unauthenticated /healthz payload (app/main.py). */
export interface HealthzOut {
  status: string;
  mqtt_connected: boolean;
  db_connected: boolean;
  db_error: string | null;
  telemetry_count: number;
  devices: string[];
  ws_clients: number;
}

/** /healthz needs no token — it is the one probe available before sign-in. */
export async function getHealthz(): Promise<HealthzOut> {
  const response = await fetch(`${apiBase()}/healthz`);
  if (!response.ok) throw new ApiError(response.status, response.statusText);
  return (await response.json()) as HealthzOut;
}
