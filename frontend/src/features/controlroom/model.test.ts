import { describe, expect, it } from "vitest";

import type { ActuationStatus } from "../../lib/api";
import type { DecisionOut } from "../decisions/useDecisions";
import {
  annunciatorWindows,
  cautionState,
  channelEvents,
  channelsInReason,
  channelStats,
  channelVerdicts,
  channelState,
  describeEvent,
  displayedDecision,
  formatEventTime,
  lastIncident,
  lastSeconds,
  parseServerTime,
  trustSeries,
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

describe("fault on-delay (D048)", () => {
  const fault = decision({ attribution: "fault", reason: "vibration: anomaly" });
  const clean = decision();

  it("hides a fault seen in fewer than 5 of the last 10 decisions", () => {
    const shown = displayedDecision([fault, fault, clean, fault, clean, fault, clean, clean]);
    expect([shown?.attribution, shown?.reason]).toEqual(["none", null]);
    expect(cautionState({ decision: shown, stale: {}, relay: null, streamOpen: true }).lamp).toBe(
      "NORMAL",
    );
  });

  it("shows a fault once it holds the majority", () => {
    const recent = [fault, fault, clean, fault, fault, fault, clean, clean, clean, clean];
    expect(displayedDecision(recent)?.attribution).toBe("fault");
  });

  it("only counts the last 10 decisions", () => {
    const recent = [fault, ...Array(9).fill(clean), fault, fault, fault, fault];
    expect(displayedDecision(recent)?.attribution).toBe("none");
  });

  it("never delays an attack, and keeps isolation and trust", () => {
    expect(displayedDecision([ATTACK, clean, clean])).toBe(ATTACK);
    const isolatedFault = { ...fault, isolated_channels: ["current"], trust_current: 0.3 };
    const shown = displayedDecision([isolatedFault, clean]);
    expect([shown?.isolated_channels, shown?.trust_current]).toEqual([["current"], 0.3]);
  });

  it("passes through an empty list", () => {
    expect(displayedDecision([])).toBeNull();
    expect(displayedDecision(null)).toBeNull();
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

describe("sensor detail helpers (D052)", () => {
  const pts = (values: number[]) =>
    values.map((value, i) => ({
      ts: `2026-10-28T10:00:${String(i * 10).padStart(2, "0")}Z`,
      value,
    }));

  it("summarises exactly the samples given", () => {
    const s = channelStats(pts([1, 2, 3, 4]));
    expect([s.n, s.now, s.min, s.max, s.mean]).toEqual([4, 4, 1, 4, 2.5]);
    expect(s.std).toBeCloseTo(Math.sqrt(1.25));
    expect(channelStats([]).mean).toBeNull();
  });

  it("keeps only the last N seconds", () => {
    expect(lastSeconds(pts([1, 2, 3, 4, 5, 6]), 20).map((p) => p.value)).toEqual([4, 5, 6]);
  });

  it("filters ledger events to one channel, newest first", () => {
    const ev = (i: number, channel: string) => ({
      block_index: i,
      ts: "2026-10-28T10:00:00Z",
      event_type: "isolate",
      payload: { channel },
    });
    const lines = channelEvents(
      [ev(1, "current"), ev(2, "vibration"), ev(3, "current")],
      "current",
    );
    expect(lines.map((l) => l.key)).toEqual([3, 1]);
  });

  it("counts verdicts that name the channel and builds its trust series", () => {
    const rows = [
      ATTACK,
      decision({ attribution: "fault", reason: "current: anomaly", trust_current: 0.6 }),
      decision({ attribution: "fault", reason: "gas: anomaly" }),
    ];
    expect(channelVerdicts(rows, "current")).toEqual({ attack: 1, fault: 1, total: 3 });
    expect(trustSeries(rows, "current").map((p) => p.value)).toEqual([0.9, 0.6, 0.31]);
  });
});

describe("incident timeline (D057)", () => {
  const ev = (block_index: number, sec: number, event_type: string, payload = {}) => ({
    block_index,
    ts: `2026-10-28T09:32:${String(sec).padStart(2, "0")}Z`,
    event_type,
    payload,
  });

  it("measures each step from the injection, on that channel only", () => {
    const incident = lastIncident([
      ev(1, 0, "relay_command", { state: "on" }),
      ev(2, 11, "scenario_inject", { scenario: "constant_spoof", channel: "current" }),
      ev(3, 29, "trust_drop", { channel: "current" }),
      ev(4, 34, "isolate", { channel: "current" }),
      ev(5, 35, "trust_drop", { channel: "pressure" }),
      ev(6, 58, "recover", { channel: "current" }),
    ]);
    expect(incident?.title).toBe("constant spoof on current");
    expect(incident?.steps.map((s) => [s.label, s.offsetS])).toEqual([
      ["Injected", 0],
      ["Detected (trust < 0.40)", 18],
      ["Isolated · twin took over", 23],
      ["Recovered", 47],
    ]);
    expect(incident?.resolvedAfterS).toBe(47);
  });

  it("is open until recovery and absent without incidents", () => {
    const open = lastIncident([ev(1, 0, "trust_drop", { channel: "current" })]);
    expect(open?.resolvedAfterS).toBeNull();
    expect(lastIncident([ev(1, 0, "relay_command", {})])).toBeNull();
  });
});
