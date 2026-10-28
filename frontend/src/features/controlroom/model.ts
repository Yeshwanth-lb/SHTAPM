// Control-room display rules (D046), kept pure so every safety-relevant
// mapping is unit-tested. Nothing here decides anything: it only translates
// what the edge and backend already reported into lamps, tags and words.
//
// Severity ladder (ISA-101 style, abnormal-only colour):
//   alarm    red     an attack, a latched Safe Pump-Stop, trust below 0.40
//   caution  amber   a fault, a dead sensor, an isolated channel, a lost stream
//   virtual  magenta a channel whose value is being reconstructed (VIRTUAL)
//   normal   grey    nothing to report
import type { ActuationStatus } from "../../lib/api";
import type { DecisionOut } from "../decisions/useDecisions";
import { CHANNELS, type Channel } from "../../types/contracts";

export type Severity = "normal" | "virtual" | "caution" | "alarm";

const SHORT: Record<Channel, string> = {
  temperature: "TEMP",
  vibration: "VIB",
  pressure: "PRES",
  humidity: "HUM",
  gas: "GAS",
  current: "CURR",
};

export function shortName(channel: string): string {
  return SHORT[channel as Channel] ?? channel.toUpperCase();
}

/** Channels named in a decision reason ("current: physics violation...; vibration: ..."). */
export function channelsInReason(reason: string | null | undefined): Set<string> {
  const out = new Set<string>();
  if (!reason) return out;
  for (const part of reason.split(";")) {
    const name = part.split(":")[0]?.trim();
    if (name && (CHANNELS as readonly string[]).includes(name)) out.add(name);
  }
  return out;
}

function trustOf(decision: DecisionOut | null, channel: string): number | null {
  if (!decision) return null;
  const value = decision[`trust_${channel}` as keyof DecisionOut];
  return typeof value === "number" ? value : null;
}

const CAUSE_TEXT: Record<string, string> = {
  safe_stop: "self-heal escalation",
  dry_run: "dry run detected",
  watchdog: "watchdog",
};

// FAULT on-delay (D048), the same rule as the backend condition rollup (D043,
// backend/app/services/condition.py): a fault is shown only when faults or
// attacks were attributed in MAJORITY of the last WINDOW decisions. On clean
// held-out bench data (2026-10-28) the raw label lit FAULT in 14% of decisions
// and changed 63 times in 8 minutes; with this rule, 5 episodes. An attack is
// never delayed (0 false attacks on the same data).
export const FAULT_WINDOW = 10;
export const FAULT_MAJORITY = 5;

/** The decision to display, from the recent ones (newest first). */
export function displayedDecision(recent: DecisionOut[] | null | undefined): DecisionOut | null {
  const latest = recent?.[0] ?? null;
  if (!latest || latest.attribution !== "fault") return latest;
  const abnormal = recent!
    .slice(0, FAULT_WINDOW)
    .filter((d) => d.attribution === "fault" || d.attribution === "attack").length;
  return abnormal >= FAULT_MAJORITY ? latest : { ...latest, attribution: "none", reason: null };
}

export interface CautionState {
  severity: Severity;
  lamp: string;
  title: string;
  detail: string;
}

export function cautionState(input: {
  decision: DecisionOut | null;
  stale: Record<string, string>;
  relay: ActuationStatus | null;
  streamOpen: boolean;
}): CautionState {
  const { decision, stale, relay, streamOpen } = input;
  if (relay && relay.relay === "off" && relay.latched && relay.cause in CAUSE_TEXT) {
    return {
      severity: "alarm",
      lamp: "PUMP TRIP",
      title: `Safe Pump-Stop: ${CAUSE_TEXT[relay.cause]}`,
      detail: relay.reason,
    };
  }
  if (decision?.attribution === "attack") {
    return {
      severity: "alarm",
      lamp: "ATTACK",
      title: "Attack: a sensor reports something physically impossible",
      detail: decision.reason ?? "",
    };
  }
  const deadChannels = Object.keys(stale);
  if (deadChannels.length > 0) {
    return {
      severity: "caution",
      lamp: "SENSOR FAIL",
      title: `Sensor not responding: ${deadChannels.join(", ")}`,
      detail: "Holding its last good reading so the rest of the system keeps running.",
    };
  }
  if (decision?.attribution === "fault") {
    return {
      severity: "caution",
      lamp: "FAULT",
      title: "Fault: an anomaly consistent with the pump's physics",
      detail: decision.reason ?? "",
    };
  }
  const isolated = decision?.isolated_channels ?? [];
  if (isolated.length > 0) {
    return {
      severity: "caution",
      lamp: "ISOLATED",
      title: `Isolated: ${isolated.join(", ")}`,
      detail: "Excluded from trust until its readings are trustworthy again.",
    };
  }
  if (!streamOpen) {
    return {
      severity: "caution",
      lamp: "NO DATA",
      title: "Live stream disconnected",
      detail: "Reconnecting automatically; values shown are the last received.",
    };
  }
  return { severity: "normal", lamp: "NORMAL", title: "All systems normal", detail: "" };
}

