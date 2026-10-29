import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { AlertToasts } from "./AlertToasts";

const alert = (id: string, message: string) => ({
  id,
  device_id: "pump-01",
  ts: "2026-10-29T10:00:00Z",
  severity: "critical" as const,
  type: "attack" as const,
  channel: "current",
  message,
  reason: "physics violation",
  acknowledged_by: null,
  acknowledged_at: null,
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("alert toasts (D058)", () => {
  it("announces only alerts raised after the page loaded", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const get = vi
      .spyOn(api, "apiGet")
      .mockResolvedValueOnce([alert("old", "old attack")] as never)
      .mockResolvedValue([alert("new", "Attack on current"), alert("old", "old attack")] as never);
    render(<AlertToasts accessToken="acc" />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(screen.queryByTestId("alert-toast")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_100);
    });
    expect(get).toHaveBeenCalledTimes(2);
    const toasts = screen.getAllByTestId("alert-toast");
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toHaveTextContent("Attack on current");
  });
});
