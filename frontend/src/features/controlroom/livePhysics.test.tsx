import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { Instrument } from "./components";
import { DemoPresets } from "./DemoPresets";
import { PhysicsPanel, physicsVerdict } from "./PhysicsPanel";

const S = (state: "idle" | "running" | "unclear", median: number) => ({
  state,
  median,
  idle_max: 0.14,
  running_min: 0.31,
});
const live = (current: ReturnType<typeof S>, vibration: ReturnType<typeof S>) => ({
  device_id: "pump-01",
  ts: "2026-10-29T10:00:00Z",
  motor_state: { current, vibration },
  twin_values: {},
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("physics panel (D054)", () => {
  it("calls agreement, contradiction, transition and absence by name", () => {
    expect(physicsVerdict(live(S("running", 0.7), S("running", 0.6)).motor_state)).toBe("agree");
    expect(physicsVerdict(live(S("idle", 0), S("running", 0.6)).motor_state)).toBe("conflict");
    expect(physicsVerdict(live(S("idle", 0), S("unclear", 0.2)).motor_state)).toBe("unclear");
    expect(physicsVerdict(null)).toBe("unknown");
  });

  it("shows both readings and flags an impossible combination", () => {
    render(<PhysicsPanel live={live(S("idle", 0), S("running", 0.6))} />);
    expect(screen.getByTestId("physics-current")).toHaveTextContent("IDLE");
    expect(screen.getByTestId("physics-vibration")).toHaveTextContent("RUNNING");
    expect(screen.getByTestId("physics-verdict")).toHaveTextContent("Physically impossible");
  });
});

describe("demo presets (D056)", () => {
  it("only allows the scenarios the motor state makes meaningful, and sends the rehearsed values", async () => {
    vi.spyOn(api, "getActiveInjection").mockResolvedValue(null);
    const inject = vi.spyOn(api, "injectScenario").mockResolvedValue({} as never);
    render(
      <DemoPresets
        deviceId="pump-01"
        accessToken="acc"
        live={live(S("running", 0.7), S("running", 0.6))}
      />,
    );
    await waitFor(() => expect(screen.getByTestId("preset-spoof")).not.toBeDisabled());
    expect(screen.getByTestId("preset-bias")).toBeDisabled(); // needs the motor OFF
    expect(screen.getByTestId("preset-bias")).toHaveTextContent("Switch the motor OFF first");
    fireEvent.click(screen.getByTestId("preset-spoof"));
    await waitFor(() =>
      expect(inject).toHaveBeenCalledWith(
        "pump-01",
        { scenario: "constant_spoof", channel: "current", duration_s: 40, params: { value: 0 } },
        "acc",
      ),
    );
  });
});

describe("twin value on a VIRTUAL instrument (D054)", () => {
  it("shows the reconstruction and strikes the untrusted sensor reading", () => {
    render(
      <Instrument
        channel="current"
        value={0}
        unit="A"
        points={[]}
        trust={0.2}
        state={{ severity: "alarm", tags: [{ label: "VIRTUAL", severity: "virtual" }] }}
        twinValue={0.71}
      />,
    );
    expect(screen.getByTestId("instrument-sensor-current")).toHaveTextContent(
      "sensor reports 0.000 A · not trusted",
    );
  });
});
