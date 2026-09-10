import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CHANNELS, type Channel } from "../../types/contracts";
import { nodeRadius, TrustConstellation } from "./TrustConstellation";

function scores(over: Partial<Record<Channel, number | null>> = {}) {
  const base = {} as Record<Channel, number | null>;
  for (const c of CHANNELS) base[c] = 0.9;
  return { ...base, ...over };
}

function empty() {
  const base = {} as Record<Channel, number | null>;
  for (const c of CHANNELS) base[c] = null;
  return base;
}

describe("nodeRadius", () => {
  it("scales with trust so value is encoded by size, not colour alone", () => {
    expect(nodeRadius(0)).toBeLessThan(nodeRadius(0.5));
    expect(nodeRadius(0.5)).toBeLessThan(nodeRadius(1));
  });

  it("gives an absent score the smallest node", () => {
    expect(nodeRadius(null)).toBe(nodeRadius(0));
  });

  it("clamps out-of-range scores rather than producing absurd sizes", () => {
    expect(nodeRadius(5)).toBe(nodeRadius(1));
    expect(nodeRadius(-5)).toBe(nodeRadius(0));
  });
});

describe("TrustConstellation", () => {
  it("renders a node for every frozen channel", () => {
    render(<TrustConstellation scores={scores()} />);
    for (const channel of CHANNELS) {
      expect(screen.getByTestId(`trust-node-${channel}`)).toBeInTheDocument();
    }
  });

  it("prints the numeric score alongside the band", () => {
    render(<TrustConstellation scores={scores({ pressure: 0.21 })} />);
    expect(screen.getByTestId("trust-score-pressure")).toHaveTextContent("0.21");
    expect(screen.getByTestId("trust-node-pressure")).toHaveTextContent("Malicious");
  });

  it("shows an absent score as 'Not computed', never as trusted", () => {
    render(<TrustConstellation scores={scores({ gas: null })} />);
    const node = screen.getByTestId("trust-node-gas");
    expect(screen.getByTestId("trust-score-gas")).toHaveTextContent("—");
    expect(node).toHaveTextContent("Not computed");
    expect(node).not.toHaveTextContent("Trusted");
  });

  it("marks trust in a non-live channel as trust in a placeholder", () => {
    render(<TrustConstellation scores={scores()} nonLiveChannels={new Set(["pressure", "gas"])} />);
    expect(screen.getByTestId("trust-nonlive-pressure")).toHaveTextContent("not a live sensor");
    expect(screen.queryByTestId("trust-nonlive-temperature")).toBeNull();
  });

  it("says so when nothing has been computed at all", () => {
    render(<TrustConstellation scores={empty()} />);
    expect(screen.getByTestId("trust-empty")).toBeInTheDocument();
  });

  it("does not claim an empty constellation is healthy", () => {
    render(<TrustConstellation scores={empty()} />);
    expect(screen.getByTestId("trust-constellation")).not.toHaveTextContent("Trusted");
  });
});
