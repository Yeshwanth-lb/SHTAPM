import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ChannelProvenanceBadge } from "./ChannelProvenanceBadge";

describe("ChannelProvenanceBadge", () => {
  it("labels a measured channel LIVE", () => {
    render(<ChannelProvenanceBadge source="live" />);
    expect(screen.getByTestId("provenance-live")).toHaveTextContent("LIVE");
  });

  it("labels a fake constant PLACEHOLDER", () => {
    render(<ChannelProvenanceBadge source="placeholder" />);
    expect(screen.getByTestId("provenance-placeholder")).toHaveTextContent("PLACEHOLDER");
  });

  it("labels an undeclared channel UNVERIFIED, not PLACEHOLDER", () => {
    // "we were not told" must read differently from "nothing is connected".
    render(<ChannelProvenanceBadge source="unknown" />);
    const badge = screen.getByTestId("provenance-unknown");
    expect(badge).toHaveTextContent("UNVERIFIED");
    expect(badge).not.toHaveTextContent("PLACEHOLDER");
  });

  it("carries an explanatory title so the state is not colour-only", () => {
    render(<ChannelProvenanceBadge source="placeholder" />);
    expect(screen.getByTestId("provenance-placeholder")).toHaveAttribute(
      "title",
      expect.stringContaining("no sensor is connected") as unknown as string,
    );
  });
});
