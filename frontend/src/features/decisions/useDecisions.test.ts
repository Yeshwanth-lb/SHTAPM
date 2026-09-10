import { describe, expect, it } from "vitest";

import { CHANNELS } from "../../types/contracts";
import {
  UNCOMPUTED_DECISION_FIELDS,
  trustBand,
  trustScores,
  type DecisionOut,
} from "./useDecisions";

function row(over: Partial<DecisionOut> = {}): DecisionOut {
  return {
    ts: "2026-09-10T12:00:00Z",
    anomaly_flag: false,
    anomaly_severity: 0,
    attribution: null,
    reason: null,
    trust_temperature: 0.9,
    trust_vibration: 0.5,
    trust_pressure: 0.2,
    trust_humidity: 0.9,
    trust_gas: 0.9,
    trust_current: 0.9,
    health_state: null,
    failure_eta: null,
    rl_action: null,
    isolated_channels: null,
    substituted_channels: null,
    ...over,
  };
}

describe("trustBand", () => {
  it("uses the specified bands: >=0.7 trusted, >=0.4 suspicious, else malicious", () => {
    expect(trustBand(0.95)).toBe("trusted");
    expect(trustBand(0.7)).toBe("trusted"); // boundary is inclusive
    expect(trustBand(0.69)).toBe("suspicious");
    expect(trustBand(0.4)).toBe("suspicious");
    expect(trustBand(0.39)).toBe("malicious");
    expect(trustBand(0)).toBe("malicious");
  });

  it("reports an absent score as unknown, never as trusted", () => {
    // "Not computed" and "fully trusted" must never collapse together.
    expect(trustBand(null)).toBe("unknown");
    expect(trustBand(undefined)).toBe("unknown");
    expect(trustBand(NaN)).toBe("unknown");
  });
});

describe("trustScores", () => {
  it("extracts every frozen channel", () => {
    const scores = trustScores(row());
    expect(Object.keys(scores).sort()).toEqual([...CHANNELS].sort());
    expect(scores.temperature).toBe(0.9);
    expect(scores.pressure).toBe(0.2);
  });

  it("returns nulls when there is no decision row", () => {
    const scores = trustScores(null);
    expect(CHANNELS.every((c) => scores[c] === null)).toBe(true);
  });

  it("keeps a genuine zero score as zero, not as missing", () => {
    // Trust 0.0 is the strongest possible malicious signal; losing it to a
    // null check would silently hide a fully-distrusted channel.
    const scores = trustScores(row({ trust_vibration: 0 }));
    expect(scores.vibration).toBe(0);
    expect(trustBand(scores.vibration)).toBe("malicious");
  });
});

describe("UNCOMPUTED_DECISION_FIELDS", () => {
  it("names every schema field no producer writes, with a reason", () => {
    const fields = UNCOMPUTED_DECISION_FIELDS.map((f) => f.field);
    expect(fields).toContain("health_state");
    expect(fields).toContain("failure_eta");
    expect(fields).toContain("rl_action");
    expect(fields).toContain("isolated_channels");
    expect(fields).toContain("substituted_channels");
    expect(UNCOMPUTED_DECISION_FIELDS.every((f) => f.why.length > 0)).toBe(true);
  });

  it("does not list fields that ARE written", () => {
    const fields = UNCOMPUTED_DECISION_FIELDS.map((f) => f.field);
    expect(fields).not.toContain("anomaly_flag");
    expect(fields).not.toContain("anomaly_severity");
    expect(fields).not.toContain("trust_temperature");
  });

  it("has no notion of confidence — none exists to report", () => {
    const fields = UNCOMPUTED_DECISION_FIELDS.map((f) => f.field);
    expect(fields.some((f) => f.includes("confidence"))).toBe(false);
    expect(Object.keys(row()).some((k) => k.includes("confidence"))).toBe(false);
  });
});
