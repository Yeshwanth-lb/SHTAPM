// WebSocket URL resolution (P0 M3.5). Configurable via VITE_WS_URL (TRD §02.7);
// falls back to the local backend default.
export function wsUrl(): string {
  return import.meta.env.VITE_WS_URL ?? "ws://localhost:8000/ws";
}