export interface ChannelState {
  severity: Severity;
  tags: { label: string; severity: Severity }[];
}

export function channelState(
  channel: string,
  decision: DecisionOut | null,
  stale: Record<string, string>,
): ChannelState {
  const tags: { label: string; severity: Severity }[] = [];
  const named = channelsInReason(decision?.reason).has(channel);
  if (named && decision?.attribution === "attack")
    tags.push({ label: "ATTACK", severity: "alarm" });
  if (named && decision?.attribution === "fault")
    tags.push({ label: "FAULT", severity: "caution" });
  if (channel in stale) tags.push({ label: "SENSOR DEAD", severity: "caution" });
  if (decision?.substituted_channels?.includes(channel)) {
    tags.push({ label: "VIRTUAL", severity: "virtual" });
  } else if (decision?.isolated_channels?.includes(channel)) {
    tags.push({ label: "ISOLATED", severity: "caution" });
  }
  const trust = trustOf(decision, channel);
  if (trust !== null && trust < 0.4) tags.push({ label: "LOW TRUST", severity: "alarm" });
  const order: Severity[] = ["alarm", "caution", "virtual"];
  const severity = order.find((s) => tags.some((t) => t.severity === s)) ?? "normal";
  return { severity, tags };
}

export interface AnnunciatorWindow {
  channel: string;
  label: string;
  severity: Severity;
}

export function annunciatorWindows(
  decision: DecisionOut | null,
  stale: Record<string, string>,
): AnnunciatorWindow[] {
  return CHANNELS.map((channel) => {
    const state = channelState(channel, decision, stale);
    const top = state.tags.find((t) => t.severity === state.severity);
    return {
      channel,
      label: top ? `${shortName(channel)} ${top.label}` : shortName(channel),
      severity: state.severity,
    };
  });
}

export function trustTone(trust: number | null): Severity {
  if (trust === null) return "normal";
  if (trust < 0.4) return "alarm";
  if (trust < 0.7) return "caution";
  return "normal";
}

export interface LedgerEvent {
  block_index: number;
  ts: string;
  event_type: string;
  payload: Record<string, unknown>;
}

export interface LogLine {
  key: number;
  ts: string;
  severity: Severity | "info";
  text: string;
}

function str(value: unknown): string {
  return typeof value === "string" ? value : value === undefined ? "" : String(value);
}

/** One audit-ledger block as an operator-readable log line. */
export function describeEvent(event: LedgerEvent): LogLine {
  const p = event.payload ?? {};
  const ch = str(p.channel);
  const base = { key: event.block_index, ts: event.ts };
  switch (event.event_type) {
    case "trust_drop":
      return { ...base, severity: "alarm", text: `Trust fell below 0.40 on ${ch}` };
    case "isolate":
      return { ...base, severity: "virtual", text: `${ch} isolated; digital twin substituting` };
    case "recover":
      return { ...base, severity: "info", text: `${ch} released from isolation` };
    case "sensor_dead":
      return { ...base, severity: "caution", text: `${ch} sensor stopped responding` };
    case "sensor_recovered":
      return { ...base, severity: "info", text: `${ch} sensor responding again` };
    case "safe_stop":
      return {
        ...base,
        severity: "alarm",
        text: `SAFE PUMP-STOP (${CAUSE_TEXT[str(p.cause)] ?? str(p.cause)}): ${str(p.reason)}`,
      };
    case "relay_on":
      return { ...base, severity: "info", text: `Pump running (${str(p.reason)})` };
    case "relay_off":
      return { ...base, severity: "normal", text: `Pump stopped (${str(p.reason)})` };
    case "relay_command":
      return {
        ...base,
        severity: "info",
        text: `Pump ${str(p.state) === "on" ? "start" : "stop"} requested by ${str(p.issued_by)}`,
      };
    case "scenario_inject":
      return {
        ...base,
        severity: "caution",
        text: `Test ${str(p.kind)} injected: ${str(p.scenario)} on ${ch} for ${str(p.duration_s)} s`,
      };
    case "scenario_cancel":
      return { ...base, severity: "info", text: "Test scenario cancelled" };
    default:
      return { ...base, severity: "normal", text: event.event_type };
  }
}

/** Parse a backend timestamp. Ledger times are stored in UTC; a value without
 * an explicit zone is therefore UTC, never the browser's local time. */
export function parseServerTime(ts: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`);
}

/** "20:30:33" for today, "26 Oct 20:44:26" for anything older. */
export function formatEventTime(ts: string, now: Date = new Date()): string {
  const at = parseServerTime(ts);
  const time = at.toLocaleTimeString();
  return at.toDateString() === now.toDateString()
    ? time
    : `${at.toLocaleDateString(undefined, { day: "numeric", month: "short" })} ${time}`;
}
