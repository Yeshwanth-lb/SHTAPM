import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, type MockInstance, vi } from "vitest";

import * as api from "../../lib/api";
import { canControlRelay } from "../../lib/token";
import { RelayPanel, relayHeadline } from "./RelayPanel";

function token(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(claims)}.signature`;
}

const ADMIN = token({ sub: "u1", role: "admin" });
const ANALYST = token({ sub: "u2", role: "analyst" });

function relay(status: Partial<api.ActuationStatus> | null): api.RelayOut {
  if (status === null) return { device_id: "pump-01", known: false, status: null };
  return {
    device_id: "pump-01",
    known: true,
    status: {
      device_id: "pump-01",
      ts: "2026-10-27T10:00:00.000Z",
      relay: "off",
      cause: "startup",
      reason: "edge started; relay forced OFF (safe default)",
      latched: false,
      hardware: true,
      ...status,
    },
  };
}

async function renderPanel(accessToken: string | null) {
  const view = render(<RelayPanel deviceId="pump-01" accessToken={accessToken} />);
  await act(async () => {
    await Promise.resolve();
  });
  return view;
}

let getRelay: MockInstance<Parameters<typeof api.getRelay>, ReturnType<typeof api.getRelay>>;

beforeEach(() => {
  getRelay = vi.spyOn(api, "getRelay").mockResolvedValue(relay({}));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("relayHeadline", () => {
  it("never guesses before the edge reports", () => {
    expect(relayHeadline(null)).toEqual({ label: "Unknown", tone: "unknown" });
    expect(relayHeadline(relay(null)).tone).toBe("unknown");
  });

  it("separates a latched autonomous stop from a plain stop", () => {
    expect(relayHeadline(relay({ relay: "on", cause: "command" })).label).toBe("Running");
    expect(relayHeadline(relay({ cause: "command" })).label).toBe("Stopped");
    for (const cause of ["safe_stop", "dry_run", "watchdog"] as const) {
      expect(relayHeadline(relay({ cause, latched: true })).label).toBe("SAFE STOP");
    }
  });

  it("is admin-only", () => {
    expect(canControlRelay("admin")).toBe(true);
    expect(canControlRelay("analyst")).toBe(false);
    expect(canControlRelay("operator")).toBe(false);
    expect(canControlRelay(null)).toBe(false);
  });
});

describe("RelayPanel", () => {
  it("waits for the edge instead of showing a guessed state", async () => {
    getRelay.mockResolvedValue(relay(null));
    await renderPanel(ADMIN);
    expect(screen.getByTestId("relay-unknown")).toBeTruthy();
    expect(screen.getByTestId("relay-badge").textContent).toBe("Unknown");
    expect((screen.getByTestId("relay-start") as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows why a safe stop happened, in words, not just colour", async () => {
    getRelay.mockResolvedValue(
      relay({ cause: "dry_run", latched: true, reason: "dry run: current 0.300 A" }),
    );
    await renderPanel(ADMIN);
    expect(screen.getByTestId("relay-badge").textContent).toBe("SAFE STOP");
    expect(screen.getByTestId("relay-status").textContent).toContain("Dry-run detected");
    expect(screen.getByTestId("relay-reason").textContent).toContain("0.300 A");
  });

  it("requires an explicit confirmation to restart after a safe stop", async () => {
    getRelay.mockResolvedValue(relay({ cause: "safe_stop", latched: true, reason: "x" }));
    const command = vi.spyOn(api, "commandRelay").mockResolvedValue({} as never);
    await renderPanel(ADMIN);
    const start = screen.getByTestId("relay-start") as HTMLButtonElement;
    expect(start.textContent).toBe("Restart after safe stop");
    expect(start.disabled).toBe(true);
    fireEvent.click(screen.getByTestId("relay-confirm"));
    expect(start.disabled).toBe(false);
    fireEvent.click(start);
    await waitFor(() => expect(command).toHaveBeenCalledWith("pump-01", "on", ADMIN));
  });

  it("starts a stopped pump and stops a running one", async () => {
    const command = vi.spyOn(api, "commandRelay").mockResolvedValue({} as never);
    await renderPanel(ADMIN);
    // The panel re-reads the edge's report right after a command.
    getRelay.mockResolvedValue(relay({ relay: "on", cause: "command" }));
    fireEvent.click(screen.getByTestId("relay-start"));
    await waitFor(() => expect(command).toHaveBeenCalledWith("pump-01", "on", ADMIN));
    await waitFor(() => expect(screen.queryByTestId("relay-stop")).toBeTruthy());
    fireEvent.click(screen.getByTestId("relay-stop"));
    await waitFor(() => expect(command).toHaveBeenCalledWith("pump-01", "off", ADMIN));
  });

  it("flags a simulated relay so no physical stop is claimed", async () => {
    getRelay.mockResolvedValue(relay({ hardware: false }));
    await renderPanel(ADMIN);
    expect(screen.getByTestId("relay-simulated").textContent).toContain("nothing is physically");
  });

  it("is read-only below admin", async () => {
    await renderPanel(ANALYST);
    expect(screen.getByTestId("relay-forbidden")).toBeTruthy();
    expect(screen.queryByTestId("relay-start")).toBeNull();
  });

  it("explains a refused or undelivered command", async () => {
    vi.spyOn(api, "commandRelay").mockRejectedValue(
      new api.ApiError(503, "MQTT broker unavailable"),
    );
    await renderPanel(ADMIN);
    fireEvent.click(screen.getByTestId("relay-start"));
    await waitFor(() =>
      expect(screen.getByTestId("relay-error").textContent).toContain("Not sent"),
    );
  });
});
