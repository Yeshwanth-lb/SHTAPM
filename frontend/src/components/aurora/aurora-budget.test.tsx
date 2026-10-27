// AC10 P5-3 (health -> Aurora colour) and P6-8 (GPU budget: <= 4 orbs).
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { healthTone } from "../../pages/DevicesPage";
import { MeshBackground } from "./MeshBackground";

describe("health -> aurora colour mapping", () => {
  it("maps each health state to its own status tone", () => {
    expect(healthTone("healthy")).toBe("healthy");
    expect(healthTone("warning")).toBe("warning");
    expect(healthTone("critical")).toBe("critical");
  });

  it("drives the ambient field's palette class", () => {
    for (const health of ["healthy", "warning", "critical"] as const) {
      const { getByTestId, unmount } = render(<MeshBackground health={health} />);
      expect(getByTestId("mesh-background").className).toContain(`mesh--${health}`);
      unmount();
    }
  });
});

describe("GPU budget (TRD 02.9)", () => {
  it("renders at most four orbs", () => {
    const { container } = render(<MeshBackground />);
    expect(container.querySelectorAll(".mesh__orb").length).toBeLessThanOrEqual(4);
  });
});
