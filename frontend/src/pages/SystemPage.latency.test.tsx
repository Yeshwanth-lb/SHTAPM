import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LatencySnapshot } from "../lib/latency";
import { BrowserLatencyPanel, formatMs } from "./SystemPage";

const base: LatencySnapshot = {
  samples: 0,
  p50Ms: null,
  p95Ms: null,
  maxMs: null,
  negativeSamples: 0,
  implausibleSamples: 0,
  clockSkewSuspected: false,
};

describe("BrowserLatencyPanel", () => {
  it("says it is waiting rather than showing a zero", () => {
    render(<BrowserLatencyPanel snapshot={base} connection="open" signedIn />);
    expect(screen.getByTestId("browser-latency-waiting")).toBeInTheDocument();
    expect(screen.queryByTestId("browser-latency")).toBeNull();
  });

  it("labels clock skew and reports no figure", () => {
    render(
      <BrowserLatencyPanel
        snapshot={{ ...base, samples: 3, negativeSamples: 2, clockSkewSuspected: true }}
        connection="open"
        signedIn
      />,
    );
    expect(screen.getByText("Clocks not synced")).toBeInTheDocument();
    expect(screen.getByTestId("browser-latency-skew")).toHaveTextContent("2 frame(s)");
    expect(screen.queryByTestId("browser-latency")).toBeNull();
  });

  it("shows p50/p95 and the 2 s target when measured", () => {
    render(
      <BrowserLatencyPanel
        snapshot={{ ...base, samples: 10, p50Ms: 180, p95Ms: 420, maxMs: 510 }}
        connection="open"
        signedIn
      />,
    );
    expect(screen.getByTestId("browser-latency")).toHaveTextContent("180 ms / 420 ms");
    expect(screen.getByText("met")).toBeInTheDocument();
  });

  it("marks the target missed when p95 is over 2 s", () => {
    render(
      <BrowserLatencyPanel
        snapshot={{ ...base, samples: 10, p50Ms: 1500, p95Ms: 2600, maxMs: 3000 }}
        connection="open"
        signedIn
      />,
    );
    expect(screen.getByText("missed")).toBeInTheDocument();
  });

  it("lists excluded late frames alongside a valid figure", () => {
    render(
      <BrowserLatencyPanel
        snapshot={{
          ...base,
          samples: 5,
          p50Ms: 200,
          p95Ms: 300,
          maxMs: 300,
          implausibleSamples: 1,
          clockSkewSuspected: true,
        }}
        connection="open"
        signedIn
      />,
    );
    expect(screen.getByTestId("browser-latency")).toBeInTheDocument();
    expect(screen.getByTestId("browser-latency-excluded")).toHaveTextContent("1 frame(s)");
  });
});

describe("formatMs", () => {
  it("formats ms and seconds, and a dash for null", () => {
    expect(formatMs(null)).toBe("—");
    expect(formatMs(412.6)).toBe("413 ms");
    expect(formatMs(1830)).toBe("1.83 s");
  });
});
