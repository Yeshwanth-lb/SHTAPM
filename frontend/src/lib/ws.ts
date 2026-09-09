// WebSocket URL resolution. Configurable via VITE_WS_URL (TRD §02.7);
// falls back to the local backend default.
//
// The backend now REQUIRES a JWT on /ws and rejects before accept(), so no
// frame can leak (backend/app/ws/routes.py). The token travels as a query
// parameter because the browser WebSocket API cannot set an Authorization
// header — that is the backend's own documented convention
// (`/ws?token=<jwt>&device_id=<id>`), not a shortcut chosen here.
export function wsUrl(): string {
  return import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/ws";
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
