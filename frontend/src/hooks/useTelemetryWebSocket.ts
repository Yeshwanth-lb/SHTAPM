// Live telemetry over WebSocket (P0 M3.5). Plain React state — NO Zustand yet
// (P5). Reuses the frozen contract types verbatim; only frames matching the
// telemetry contract are accepted. Reconnects with capped exponential backoff.
// Kept small and self-contained so P5 can replace it without touching the
// backend MQTT/WebSocket layers.
import { useEffect, useRef, useState } from "react";

import { CHANNELS, type TelemetryMessage, type WSFrame } from "../types/contracts";
import { wsUrl } from "../lib/ws";

export type ConnStatus = "connecting" | "open" | "closed";

export interface TelemetryState {
  status: ConnStatus;
  byDevice: Record<string, TelemetryMessage>;
  lastError: string | null;
}

// Structural guard: accept ONLY well-formed telemetry frames (frozen contract).
export function isTelemetryFrame(x: unknown): x is WSFrame<TelemetryMessage> {
  if (typeof x !== "object" || x === null) return false;
  const f = x as Record<string, unknown>;
  if (f.type !== "telemetry") return false;
  if (typeof f.device_id !== "string") return false;
  if (typeof f.ts !== "string") return false;
  if (typeof f.sample_seq !== "number") return false;
  if (typeof f.sensors !== "object" || f.sensors === null) return false;
  const s = f.sensors as Record<string, unknown>;
  return CHANNELS.every((c) => typeof s[c] === "number");
}

export function useTelemetryWebSocket(
  url: string = wsUrl(),
  deviceId?: string,
): TelemetryState {
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [byDevice, setByDevice] = useState<Record<string, TelemetryMessage>>({});
  const [lastError, setLastError] = useState<string | null>(null);

  const retryRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let disposed = false;
    const target = deviceId ? `${url}?device_id=${encodeURIComponent(deviceId)}` : url;

    function connect() {
      if (disposed) return;
      setStatus("connecting");
      const ws = new WebSocket(target);
      wsRef.current = ws;

      ws.onopen = () => {
        retryRef.current = 0;
        setStatus("open");
      };
      ws.onmessage = (ev: MessageEvent) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(ev.data as string);
        } catch {
          setLastError("invalid JSON");
          return;
        }
        if (!isTelemetryFrame(parsed)) return; // ignore non-telemetry / off-contract
        const frame = parsed as WSFrame<TelemetryMessage>;
        const msg: TelemetryMessage = {
          device_id: frame.device_id,
          ts: frame.ts,
          sensors: frame.sensors,
          sample_seq: frame.sample_seq,
        };
        setByDevice((prev) => ({ ...prev, [msg.device_id]: msg }));
      };
      ws.onerror = () => setLastError("websocket error");
      ws.onclose = () => {
        setStatus("closed");
        if (disposed) return;
        const delay = Math.min(1000 * 2 ** retryRef.current, 10000); // 1s→2s→…→10s cap
        retryRef.current += 1;
        timerRef.current = setTimeout(connect, delay);
      };
    }

    connect();
    return () => {
      disposed = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      wsRef.current?.close();
    };
  }, [url, deviceId]);

  return { status, byDevice, lastError };
}
