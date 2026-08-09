// M3.5 component test (Vitest + jsdom + RTL). Runs in CI (npm blocked locally).
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TelemetryView } from "./TelemetryView";
import type { TelemetryMessage } from "../../types/contracts";

const msg: TelemetryMessage = {
  device_id: "pump-01",
  ts: "2026-08-09T12:00:00.000Z",
  sensors: { temperature: 26, vibration: 0.03, pressure: 1013, humidity: 45, gas: 150, current: 0.42 },
  sample_seq: 4,
};

describe("TelemetryView", () => {
  it("shows empty state when no telemetry", () => {
    render(<TelemetryView byDevice={{}} status="connecting" />);
    expect(screen.getByTestId("empty")).toBeInTheDocument();
    expect(screen.getByTestId("conn-status")).toHaveTextContent("connecting");
  });

  it("renders a device row with all six channel values", () => {
    render(<TelemetryView byDevice={{ "pump-01": msg }} status="open" />);
    const row = screen.getByTestId("row-pump-01");
    expect(row).toHaveTextContent("pump-01");
    expect(row).toHaveTextContent("26");
    expect(row).toHaveTextContent("1013");
    expect(row).toHaveTextContent("0.42");
    expect(row).toHaveTextContent("4"); // sample_seq
  });
});
