import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { canInject, roleFromToken } from "../../lib/token";
import { SCENARIOS, ScenarioInjectPanel, validateInjection } from "./ScenarioInjectPanel";

function token(claims: Record<string, unknown>): string {
  const b64 = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${b64({ alg: "HS256", typ: "JWT" })}.${b64(claims)}.signature`;
}

const ADMIN = token({ sub: "u1", role: "admin" });
const OPERATOR = token({ sub: "u2", role: "operator" });

const CHANNELS = [
  { channel: "current", unit: "A" },
  { channel: "vibration", unit: "g" },
] as never;

function injection(overrides: Partial<api.InjectionOut> = {}): api.InjectionOut {
  const now = Date.now();
  return {
    command_id: "abcdef1234567890",
    device_id: "pump-01",
    scenario: "constant_spoof",
    kind: "attack",
    channel: "current",
    duration_s: 60,
    params: { value: 0.8 },
    issued_by: "admin@example.com",
    issued_at: new Date(now).toISOString(),
    expires_at: new Date(now + 60_000).toISOString(),
    active: true,
    ...overrides,
  };
}

async function renderPanel(accessToken: string | null, live: Record<string, number> | null = null) {
  const view = render(
    <ScenarioInjectPanel
      deviceId="pump-01"
      accessToken={accessToken}
      liveValues={live}
      channels={CHANNELS}
    />,
  );
  // Let the panel's first status poll resolve before the test interacts.
  await act(async () => {
    await Promise.resolve();
  });
  return view;
}

beforeEach(() => {
  vi.spyOn(api, "getActiveInjection").mockResolvedValue(null);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("roleFromToken", () => {
  it("reads the role claim", () => {
    expect(roleFromToken(ADMIN)).toBe("admin");
    expect(roleFromToken(OPERATOR)).toBe("operator");
  });

  it("returns null for anything malformed or unknown", () => {
    expect(roleFromToken(null)).toBeNull();
    expect(roleFromToken("not.a.jwt.at.all")).toBeNull();
    expect(roleFromToken("a.%%%.c")).toBeNull();
    expect(roleFromToken(token({ role: "root" }))).toBeNull();
  });

  it("allows injection only for analyst and admin", () => {
    expect(canInject("admin")).toBe(true);
    expect(canInject("analyst")).toBe(true);
    expect(canInject("operator")).toBe(false);
    expect(canInject(null)).toBe(false);
  });
});

describe("validateInjection", () => {
  const spec = (id: string) => SCENARIOS.find((s) => s.id === id)!;

  it("requires every parameter as a finite number", () => {
    expect(validateInjection(spec("bias_fdi"), "60", {})).toMatch(/Offset needs a number/);
    expect(validateInjection(spec("bias_fdi"), "60", { bias: "abc" })).toMatch(/needs a number/);
    expect(validateInjection(spec("bias_fdi"), "60", { bias: "0.3" })).toEqual({
      params: { bias: 0.3 },
      duration: 60,
    });
  });

  it("bounds the duration", () => {
    expect(validateInjection(spec("stuck_at"), "0", {})).toMatch(/Duration/);
    expect(validateInjection(spec("stuck_at"), "601", {})).toMatch(/Duration/);
    expect(validateInjection(spec("stuck_at"), "2.5", {})).toMatch(/Duration/);
    expect(validateInjection(spec("stuck_at"), "30", {})).toEqual({ params: {}, duration: 30 });
  });

  it("enforces replay and stealth rules", () => {
    expect(validateInjection(spec("replay"), "60", { lookback_s: "30" })).toMatch(/overlap/);
    expect(validateInjection(spec("replay"), "60", { lookback_s: "90.5" })).toMatch(/whole/);
    expect(
      validateInjection(spec("adaptive_stealth_fdi"), "60", { rate: "0.1", residual_cap: "0" }),
    ).toMatch(/Cap/);
  });
});

describe("ScenarioInjectPanel", () => {
  it("hides the form from operators but explains why", async () => {
    await renderPanel(OPERATOR);
    expect(await screen.findByTestId("inject-forbidden")).toHaveTextContent("operator");
    expect(screen.queryByTestId("inject-submit")).toBeNull();
  });

  it("sends the typed scenario and shows it running", async () => {
    const spy = vi.spyOn(api, "injectScenario").mockResolvedValue(injection());
    await renderPanel(ADMIN, { current: 0.734 });

    fireEvent.click(screen.getByTestId("inject-use-current"));
    expect(screen.getByTestId("inject-param-value")).toHaveValue(0.734);
    fireEvent.change(screen.getByTestId("inject-duration"), { target: { value: "45" } });
    fireEvent.click(screen.getByTestId("inject-submit"));

    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    expect(spy).toHaveBeenCalledWith(
      "pump-01",
      { scenario: "constant_spoof", channel: "current", duration_s: 45, params: { value: 0.734 } },
      ADMIN,
    );
    expect(await screen.findByTestId("inject-active")).toHaveTextContent("Constant spoof");
    expect(screen.getByTestId("inject-badge")).toHaveTextContent("Attack running");
  });

  it("labels parameters with the channel unit and switches fields per scenario", async () => {
    await renderPanel(ADMIN);
    fireEvent.click(screen.getByTestId("scenario-ramp_fdi"));
    expect(screen.getByText("Slope (A/s)")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("scenario-stuck_at"));
    expect(screen.queryByTestId("inject-param-slope")).toBeNull();
    expect(screen.getByTestId("inject-submit")).toHaveTextContent("Inject fault");
  });

  it("blocks an invalid form client-side without calling the API", async () => {
    const spy = vi.spyOn(api, "injectScenario");
    await renderPanel(ADMIN);
    fireEvent.click(screen.getByTestId("inject-submit"));
    expect(screen.getByTestId("inject-error")).toHaveTextContent("Spoofed value needs a number");
    expect(spy).not.toHaveBeenCalled();
  });

  it("reports a broker outage honestly", async () => {
    vi.spyOn(api, "injectScenario").mockRejectedValue(
      new api.ApiError(503, "MQTT broker unavailable; command not sent"),
    );
    await renderPanel(ADMIN);
    fireEvent.change(screen.getByTestId("inject-param-value"), { target: { value: "1" } });
    fireEvent.click(screen.getByTestId("inject-submit"));
    expect(await screen.findByTestId("inject-error")).toHaveTextContent(
      "Not sent: MQTT broker unavailable",
    );
    expect(screen.queryByTestId("inject-active")).toBeNull();
  });

  it("shows a running injection from the backend and stops it", async () => {
    vi.spyOn(api, "getActiveInjection").mockResolvedValue(
      injection({ scenario: "drift", kind: "fault", channel: "vibration" }),
    );
    const cancel = vi
      .spyOn(api, "cancelScenario")
      .mockResolvedValue({ command_id: "abcdef1234567890", cancelled: true });
    await renderPanel(ADMIN);
    expect(await screen.findByTestId("inject-active")).toHaveTextContent("Gradual drift");
    expect(screen.getByTestId("inject-badge")).toHaveTextContent("Fault running");

    fireEvent.click(screen.getByTestId("inject-cancel"));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("pump-01", ADMIN));
    await waitFor(() => expect(screen.queryByTestId("inject-active")).toBeNull());
  });

  it("treats an expired injection as not running", async () => {
    const past = Date.now() - 120_000;
    vi.spyOn(api, "getActiveInjection").mockResolvedValue(
      injection({
        issued_at: new Date(past).toISOString(),
        expires_at: new Date(past + 60_000).toISOString(),
      }),
    );
    await renderPanel(ADMIN);
    await waitFor(() => expect(api.getActiveInjection).toHaveBeenCalled());
    expect(screen.queryByTestId("inject-active")).toBeNull();
  });
});
