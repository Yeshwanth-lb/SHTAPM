// Live sensor -> browser latency for one device, measured at WebSocket receipt.
// See lib/latency.ts for what the figure covers and how clock skew is handled.
import { useEffect, useRef, useState } from "react";

import { BrowserLatencyTracker, type LatencySnapshot } from "../../lib/latency";
import { authedWsUrl } from "../../lib/ws";
import { isTelemetryFrame, isTerminalCloseCode } from "./useDeviceTelemetry";

export type LatencyConn = "connecting" | "open" | "closed" | "unauthorized";

export interface BrowserLatencyState {
  snapshot: LatencySnapshot;
  connection: LatencyConn;
}

export function useBrowserLatency(
  deviceId: string,
  accessToken: string | null,
  now: () => number = Date.now,
): BrowserLatencyState {
  const trackerRef = useRef(new BrowserLatencyTracker());
  const [snapshot, setSnapshot] = useState<LatencySnapshot>(() => trackerRef.current.snapshot());
  const [connection, setConnection] = useState<LatencyConn>("connecting");
  const nowRef = useRef(now);
  nowRef.current = now;

  useEffect(() => {
    if (!accessToken) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const target = authedWsUrl(accessToken, deviceId);

    function connect() {
      if (disposed) return;
      setConnection("connecting");
      socket = new WebSocket(target);
      socket.onopen = () => {
        retry = 0;
        setConnection("open");
      };
      socket.onmessage = (event: MessageEvent) => {
        // Timestamp first, before parsing, so JSON work is not billed to the network.
        const receivedAt = nowRef.current();
        let parsed: unknown;
        try {
          parsed = JSON.parse(event.data as string);
        } catch {
          return;
        }
        if (!isTelemetryFrame(parsed) || parsed.device_id !== deviceId) return;
        trackerRef.current.record(parsed.ts, receivedAt);
        setSnapshot(trackerRef.current.snapshot());
      };
      socket.onclose = (event: CloseEvent) => {
        if (disposed) return;
        if (isTerminalCloseCode(event.code)) {
          setConnection("unauthorized");
          return;
        }
        setConnection("closed");
        const delay = Math.min(1000 * 2 ** retry, 10000);
        retry += 1;
        timer = setTimeout(connect, delay);
      };
    }

    connect();
    return () => {
      disposed = true;
      if (timer) clearTimeout(timer);
      socket?.close();
    };
  }, [deviceId, accessToken]);

  return { snapshot, connection };
}
