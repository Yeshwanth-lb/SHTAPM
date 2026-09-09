// WebSocket URL resolution. Configurable via VITE_WS_URL (TRD §02.7).
//
// Same origin-derivation as lib/api.ts: when VITE_WS_URL is unset the host
// follows the page's own, so the UI works from the Pi's IP and from the Pi
// itself without configuration. Port 8002 matches .env.example (the backend's
// published host port; the container stays on 8000).
//
// The backend REQUIRES a JWT on /ws and rejects before accept(), so no frame
// can leak (backend/app/ws/routes.py). The token travels as a query parameter
// because the browser WebSocket API cannot set an Authorization header — that
// is the backend's own documented convention (`/ws?token=<jwt>&device_id=<id>`),
// not a shortcut chosen here.
import { DEFAULT_BACKEND_PORT } from "./api";

/** Resolve the WS URL from config, falling back to the page's own origin. */
export function resolveWsUrl(
  env: { VITE_WS_URL?: string },
  location?: { protocol: string; hostname: string },
): string {
  const configured = env.VITE_WS_URL;
  if (configured) return configured;
  if (!location) return `ws://localhost:${DEFAULT_BACKEND_PORT}/ws`;
  // https pages must not open an insecure socket — browsers block mixed content.
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.hostname}:${DEFAULT_BACKEND_PORT}/ws`;
}

export function wsUrl(): string {
  return resolveWsUrl(
    import.meta.env as { VITE_WS_URL?: string },
    typeof window === "undefined" ? undefined : window.location,
  );
}

/**
 * Authenticated WS URL. `deviceId` is optional server-side; when omitted a
 * non-admin user receives frames for all devices they own.
 */
export function authedWsUrl(token: string, deviceId?: string): string {
  const url = new URL(wsUrl());
  url.searchParams.set("token", token);
  if (deviceId) url.searchParams.set("device_id", deviceId);
  return url.toString();
}
