import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { useDeviceTelemetry, WS_AUTH_FAILED } from "./useDeviceTelemetry";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  closed = false;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.spyOn(api, "apiGet").mockResolvedValue([] as never);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useDeviceTelemetry across a silent token refresh", () => {
  it("keeps the open socket and does not re-fetch history when the token rotates", async () => {
    const { rerender } = renderHook(({ token }) => useDeviceTelemetry("pump-01", token), {
      initialProps: { token: "tok-1" as string | null },
    });
    await act(async () => {
      FakeWebSocket.instances[0].onopen?.();
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(api.apiGet).toHaveBeenCalledTimes(1);

    rerender({ token: "tok-2" });
    await act(async () => {
      await Promise.resolve();
    });
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].closed).toBe(false);
    expect(api.apiGet).toHaveBeenCalledTimes(1);
  });

  it("reconnects with the newest token after an ordinary drop", async () => {
    vi.useFakeTimers();
    try {
      const { rerender } = renderHook(({ token }) => useDeviceTelemetry("pump-01", token), {
        initialProps: { token: "tok-1" as string | null },
      });
      rerender({ token: "tok-2" });
      await act(async () => {
        FakeWebSocket.instances[0].onclose?.({ code: 1006 } as CloseEvent);
        await vi.advanceTimersByTimeAsync(1_100);
      });
      expect(FakeWebSocket.instances).toHaveLength(2);
      expect(FakeWebSocket.instances[1].url).toContain("token=tok-2");
    } finally {
      vi.useRealTimers();
    }
  });

  it("retries an auth rejection when the token was renewed after that attempt", async () => {
    vi.useFakeTimers();
    try {
      const { rerender, result } = renderHook(({ token }) => useDeviceTelemetry("pump-01", token), {
        initialProps: { token: "tok-1" as string | null },
      });
      rerender({ token: "tok-2" });
      await act(async () => {
        FakeWebSocket.instances[0].onclose?.({ code: WS_AUTH_FAILED } as CloseEvent);
        await vi.advanceTimersByTimeAsync(10);
      });
      expect(result.current.sessionExpired).toBe(false);
      expect(FakeWebSocket.instances[1].url).toContain("token=tok-2");
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops on an auth rejection of the current token, then resumes on a new one", async () => {
    const { rerender, result } = renderHook(({ token }) => useDeviceTelemetry("pump-01", token), {
      initialProps: { token: "tok-1" as string | null },
    });
    await act(async () => {
      FakeWebSocket.instances[0].onclose?.({ code: WS_AUTH_FAILED } as CloseEvent);
    });
    expect(result.current.sessionExpired).toBe(true);
    expect(FakeWebSocket.instances).toHaveLength(1);

    rerender({ token: "tok-2" });
    await act(async () => {
      await Promise.resolve();
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].url).toContain("token=tok-2");
    expect(result.current.sessionExpired).toBe(false);
  });
});

describe("useDeviceTelemetry reconnect loop (AC10 P4-6, P5-9)", () => {
  it("shows the drop, backs off, never storms, and recovers", async () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() => useDeviceTelemetry("pump-01", "tok-1"));
      await act(async () => {
        FakeWebSocket.instances[0].onopen?.();
      });
      expect(result.current.connection).toBe("open");

      // Abnormal drop (1006): the UI says so ("Stream disconnected" + notice).
      await act(async () => {
        FakeWebSocket.instances[0].onclose?.({ code: 1006 } as CloseEvent);
      });
      expect(result.current.connection).toBe("closed");
      expect(FakeWebSocket.instances).toHaveLength(1); // no immediate retry storm

      await act(async () => {
        vi.advanceTimersByTime(999);
      });
      expect(FakeWebSocket.instances).toHaveLength(1);
      await act(async () => {
        vi.advanceTimersByTime(1);
      });
      expect(FakeWebSocket.instances).toHaveLength(2); // first retry after 1 s

      // The retry fails too: the next attempt waits longer (2 s), still one socket.
      await act(async () => {
        FakeWebSocket.instances[1].onclose?.({ code: 1006 } as CloseEvent);
        vi.advanceTimersByTime(1999);
      });
      expect(FakeWebSocket.instances).toHaveLength(2);
      await act(async () => {
        vi.advanceTimersByTime(1);
      });
      expect(FakeWebSocket.instances).toHaveLength(3);

      await act(async () => {
        FakeWebSocket.instances[2].onopen?.();
      });
      expect(result.current.connection).toBe("open");
    } finally {
      vi.useRealTimers();
    }
  });
});
