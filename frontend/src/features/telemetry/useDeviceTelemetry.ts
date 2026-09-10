// Live + historical telemetry for one device.
//
// Two real sources, no synthesis:
//   * GET /api/devices/:id/readings?limit=N  — the recent window, on mount.
//   * WS  /ws?token=…&device_id=…            — live frames appended after.
//
// Nothing here invents, interpolates or smooths a value. A channel with no
// reading yet is reported as absent so the UI can say so, rather than showing
// a zero that looks like a measurement.
import { useEffect, useMemo, useRef, useState } from "react";

import { apiGet, ApiError } from "../../lib/api";
import { authedWsUrl } from "../../lib/ws";
import { CHANNELS, type Channel, type TelemetryMessage } from "../../types/contracts";

/** Mirrors backend SensorReadingOut (api/devices.py). */
export interface SensorReadingOut {
  ts: string;
  sample_seq: number;
  temperature: number;
  vibration: number;
  pressure: number;
  humidity: number;
  gas: number;
  current: number;
  healthy_mask: number;
}

/** One point of one channel's history. */
export interface ChannelPoint {
  ts: string;
  value: number;
}

export type ConnStatus = "connecting" | "open" | "closed" | "unauthorized";

// Close codes the backend uses to reject BEFORE accept() (ws/routes.py).
// Both are terminal for this token: retrying with the same one cannot succeed,
// so the reconnect loop must stop rather than hammer a rejecting server every
// 10s forever. An access token expires after 15 minutes, so without this an
// idle tab becomes an indefinite authenticated-reconnect storm.
export const WS_AUTH_FAILED = 4401; // missing/invalid/expired token
export const WS_ACCESS_DENIED = 4403; // valid token, device not accessible

/** True when the close code means "this token will never work". */
export function isTerminalCloseCode(code: number): boolean {
  return code === WS_AUTH_FAILED || code === WS_ACCESS_DENIED;
}
export type HistoryStatus = "loading" | "ready" | "error";

export interface DeviceTelemetryState {
  latest: TelemetryMessage | null;
  history: Record<Channel, ChannelPoint[]>;
  connection: ConnStatus;
  historyStatus: HistoryStatus;
  historyError: string | null;
  /** Frames received over the socket this session (not rows from history). */
  liveFrameCount: number;
  /** True when the socket was rejected for auth and will NOT be retried. */
  sessionExpired: boolean;
}

/** A fresh, empty series per frozen channel. Exported for tests. */
export function emptyHistory(): Record<Channel, ChannelPoint[]> {
  const out = {} as Record<Channel, ChannelPoint[]>;
  for (const channel of CHANNELS) out[channel] = [];
  return out;
}

/** Convert one readings row into per-channel points. */
export function pointsFromReading(row: SensorReadingOut): Record<Channel, ChannelPoint> {
  return Object.fromEntries(CHANNELS.map((c) => [c, { ts: row.ts, value: row[c] }])) as Record<
    Channel,
    ChannelPoint
  >;
}

/** Append a frame's values, keeping at most `cap` points per channel. */
export function appendFrame(
  history: Record<Channel, ChannelPoint[]>,
  message: TelemetryMessage,
  cap: number,
): Record<Channel, ChannelPoint[]> {
  const next = {} as Record<Channel, ChannelPoint[]>;
  for (const channel of CHANNELS) {
    const series = [...history[channel], { ts: message.ts, value: message.sensors[channel] }];
    next[channel] = series.length > cap ? series.slice(series.length - cap) : series;
  }
  return next;
}

export interface UseDeviceTelemetryOptions {
  /** Points retained per channel. Also the history page size requested. */
  window?: number;
}

