import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import {
  accessTokenExpiry,
  AuthProvider,
  REFRESH_LEAD_MS,
  REFRESH_RETRY_MS,
  useAuth,
} from "./AuthContext";

function jwt(expSeconds: number, tag: string): string {
  const b64 = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256" })}.${b64({ sub: tag, exp: expSeconds })}.sig`;
}

function Probe() {
  const { isAuthenticated, isRestoring, tokens } = useAuth();
  return (
    <div>
      <span data-testid="state">{isRestoring ? "restoring" : isAuthenticated ? "in" : "out"}</span>
      <span data-testid="refresh">{tokens?.refreshToken ?? ""}</span>
    </div>
  );
}

const T0 = new Date("2026-10-26T15:00:00Z").getTime();

function store(accessExpMs: number, refreshToken = "r1") {
  window.localStorage.setItem(
    "shtapm.auth",
    JSON.stringify({
      accessToken: jwt(Math.floor(accessExpMs / 1000), refreshToken),
      refreshToken,
    }),
  );
}

/** Run due timers and let React flush the effects they schedule. */
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function mount() {
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  window.localStorage.clear();
  vi.useFakeTimers({ shouldAdvanceTime: false, now: T0 });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("accessTokenExpiry", () => {
  it("reads exp in milliseconds and rejects junk", () => {
    expect(accessTokenExpiry(jwt(1_800_000_000, "a"))).toBe(1_800_000_000_000);
    expect(accessTokenExpiry("nope")).toBeNull();
    expect(accessTokenExpiry("a.%%%.c")).toBeNull();
  });
});

describe("silent refresh", () => {
  it("renews once, REFRESH_LEAD_MS before expiry, and stores the rotated pair", async () => {
    store(T0 + 15 * 60_000);
    const spy = vi.spyOn(api, "refresh").mockResolvedValue({
      access_token: jwt(Math.floor((T0 + 30 * 60_000) / 1000), "r2"),
      refresh_token: "r2",
      token_type: "bearer",
    } as never);
    await mount();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 60_000 - REFRESH_LEAD_MS - 1_000);
    });
    expect(spy).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_000);
    });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith("r1");
    expect(screen.getByTestId("refresh")).toHaveTextContent("r2");
    expect(JSON.parse(window.localStorage.getItem("shtapm.auth")!).refreshToken).toBe("r2");
  });

  it("never presents the same refresh token twice when triggers coincide", async () => {
    store(T0 - 1_000); // already expired: the schedule fires at once
    let resolve!: (v: unknown) => void;
    const spy = vi
      .spyOn(api, "refresh")
      .mockImplementation(() => new Promise((r) => (resolve = r)) as never);
    await mount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
      document.dispatchEvent(new Event("visibilitychange")); // a second trigger mid-flight
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(spy).toHaveBeenCalledTimes(1);
    await act(async () => {
      resolve({ access_token: jwt(Math.floor((T0 + 900_000) / 1000), "r2"), refresh_token: "r2" });
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByTestId("refresh")).toHaveTextContent("r2");
  });

  it("signs out when the backend rejects the refresh token", async () => {
    store(T0 - 1_000);
    vi.spyOn(api, "refresh").mockRejectedValue(new api.ApiError(401, "invalid"));
    await mount();
    await flush();
    expect(screen.getByTestId("state")).toHaveTextContent("out");
    expect(window.localStorage.getItem("shtapm.auth")).toBeNull();
  });

  it("keeps the session and retries after a network failure", async () => {
    store(T0 - 1_000);
    const spy = vi
      .spyOn(api, "refresh")
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue({
        access_token: jwt(Math.floor((T0 + 900_000) / 1000), "r2"),
        refresh_token: "r2",
      } as never);
    await mount();
    await flush();
    expect(screen.getByTestId("state")).toHaveTextContent("in");
    expect(spy).toHaveBeenCalledTimes(1);

    await flush(REFRESH_RETRY_MS + 10);
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenLastCalledWith("r1");
    expect(screen.getByTestId("refresh")).toHaveTextContent("r2");
  });

  it("adopts a pair another tab already rotated instead of reusing the old token", async () => {
    store(T0 + 15 * 60_000);
    const spy = vi.spyOn(api, "refresh");
    await mount();
    // Another tab refreshed: storage now holds r9, this tab still has r1.
    store(T0 + 30 * 60_000, "r9");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 60_000);
    });
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByTestId("refresh")).toHaveTextContent("r9");
  });

  it("follows other tabs through the storage event", async () => {
    store(T0 + 15 * 60_000);
    await mount();
    store(T0 + 15 * 60_000, "r5");
    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", { key: "shtapm.auth" }));
    });
    expect(screen.getByTestId("refresh")).toHaveTextContent("r5");

    window.localStorage.removeItem("shtapm.auth");
    await act(async () => {
      window.dispatchEvent(new StorageEvent("storage", { key: "shtapm.auth" }));
    });
    expect(screen.getByTestId("state")).toHaveTextContent("out");
  });
});
