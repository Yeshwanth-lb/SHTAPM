// M3.5 hook tests (Vitest + jsdom). Runs in CI (npm blocked locally).
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { isTelemetryFrame, useTelemetryWebSocket } from "./useTelemetryWebSocket";

// Minimal fake WebSocket capturing the latest instance so tests can drive it.
class FakeWebSocket {
  static last: FakeWebSocket | null = null;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  url: string;
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.last = this;
  }
  close() {
    this.closed = true;
    this.onclose?.();
  }
}

const validFrame = {
  type: "telemetry",
  device_id: "pump-01",
  ts: "2026-08-09T12:00:00.000Z",
  sensors: { temperature: 26, vibration: 0.03, pressure: 1013, humidity: 45, gas: 150, current: 0.42 },
  sample_seq: 4,
};

beforeEach(() => {
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("isTelemetryFrame", () => {
  it("accepts a valid telemetry frame", () => {
    expect(isTelemetryFrame(validFrame)).toBe(true);
  });
  it("rejects wrong type / missing sensors / non-numeric channel", () => {
    expect(isTelemetryFrame({ ...validFrame, type: "decision" })).toBe(false);
    expect(isTelemetryFrame({ ...validFrame, sensors: { temperature: 1 } })).toBe(false);
    expect(isTelemetryFrame({ ...validFrame, sample_seq: "x" })).toBe(false);
  });
});

describe("useTelemetryWebSocket", () => {
  it("connects and stores telemetry keyed by device", async () => {
    const { result } = renderHook(() => useTelemetryWebSocket("ws://test/ws"));
    act(() => FakeWebSocket.last!.onopen?.());
    await waitFor(() => expect(result.current.status).toBe("open"));
    act(() => FakeWebSocket.last!.onmessage?.({ data: JSON.stringify(validFrame) }));
    await waitFor(() => expect(result.current.byDevice["pump-01"]?.sample_seq).toBe(4));
    expect(result.current.byDevice["pump-01"].sensors.current).toBe(0.42);
  });

  it("ignores off-contract frames", async () => {
    const { result } = renderHook(() => useTelemetryWebSocket("ws://test/ws"));
    act(() => FakeWebSocket.last!.onopen?.());
    act(() =>
      FakeWebSocket.last!.onmessage?.({
        data: JSON.stringify({ ...validFrame, sensors: { temp: 1, vib: 1 } }),
      }),
    );
    expect(Object.keys(result.current.byDevice)).toHaveLength(0);
  });

  it("passes device_id as a query param", () => {
    renderHook(() => useTelemetryWebSocket("ws://test/ws", "pump-02"));
    expect(FakeWebSocket.last!.url).toBe("ws://test/ws?device_id=pump-02");
  });
});
