import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "./api";
import { useApiResource } from "./useApiResource";

describe("useApiResource", () => {
  it("moves loading → ready and exposes the data", async () => {
    const { result } = renderHook(() => useApiResource(() => Promise.resolve([1, 2]), []));
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(result.current.data).toEqual([1, 2]);
    expect(result.current.error).toBeNull();
  });

  it("reports an HTTP failure with its status", async () => {
    const { result } = renderHook(() =>
      useApiResource(() => Promise.reject(new ApiError(500, "boom")), []),
    );
    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toContain("HTTP 500");
    expect(result.current.unauthorized).toBe(false);
  });

  it("flags a 401 distinctly so the caller can end the session", async () => {
    // An expired access token is not a per-panel failure; it ends the session.
    const { result } = renderHook(() =>
      useApiResource(() => Promise.reject(new ApiError(401, "expired")), []),
    );
    await waitFor(() => expect(result.current.unauthorized).toBe(true));
  });

  it("does not fetch when disabled", async () => {
    const fetcher = vi.fn(() => Promise.resolve("x"));
    const { result } = renderHook(() => useApiResource(fetcher, [], { enabled: false }));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("refresh() re-runs the fetcher", async () => {
    const fetcher = vi.fn(() => Promise.resolve("x"));
    const { result } = renderHook(() => useApiResource(fetcher, []));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(fetcher).toHaveBeenCalledTimes(1);
    act(() => result.current.refresh());
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
  });

  it("does not set state after unmount", async () => {
    // Guards the leak that would otherwise occur on every route change, since
    // every page mounts one of these.
    const errors: unknown[] = [];
    const spy = vi.spyOn(console, "error").mockImplementation((...args) => errors.push(args));
    let resolve: (v: string) => void = () => {};
    const pending = new Promise<string>((r) => {
      resolve = r;
    });

    const { unmount } = renderHook(() => useApiResource(() => pending, []));
    unmount();
    await act(async () => {
      resolve("late");
      await pending;
    });

    expect(errors.filter((e) => String(e).includes("unmounted"))).toHaveLength(0);
    spy.mockRestore();
  });
});
