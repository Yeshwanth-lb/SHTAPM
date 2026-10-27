import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AttributionBanner } from "./AttributionBanner";
import type { DecisionOut } from "./useDecisions";

function decision(overrides: Partial<DecisionOut> = {}): DecisionOut {
  return {
    ts: "2026-10-27T10:00:00.000Z",
    anomaly_flag: true,
    anomaly_severity: 0.97,
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
  };
}

describe("AttributionBanner (D042)", () => {
  it("stays out of the way on a clean cycle", () => {
    const { container } = render(<AttributionBanner decision={decision()} />);
    expect(container.firstChild).toBeNull();
    const { container: empty } = render(<AttributionBanner decision={null} />);
    expect(empty.firstChild).toBeNull();
  });

  it("calls an attack an attack, with the channel and the physics reason", () => {
    render(
      <AttributionBanner
        decision={decision({
          attribution: "attack",
          reason: "current: physics violation: current says the motor is running",
          isolated_channels: ["current"],
          substituted_channels: ["current"],
        })}
      />,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByTestId("attribution-label")).toHaveTextContent("Attack");
    expect(screen.getByTestId("attribution-reason")).toHaveTextContent(
      "current: physics violation",
    );
    expect(screen.getByTestId("attribution-isolated")).toHaveTextContent("Isolated: current");
    expect(screen.getByTestId("attribution-isolated")).toHaveTextContent("VIRTUAL: current");
  });

  it("labels a fault as a fault, not as an attack", () => {
    render(
      <AttributionBanner
        decision={decision({ attribution: "fault", reason: "vibration: anomaly" })}
      />,
    );
    expect(screen.getByTestId("attribution-label")).toHaveTextContent("Fault");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an isolation that outlives the attributed anomaly", () => {
    render(<AttributionBanner decision={decision({ isolated_channels: ["current"] })} />);
    expect(screen.getByTestId("attribution-label")).toHaveTextContent("Sensor isolated");
  });
});
