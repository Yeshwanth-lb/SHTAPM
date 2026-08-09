import { describe, it, expect } from "vitest";

import {
  CHANNELS,
  EXAMPLE_DECISION,
  EXAMPLE_LEDGER,
  EXAMPLE_TELEMETRY,
} from "../types/contracts";

// P0 M2: the TS mirror is compile-time-checked by tsc; these runtime checks
// assert the canonical examples keep the frozen field set (D006/D007). Real
// runtime validation (if a validator is added) lands with the app in P5.
describe("shared contract (TS mirror)", () => {
  it("telemetry has the six full channel names", () => {
    expect(Object.keys(EXAMPLE_TELEMETRY.sensors).sort()).toEqual([...CHANNELS].sort());
  });

  it("decision trust uses the six full channel names, flat heal arrays", () => {
    expect(Object.keys(EXAMPLE_DECISION.trust).sort()).toEqual([...CHANNELS].sort());
    expect(Array.isArray(EXAMPLE_DECISION.isolated)).toBe(true);
    expect(Array.isArray(EXAMPLE_DECISION.substituted)).toBe(true);
    expect("healing" in EXAMPLE_DECISION).toBe(false);
  });

  it("ledger keeps payload_hash", () => {
    expect(EXAMPLE_LEDGER.payload_hash).toBeTruthy();
  });
});
