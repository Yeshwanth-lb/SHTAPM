import { describe, expect, it } from "vitest";

import { CHANNELS, type TelemetryMessage } from "../../types/contracts";
import {
  appendFrame,
  emptyHistory,
  isTelemetryFrame,
  isTerminalCloseCode,
  pointsFromReading,
  WS_ACCESS_DENIED,
  WS_AUTH_FAILED,
  type SensorReadingOut,
} from "./useDeviceTelemetry";

const READING: SensorReadingOut = {
  ts: "2026-09-10T12:00:00.000Z",
  sample_seq: 42,
  temperature: 24.5,
  vibration: 0.62,
  pressure: 1013.0,
  humidity: 61.2,
  gas: 150.0,
  current: 0.0,
  healthy_mask: 63,
};

const FRAME: TelemetryMessage = {
  device_id: "pump-01",
  ts: "2026-09-10T12:00:01.000Z",
  sensors: {
    temperature: 24.6,
    vibration: 0.7,
    pressure: 1013.0,
    humidity: 61.0,
    gas: 150.0,
    current: 0.0,
  },
  sample_seq: 43,
};

describe("pointsFromReading", () => {
  it("maps every frozen channel, preserving exact values", () => {
    const points = pointsFromReading(READING);
    expect(Object.keys(points).sort()).toEqual([...CHANNELS].sort());
    expect(points.temperature).toEqual({ ts: READING.ts, value: 24.5 });
    // A real zero must survive as zero, not become "missing".
    expect(points.current).toEqual({ ts: READING.ts, value: 0 });
  });
});

describe("appendFrame", () => {
  it("appends one point per channel", () => {
    const next = appendFrame(emptyHistory(), FRAME, 10);
    expect(next.temperature).toEqual([{ ts: FRAME.ts, value: 24.6 }]);
    expect(next.vibration).toEqual([{ ts: FRAME.ts, value: 0.7 }]);
  });

  it("caps the window, dropping the OLDEST points", () => {
    let history = emptyHistory();
    for (let i = 0; i < 5; i += 1) {
      history = appendFrame(
        history,
        { ...FRAME, sensors: { ...FRAME.sensors, temperature: i } },
        3,
      );
    }
    expect(history.temperature).toHaveLength(3);
    expect(history.temperature.map((p) => p.value)).toEqual([2, 3, 4]);
  });

  it("does not mutate the previous history object", () => {
    const before = emptyHistory();
    appendFrame(before, FRAME, 10);
    expect(before.temperature).toEqual([]);
  });
});

describe("isTelemetryFrame", () => {
  it("accepts a well-formed telemetry frame", () => {
    expect(isTelemetryFrame({ type: "telemetry", ...FRAME })).toBe(true);
  });

  it("rejects a frame missing a channel — never render a partial reading", () => {
    const { temperature: _dropped, ...partial } = FRAME.sensors;
    expect(isTelemetryFrame({ type: "telemetry", ...FRAME, sensors: partial })).toBe(false);
  });

  it("rejects a non-numeric sensor value", () => {
    expect(
      isTelemetryFrame({
        type: "telemetry",
        ...FRAME,
        sensors: { ...FRAME.sensors, gas: "150" },
      }),
    ).toBe(false);
  });

  it("ignores other frame types on the shared socket", () => {
    expect(isTelemetryFrame({ type: "decision", ...FRAME })).toBe(false);
    expect(isTelemetryFrame(null)).toBe(false);
    expect(isTelemetryFrame("telemetry")).toBe(false);
  });
});

describe("isTerminalCloseCode", () => {
  it("treats 4401 (bad/expired token) as terminal", () => {
    // Retrying with the same dead token can only fail. Without this the socket
    // reconnects every 10s indefinitely against a rejecting endpoint.
    expect(isTerminalCloseCode(4401)).toBe(true);
  });

  it("treats 4403 (device not accessible) as terminal", () => {
    expect(isTerminalCloseCode(4403)).toBe(true);
  });

  it("treats ordinary closes as retryable", () => {
    expect(isTerminalCloseCode(1000)).toBe(false); // normal
    expect(isTerminalCloseCode(1006)).toBe(false); // abnormal — backend restart
    expect(isTerminalCloseCode(1001)).toBe(false); // going away
  });

  it("matches the close codes the backend actually sends", () => {
    // ws/routes.py: WS_AUTH_FAILED = 4401, WS_ACCESS_DENIED = 4403
    expect(WS_AUTH_FAILED).toBe(4401);
    expect(WS_ACCESS_DENIED).toBe(4403);
  });

  it("does not weaken auth: a terminal code is a STOP, not a bypass", () => {
    // Both terminal codes mean the server refused. Nothing here retries with a
    // modified token, downgrades the check, or falls back to an unauthenticated
    // socket — the only response is to stop and surface it.
    expect(isTerminalCloseCode(WS_AUTH_FAILED)).toBe(true);
    expect(isTerminalCloseCode(WS_ACCESS_DENIED)).toBe(true);
  });
});
