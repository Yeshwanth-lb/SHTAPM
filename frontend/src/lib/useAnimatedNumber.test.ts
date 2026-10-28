import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAnimatedNumber } from "./useAnimatedNumber";

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.removeAttribute("data-motion");
});

describe("useAnimatedNumber (D052)", () => {
  it("starts at the value and lands exactly on each new target", async () => {
    vi.useFakeTimers({ toFake: ["requestAnimationFrame", "cancelAnimationFrame", "performance"] });
    const { result, rerender } = renderHook(({ v }) => useAnimatedNumber(v, 100), {
      initialProps: { v: 1 as number | null },
    });
    expect(result.current).toBe(1);
    rerender({ v: 0 });
    await act(async () => {
      vi.advanceTimersByTime(50);
    });
    expect(result.current).toBeGreaterThan(0);
    expect(result.current).toBeLessThan(1);
    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    expect(result.current).toBe(0);
  });

  it("jumps straight to the value with reduced motion or a missing value", () => {
    document.documentElement.dataset.motion = "off";
    const { result, rerender } = renderHook(({ v }) => useAnimatedNumber(v), {
      initialProps: { v: 5 as number | null },
    });
    rerender({ v: 9 });
    expect(result.current).toBe(9);
    rerender({ v: null });
    expect(result.current).toBeNull();
  });

  it("stays between the old and new value even if a frame time precedes the start", () => {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((cb) => {
      frames.push(cb);
      return frames.length;
    });
    vi.spyOn(performance, "now").mockReturnValue(10_000);
    const { result, rerender } = renderHook(({ v }) => useAnimatedNumber(v, 100), {
      initialProps: { v: 1 as number | null },
    });
    rerender({ v: 2 });
    act(() => frames.at(-1)?.(5_000)); // 5 s BEFORE the recorded start
    expect(result.current).toBeGreaterThanOrEqual(1);
    expect(result.current).toBeLessThanOrEqual(2);
    vi.restoreAllMocks();
  });
});
