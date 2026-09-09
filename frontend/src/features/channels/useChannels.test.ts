import { describe, expect, it } from "vitest";

import { normalizeSource } from "./useChannels";

describe("normalizeSource", () => {
  it("passes through the three documented sources", () => {
    expect(normalizeSource("live")).toBe("live");
    expect(normalizeSource("placeholder")).toBe("placeholder");
    expect(normalizeSource("unknown")).toBe("unknown");
  });

  it("degrades an unrecognised source to unknown, never to a positive claim", () => {
    // A future/garbled backend value must not be rendered as "live" (implying a
    // sensor exists) or as "placeholder" (implying we know one does not).
    expect(normalizeSource("simulated")).toBe("unknown");
    expect(normalizeSource("LIVE")).toBe("unknown");
    expect(normalizeSource(undefined)).toBe("unknown");
    expect(normalizeSource(null)).toBe("unknown");
    expect(normalizeSource(42)).toBe("unknown");
  });
});
