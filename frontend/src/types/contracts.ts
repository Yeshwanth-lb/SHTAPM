// SHTAPM canonical shared data contract (D006 / D007) — mirror of
// backend/app/schemas/contracts.py. Authoritative field names/shapes: Doc05
// §05.8. Keep this file in EXACT sync with the Python source (the contract is
// sacred, TRD §02.6). PRD §10.3 shorthand (temp/vib, s1..s6, nested healing)
// is superseded. MQTT payloads carry no `type`; the WS layer wraps them.

export const CHANNELS = [
  "temperature",
  "vibration",
  "pressure",
  "humidity",
  "gas",
  "current",
] as const;
export type Channel = (typeof CHANNELS)[number];

export type Attribution = "none" | "fault" | "attack";
export type HealthState = "healthy" | "warning" | "critical";
export type RLAction = "continue" | "reduce_weight" | "isolate" | "alert" | "safe_stop";

export interface SensorReadings {
  temperature: number;
  vibration: number;
  pressure: number;
  humidity: number;
  gas: number;
  current: number;
}

export interface TelemetryMessage {
  device_id: string;
  ts: string; // ISO-8601 with ms
  sensors: SensorReadings;
  sample_seq: number;
}

export interface AnomalyInfo {
  flag: boolean;
  severity: number; // 0..1
  attribution: Attribution;
  reason: string;
}

// Same six channel keys as SensorReadings; values are trust scores in 0..1.
export type TrustScores = SensorReadings;

export interface DecisionMessage {
  device_id: string;
  ts: string;
  anomaly: AnomalyInfo;
  trust: TrustScores;
  health: HealthState;
  failure_eta: number;
  rl_action: RLAction;
  isolated: Channel[]; // ruling C — flat arrays, not nested healing:{}
  substituted: Channel[];
}

export interface LedgerMessage {
  device_id: string;
  ts: string;
  block_index: number;
  event: string;
  payload_hash: string; // ruling D — required
  prev_hash: string;
  this_hash: string;
}

// WebSocket envelope (ruling E): type is a WS concern; MQTT payloads omit it.
export type WSFrameType =
  | "telemetry"
  | "decision"
  | "ledger"
  | "device_status"
  | "system_health"
  | "alert";
export type WSFrame<T> = { type: WSFrameType } & T;

// Canonical valid examples (also give tsc a compile-time shape check).
export const EXAMPLE_TELEMETRY: TelemetryMessage = {
  device_id: "pump-01",
  ts: "2026-08-09T12:00:00.000Z",
  sensors: { temperature: 24.5, vibration: 0.03, pressure: 1013.2, humidity: 41.0, gas: 120.0, current: 0.42 },
  sample_seq: 123,
};

export const EXAMPLE_DECISION: DecisionMessage = {
  device_id: "pump-01",
  ts: "2026-08-09T12:00:03.000Z",
  anomaly: { flag: true, severity: 0.82, attribution: "attack", reason: "pressure vs current" },
  trust: { temperature: 0.95, vibration: 0.93, pressure: 0.21, humidity: 0.9, gas: 0.88, current: 0.97 },
  health: "warning",
  failure_eta: 142,
  rl_action: "isolate",
  isolated: ["pressure"],
  substituted: ["pressure"],
};

export const EXAMPLE_LEDGER: LedgerMessage = {
  device_id: "pump-01",
  ts: "2026-08-09T12:00:03.100Z",
  block_index: 57,
  event: "isolate",
  payload_hash: "9f0c",
  prev_hash: "7a3b",
  this_hash: "a1b2",
};
