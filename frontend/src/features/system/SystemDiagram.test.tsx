import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SystemDiagram } from "./SystemDiagram";

const health = {
  status: "ok",
  mqtt_connected: false,
  db_connected: true,
  db_error: null,
  telemetry_count: 10,
  devices: ["pump-01"],
  ws_clients: 1,
};
const browser = {
  connection: "open" as const,
  snapshot: {
    samples: 0,
    p50Ms: null,
    p95Ms: null,
    maxMs: null,
    negativeSamples: 0,
    implausibleSamples: 0,
    clockSkewSuspected: false,
  },
};

describe("live architecture diagram (D059)", () => {
  it("lights each stage from its own health signal", () => {
    render(<SystemDiagram health={health} system={null} channels={[]} browser={browser} />);
    expect(screen.getByTestId("arch-mqtt")).toHaveAttribute("data-level", "alarm");
    expect(screen.getByTestId("arch-backend")).toHaveAttribute("data-level", "ok");
    expect(screen.getByTestId("arch-ui")).toHaveAttribute("data-level", "ok");
    expect(screen.getByTestId("arch-mqtt")).toHaveTextContent("disconnected");
  });
});
