// AC10 P5-3: each stored condition maps to its own status tone (D043).
import { describe, expect, it } from "vitest";

import { healthTone } from "./DevicesPage";

describe("health -> status tone", () => {
  it("maps each condition to its own tone", () => {
    expect(healthTone("healthy")).toBe("healthy");
    expect(healthTone("warning")).toBe("warning");
    expect(healthTone("critical")).toBe("critical");
  });
});
