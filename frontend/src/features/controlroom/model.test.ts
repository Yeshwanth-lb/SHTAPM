import { describe, expect, it } from "vitest";

import type { ActuationStatus } from "../../lib/api";
import type { DecisionOut } from "../decisions/useDecisions";
import {
  annunciatorWindows,
  cautionState,
  channelsInReason,
  channelState,
  describeEvent,
  formatEventTime,
  parseServerTime,
  trustTone,
} from "./model";

function decision(overrides: Partial<DecisionOut> = {}): DecisionOut {
  return {
    ts: "2026-10-27T10:00:00.000Z",
    anomaly_flag: false,
    anomaly_severity: 0.1,
    attribution: "none",
    reason: null,
    trust_temperature: 0.9,
    trust_vibration: 0.9,
    trust_pressure: 0.9,
    trust_humidity: 0.9,
    trust_gas: 0.9,
    trust_current: 0.9,
    health_state: null,
    failure_eta: null,
    rl_action: null,
    isolated_channels: [],
    substituted_channels: [],
    ...overrides,
  };
}

const RELAY_TRIP: ActuationStatus = {
  device_id: "pump-01",
  ts: "2026-10-27T10:00:00.000Z",
  relay: "off",
  cause: "dry_run",
  reason: "dry run: current 0.300 A",
  latched: true,
  hardware: true,
};

const ATTACK = decision({
  attribution: "attack",
  reason: "current: physics violation: current says the motor is running",
  isolated_channels: ["current"],
  substituted_channels: ["current"],
  trust_current: 0.31,
});

describe("master caution", () => {
  it("is normal when nothing is wrong", () => {
    const s = cautionState({ decision: decision(), stale: {}, relay: null, streamOpen: true });
    expect([s.severity, s.lamp]).toEqual(["normal", "NORMAL"]);
  });

  it("puts a latched pump trip above everything else", () => {
    const s = cautionState({ decision: ATTACK, stale: {}, relay: RELAY_TRIP, streamOpen: true });
    expect([s.severity, s.lamp]).toEqual(["alarm", "PUMP TRIP"]);
    expect(s.title).toContain("dry run");
  });

  it("calls an attack an alarm and a fault a caution", () => {
    expect(cautionState({ decision: ATTACK, stale: {}, relay: null, streamOpen: true }).lamp).toBe(
      "ATTACK",
    );
    const fault = decision({ attribution: "fault", reason: "vibration: anomaly" });
    const s = cautionState({ decision: fault, stale: {}, relay: null, streamOpen: true });
    expect([s.severity, s.lamp]).toEqual(["caution", "FAULT"]);
  });

  it("names dead sensors and a lost stream", () => {
    const dead = cautionState({
      decision: decision(),
      stale: { humidity: "2026-10-27T10:00:00Z" },
      relay: null,
      streamOpen: true,
    });
    expect(dead.lamp).toBe("SENSOR FAIL");
    expect(dead.title).toContain("humidity");
    const lost = cautionState({ decision: decision(), stale: {}, relay: null, streamOpen: false });
    expect(lost.lamp).toBe("NO DATA");
  });

  it("does not trip on an operator stop", () => {
    const stopped = { ...RELAY_TRIP, cause: "command" as const, latched: false };
    const s = cautionState({ decision: decision(), stale: {}, relay: stopped, streamOpen: true });
    expect(s.severity).toBe("normal");
  });
});

describe("per-channel state", () => {
  it("parses the channels named in a reason", () => {
    expect(channelsInReason("current: x; vibration: y")).toEqual(new Set(["current", "vibration"]));
    expect(channelsInReason(null).size).toBe(0);
  });

  it("tags the attacked channel only", () => {
    const current = channelState("current", ATTACK, {});
    expect(current.severity).toBe("alarm");
    expect(current.tags.map((t) => t.label)).toEqual(["ATTACK", "VIRTUAL", "LOW TRUST"]);
    expect(channelState("vibration", ATTACK, {}).severity).toBe("normal");
  });

  it("marks a dead sensor and an isolation without substitution", () => {
    const d = decision({ isolated_channels: ["pressure"] });
    expect(channelState("pressure", d, {}).tags.map((t) => t.label)).toEqual(["ISOLATED"]);
    expect(channelState("humidity", d, { humidity: "t" }).tags[0].label).toBe("SENSOR DEAD");
  });

  it("lights the annunciator window with the worst condition", () => {
    const windows = annunciatorWindows(ATTACK, { humidity: "t" });
    const byChannel = Object.fromEntries(windows.map((w) => [w.channel, w]));
    expect(byChannel.current.label).toBe("CURR ATTACK");
    expect(byChannel.current.severity).toBe("alarm");
    expect(byChannel.humidity.label).toBe("HUM SENSOR DEAD");
    expect(byChannel.gas).toEqual({ channel: "gas", label: "GAS", severity: "normal" });
  });

  it("bands trust like the trust engine", () => {
    expect([trustTone(0.9), trustTone(0.5), trustTone(0.2), trustTone(null)]).toEqual([
      "normal",
      "caution",
      "alarm",
      "normal",
    ]);
  });
});

describe("event log", () => {
  const block = (event_type: string, payload: Record<string, unknown>) => ({
    block_index: 1,
    ts: "2026-10-27T10:00:00.000Z",
    event_type,
    payload,
  });

  it("describes every ledger event type in operator words", () => {
    expect(describeEvent(block("isolate", { channel: "current" })).text).toContain(
      "current isolated",
    );
    expect(describeEvent(block("sensor_dead", { channel: "humidity" })).severity).toBe("caution");
    const trip = describeEvent(block("safe_stop", { cause: "watchdog", reason: "no frames" }));
    expect([trip.severity, trip.text]).toEqual(["alarm", "SAFE PUMP-STOP (watchdog): no frames"]);
    expect(describeEvent(block("relay_command", { state: "on", issued_by: "admin@x" })).text).toBe(
      "Pump start requested by admin@x",
    );
    expect(describeEvent(block("something_new", {})).text).toBe("something_new");
  });
});

describe("event times", () => {
  it("reads a zone-less ledger time as UTC, not local", () => {
    expect(parseServerTime("2026-10-27T15:00:33").toISOString()).toBe("2026-10-27T15:00:33.000Z");
    expect(parseServerTime("2026-10-27T15:00:33Z").toISOString()).toBe("2026-10-27T15:00:33.000Z");
    expect(parseServerTime("2026-10-27T20:30:33+05:30").toISOString()).toBe(
      "2026-10-27T15:00:33.000Z",
    );
  });

  it("adds the date to events that are not from today", () => {
    const now = new Date("2026-10-27T15:05:00Z");
    expect(formatEventTime("2026-10-27T15:00:33", now)).not.toMatch(/Oct/);
    expect(formatEventTime("2026-10-25T15:14:26", now)).toMatch(/Oct/);
  });
});
