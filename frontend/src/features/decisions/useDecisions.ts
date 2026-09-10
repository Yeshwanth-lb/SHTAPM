// Decision / diagnostic rows for one device.
//
// WHAT THESE ROWS ARE: output of the edge's P2 pipeline (preprocess → anomaly →
// trust → attribution), published on shtapm/{device}/decision_diagnostic and
// persisted by the backend. They are DERIVED STATE, not telemetry, and the
// producer labels itself `diagnostic_unvalidated`.
//
// WHAT THEY ARE NOT: a validated model output. The detector currently wired is
// a null detector that never flags by design, so `anomaly_flag: false` means
// "the pipeline ran", not "no anomaly exists". Callers must not present it as
// an all-clear.
import { apiGet, type ApiError } from "../../lib/api";
import { useApiResource, type ApiResource } from "../../lib/useApiResource";
import { CHANNELS, type Channel } from "../../types/contracts";

/** Mirrors backend DecisionOut (api/devices.py). */
export interface DecisionOut {
  ts: string;
  anomaly_flag: boolean | null;
  anomaly_severity: number | null;
  attribution: string | null;
  reason: string | null;
  trust_temperature: number | null;
  trust_vibration: number | null;
  trust_pressure: number | null;
  trust_humidity: number | null;
  trust_gas: number | null;
  trust_current: number | null;
  // Present in the schema but never written by any current producer. Null here
  // means UNIMPLEMENTED CAPABILITY, not "nothing to report".
  health_state: string | null;
  failure_eta: number | null;
  rl_action: string | null;
  isolated_channels: string[] | null;
  substituted_channels: string[] | null;
}

/** Mirrors backend DecisionProvenanceOut (api/devices.py). */
export interface DecisionProvenance {
  execution_mode: string;
  data_source: string;
  model_status: string;
  note: string;
}

/** Trust bands, from PRD/Doc04 §04.2: >=0.7 trusted, 0.4–0.7 suspicious, <0.4 malicious. */
export type TrustBand = "trusted" | "suspicious" | "malicious" | "unknown";

export function trustBand(score: number | null | undefined): TrustBand {
  if (score === null || score === undefined || Number.isNaN(score)) return "unknown";
  if (score >= 0.7) return "trusted";
  if (score >= 0.4) return "suspicious";
  return "malicious";
}

/** Pull the six per-channel trust scores off one decision row. */
export function trustScores(row: DecisionOut | null): Record<Channel, number | null> {
  const out = {} as Record<Channel, number | null>;
  for (const channel of CHANNELS) {
    const key = `trust_${channel}` as keyof DecisionOut;
    const value = row ? row[key] : null;
    out[channel] = typeof value === "number" ? value : null;
  }
  return out;
}

/**
 * Fields the schema defines but no producer writes. Returned so the UI can
 * list them as unimplemented rather than rendering a misleading blank.
 */
export const UNCOMPUTED_DECISION_FIELDS = [
  { field: "health_state", why: "no prognosis model exists (D017)" },
  { field: "failure_eta", why: "no prognosis model exists (D017)" },
  { field: "rl_action", why: "no RL policy is wired (U06 open)" },
  { field: "isolated_channels", why: "no isolation is executed; the live path is observe-only" },
  { field: "substituted_channels", why: "no self-healing substitution is executed" },
  { field: "attribution", why: "not published by the diagnostic path" },
] as const;

export function useDecisions(
  deviceId: string,
  accessToken: string | null,
  limit = 120,
): ApiResource<DecisionOut[]> {
  return useApiResource<DecisionOut[]>(
    () =>
      apiGet<DecisionOut[]>(
        `/api/devices/${encodeURIComponent(deviceId)}/decisions?limit=${limit}`,
        accessToken!,
      ),
    [deviceId, accessToken, limit],
    { enabled: accessToken !== null },
  );
}

export function useDecisionProvenance(
  deviceId: string,
  accessToken: string | null,
): ApiResource<DecisionProvenance> {
  return useApiResource<DecisionProvenance>(
    () =>
      apiGet<DecisionProvenance>(
        `/api/devices/${encodeURIComponent(deviceId)}/decisions/provenance`,
        accessToken!,
      ),
    [deviceId, accessToken],
    { enabled: accessToken !== null },
  );
}

export type { ApiError };