export function useDeviceTelemetry(
  deviceId: string,
  accessToken: string | null,
  { window: windowSize = 120 }: UseDeviceTelemetryOptions = {},
): DeviceTelemetryState {
  const [latest, setLatest] = useState<TelemetryMessage | null>(null);
  const [history, setHistory] = useState<Record<Channel, ChannelPoint[]>>(emptyHistory);
  const [connection, setConnection] = useState<ConnStatus>("connecting");
  const [historyStatus, setHistoryStatus] = useState<HistoryStatus>("loading");
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [liveFrameCount, setLiveFrameCount] = useState(0);
  const [sessionExpired, setSessionExpired] = useState(false);

  // ---- historical window (REST, once per device/token) --------------------
  useEffect(() => {
    if (!accessToken) return;
    let cancelled = false;
    setHistoryStatus("loading");
    setHistoryError(null);

    apiGet<SensorReadingOut[]>(
      `/api/devices/${encodeURIComponent(deviceId)}/readings?limit=${windowSize}`,
      accessToken,
    )
      .then((rows) => {
        if (cancelled) return;
        const seeded = emptyHistory();
        for (const row of rows) {
          const points = pointsFromReading(row);
          for (const channel of CHANNELS) seeded[channel].push(points[channel]);
        }
        // Live frames may already have arrived; keep them at the end.
        setHistory((live) => {
          const merged = {} as Record<Channel, ChannelPoint[]>;
          for (const channel of CHANNELS) {
            const combined = [...seeded[channel], ...live[channel]];
            merged[channel] =
              combined.length > windowSize
                ? combined.slice(combined.length - windowSize)
                : combined;
          }
          return merged;
        });
        setHistoryStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setHistoryError(
          err instanceof ApiError ? `HTTP ${err.status}: ${err.message}` : "could not load history",
        );
        setHistoryStatus("error");
      });

    return () => {
      cancelled = true;
    };
  }, [deviceId, accessToken, windowSize]);

  // ---- live frames (WebSocket) -------------------------------------------
  const disposedRef = useRef(false);
  useEffect(() => {
    if (!accessToken) return;
    disposedRef.current = false;
    setSessionExpired(false); // a new token deserves a fresh attempt
    let socket: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    // authedWsUrl already carries ?token=&device_id= — this must NOT be
    // concatenated with another query string.
    const target = authedWsUrl(accessToken, deviceId);

    function connect() {
      if (disposedRef.current) return;
      setConnection("connecting");
      socket = new WebSocket(target);

      socket.onopen = () => {
        retry = 0;
        setConnection("open");
      };
      socket.onmessage = (event: MessageEvent) => {
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data as string);
        } catch {
          return; // malformed frame: ignore, never render a partial value
        }
        if (!isTelemetryFrame(parsed)) return;
        const frame = parsed as TelemetryMessage & { type: string };
        if (frame.device_id !== deviceId) return;
        const message: TelemetryMessage = {
          device_id: frame.device_id,
          ts: frame.ts,
          sensors: frame.sensors,
          sample_seq: frame.sample_seq,
        };
        setLatest(message);
        setLiveFrameCount((n) => n + 1);
        setHistory((prev) => appendFrame(prev, message, windowSize));
      };
      socket.onclose = (event: CloseEvent) => {
        if (disposedRef.current) return;
        // Terminal auth rejection: STOP. Reconnecting with the same dead token
        // can only ever fail, and doing so every 10s indefinitely is both a
        // resource leak and a self-inflicted load on a rejecting endpoint.
        if (isTerminalCloseCode(event.code)) {
          setConnection("unauthorized");
          setSessionExpired(true);
          return;
        }
        setConnection("closed");
        const delay = Math.min(1000 * 2 ** retry, 10000); // 1s→2s→…→10s cap
        retry += 1;
        timer = setTimeout(connect, delay);
      };
    }

    connect();
    return () => {
      disposedRef.current = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [deviceId, accessToken, windowSize]);

  return useMemo(
    () => ({
      latest,
      history,
      connection,
      historyStatus,
      historyError,
      liveFrameCount,
      sessionExpired,
    }),
    [latest, history, connection, historyStatus, historyError, liveFrameCount, sessionExpired],
  );
}

/** Structural guard: accept ONLY well-formed telemetry frames. */
export function isTelemetryFrame(x: unknown): x is TelemetryMessage & { type: string } {
  if (typeof x !== "object" || x === null) return false;
  const f = x as Record<string, unknown>;
  if (f.type !== "telemetry") return false;
  if (typeof f.device_id !== "string" || typeof f.ts !== "string") return false;
  if (typeof f.sample_seq !== "number") return false;
  if (typeof f.sensors !== "object" || f.sensors === null) return false;
  const s = f.sensors as Record<string, unknown>;
  return CHANNELS.every((c) => typeof s[c] === "number");
}
