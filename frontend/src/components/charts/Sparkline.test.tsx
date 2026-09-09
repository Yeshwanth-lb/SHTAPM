import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { buildPath, Sparkline } from "./Sparkline";

const P = (values: number[]) =>
  values.map((value, i) => ({ ts: `2026-09-10T12:00:0${i}.000Z`, value }));

describe("buildPath", () => {
  it("is empty with no points", () => {
    expect(buildPath([], 100, 40)).toBe("");
  });

  it("plots one point per sample", () => {
    const path = buildPath(P([1, 2, 3, 4]), 100, 40);
    expect(path.startsWith("M")).toBe(true);
    expect(path.match(/L/g)).toHaveLength(3);
  });

  it("centres a constant series instead of dividing by zero", () => {
    // A placeholder channel is exactly this: the same value forever.
    const path = buildPath(P([1013, 1013, 1013]), 100, 40);
    expect(path).not.toContain("NaN");
    expect(path).toContain("20.00"); // vertical midpoint of height 40
  });

  it("produces no NaN for a single point", () => {
    expect(buildPath(P([5]), 100, 40)).not.toContain("NaN");
  });
});

describe("Sparkline", () => {
  it("renders an explicit empty state rather than a blank box", () => {
    render(<Sparkline points={[]} />);
    expect(screen.getByTestId("sparkline-empty")).toHaveTextContent("no history yet");
  });

  it("renders exactly the points it was given — none synthesised", () => {
    render(<Sparkline points={P([1, 2, 3])} />);
    expect(screen.getByTestId("sparkline")).toHaveAttribute("data-points", "3");
  });

  it("is labelled for assistive technology", () => {
    render(<Sparkline points={P([1, 2])} label="vibration recent history" />);
    expect(screen.getByLabelText("vibration recent history")).toBeInTheDocument();
  });
});
