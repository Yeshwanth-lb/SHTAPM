import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TrustTimeline, verdictOf } from "./TrustTimeline";
import type { DecisionOut } from "./useDecisions";

const d = (overrides: Partial<DecisionOut> = {}): DecisionOut => ({
  ts: "2026-10-29T10:00:00Z",
  anomaly_flag: false,
  anomaly_severity: 0.1,
  attribution: "none",
  reason: null,
  trust_temperature: 0.9,
  trust_vibration: 0.9,
  trust_pressure: 0.9,
  trust_humidity: 0.9,
  trust_gas: 0.9,
  trust_current: 0.9,
  health_state: null,
  failure_eta: null,
  rl_action: null,
  isolated_channels: [],
  substituted_channels: [],
  ...overrides,
});

describe("decisions timeline (D060)", () => {
  it("names what each decision concluded", () => {
    expect(verdictOf(d({ attribution: "attack" }))).toBe("attack");
    expect(verdictOf(d({ attribution: "fault" }))).toBe("fault");
    expect(verdictOf(d({ isolated_channels: ["current"] }))).toBe("isolated");
    expect(verdictOf(d())).toBe("normal");
  });

  it("draws one strip cell per decision and lets a channel be hidden", () => {
    render(<TrustTimeline rows={[d(), d({ attribution: "attack" }), d()]} />);
    expect(screen.getByTestId("verdict-strip").children).toHaveLength(3);
    fireEvent.click(screen.getByTestId("legend-gas"));
    expect(screen.getByTestId("legend-gas")).toHaveAttribute("aria-pressed", "false");
  });
});
