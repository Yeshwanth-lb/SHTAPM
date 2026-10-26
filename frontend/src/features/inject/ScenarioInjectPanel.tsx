// Scenario injection control (FR-D7, D032).
//
// Sends an authenticated command to the backend, which publishes it to the
// edge. The edge rewrites the chosen channel for a bounded time, so what the
// dashboard then shows -- the changed reading, trust falling, VIRTUAL, ledger
// blocks -- is the real pipeline reacting, not a client-side animation.
//
// Magnitudes are always typed by the operator: no scenario has a built-in
// value. The one convenience is "use current reading" for a constant spoof,
// which is the definition of a plausible spoof (pin the sensor where it is).
//
// Visibility follows the token's role claim (display only); the backend
// re-checks the role on every request and rejects anything else.
import { useCallback, useEffect, useMemo, useState } from "react";

import { GlassTile } from "../../components/aurora/GlassTile";
import type { ChannelOut } from "../channels/useChannels";
import {
  cancelScenario,
  describeRequestFailure,
  getActiveInjection,
  injectScenario,
  isApiError,
  MAX_INJECTION_DURATION_S,
  type InjectionOut,
  type InjectionScenario,
} from "../../lib/api";
import { canInject, roleFromToken } from "../../lib/token";
import { CHANNELS } from "../../types/contracts";
import "./inject.css";

interface ParamSpec {
  name: string;
  label: string;
  perSecond?: boolean;
  seconds?: boolean;
}

interface ScenarioSpec {
  id: InjectionScenario;
  label: string;
  kind: "fault" | "attack";
  description: string;
  params: ParamSpec[];
}

export const SCENARIOS: readonly ScenarioSpec[] = [
  {
    id: "constant_spoof",
    label: "Constant spoof",
    kind: "attack",
    description: "Pin the reading to a fixed, plausible value.",
    params: [{ name: "value", label: "Spoofed value" }],
  },
  {
    id: "bias_fdi",
    label: "Bias injection",
    kind: "attack",
    description: "Add a constant offset to the true reading.",
    params: [{ name: "bias", label: "Offset" }],
  },
  {
    id: "ramp_fdi",
    label: "Ramp injection",
    kind: "attack",
    description: "Add an offset that grows steadily.",
    params: [{ name: "slope", label: "Slope", perSecond: true }],
  },
  {
    id: "replay",
    label: "Replay",
    kind: "attack",
    description: "Replay this channel's real readings from earlier.",
    params: [{ name: "lookback_s", label: "Replay from", seconds: true }],
  },
  {
    id: "adaptive_stealth_fdi",
    label: "Stealth injection",
    kind: "attack",
    description: "A growing offset capped to stay under a naive residual check.",
    params: [
      { name: "rate", label: "Growth rate", perSecond: true },
      { name: "residual_cap", label: "Cap" },
    ],
  },
  {
    id: "drift",
    label: "Gradual drift",
    kind: "fault",
    description: "A sensor slowly drifting off calibration.",
    params: [{ name: "rate", label: "Drift rate", perSecond: true }],
  },
  {
    id: "spike",
    label: "Sudden spike",
    kind: "fault",
    description: "A sudden offset on every sample, like a glitching sensor.",
    params: [{ name: "amplitude", label: "Amplitude" }],
  },
  {
    id: "stuck_at",
    label: "Stuck sensor",
    kind: "fault",
    description: "The reading freezes at its value when the fault starts.",
    params: [],
  },
];

const POLL_MS = 5_000;

interface Props {
  deviceId: string;
  accessToken: string | null;
  liveValues: Record<string, number> | null;
  channels: ChannelOut[];
}

function errorText(err: unknown): string {
  if (isApiError(err)) {
    if (err.status === 403) return "Your role cannot inject scenarios (analyst or admin required).";
    if (err.status === 503) return `Not sent: ${err.message}`;
    return `${err.status}: ${err.message}`;
  }
  return describeRequestFailure(err);
}

export function validateInjection(
  spec: ScenarioSpec,
  duration: string,
  values: Record<string, string>,
): { params: Record<string, number>; duration: number } | string {
  const durationS = Number(duration);
  if (!Number.isInteger(durationS) || durationS < 1 || durationS > MAX_INJECTION_DURATION_S) {
    return `Duration must be a whole number of seconds from 1 to ${MAX_INJECTION_DURATION_S}.`;
  }
  const params: Record<string, number> = {};
  for (const p of spec.params) {
    const raw = (values[p.name] ?? "").trim();
    const n = Number(raw);
    if (raw === "" || !Number.isFinite(n)) return `${p.label} needs a number.`;
    params[p.name] = n;
  }
  if (spec.id === "adaptive_stealth_fdi" && params.residual_cap <= 0) {
    return "Cap must be greater than 0.";
  }
  if (spec.id === "replay") {
    if (!Number.isInteger(params.lookback_s)) return "Replay from must be whole seconds.";
    if (params.lookback_s < durationS) {
      return "Replay from must be at least the duration, so the copied span does not overlap.";
    }
  }
  return { params, duration: durationS };
}

export function ScenarioInjectPanel({ deviceId, accessToken, liveValues, channels }: Props) {
  const role = roleFromToken(accessToken);
  const allowed = canInject(role);
  const [scenarioId, setScenarioId] = useState<InjectionScenario>("constant_spoof");
  const [channel, setChannel] = useState<string>("current");
  const [duration, setDuration] = useState<string>("60");
  const [values, setValues] = useState<Record<string, string>>({});
  const [active, setActive] = useState<InjectionOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());

  const spec = useMemo(
    () => SCENARIOS.find((s) => s.id === scenarioId) ?? SCENARIOS[0],
    [scenarioId],
  );
  const unit = channels.find((c) => c.channel === channel)?.unit ?? "";

  const refresh = useCallback(async () => {
    if (!accessToken) return;
    try {
      setActive(await getActiveInjection(deviceId, accessToken));
    } catch {
      /* status is advisory; a failed poll keeps the last known state */
    }
  }, [accessToken, deviceId]);

  useEffect(() => {
    void refresh();
    const poll = window.setInterval(() => void refresh(), POLL_MS);
    const tick = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
    };
  }, [refresh]);

  const remainingS = active
    ? Math.max(0, Math.ceil((Date.parse(active.expires_at) - now) / 1000))
    : 0;
  const running = active !== null && remainingS > 0;

  const onSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!accessToken) return;
    const checked = validateInjection(spec, duration, values);
    if (typeof checked === "string") {
      setError(checked);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const sent = await injectScenario(
        deviceId,
        { scenario: spec.id, channel, duration_s: checked.duration, params: checked.params },
        accessToken,
      );
      setActive(sent);
      setNow(Date.now());
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const onCancel = async () => {
    if (!accessToken) return;
    setBusy(true);
    setError(null);
    try {
      await cancelScenario(deviceId, accessToken);
      setActive(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const liveValue = liveValues?.[channel];

  return (
    <GlassTile
      title="Scenario injection"
      aside={
        running ? (
          <span
            className={`inject__badge inject__badge--${active!.kind}`}
            data-testid="inject-badge"
          >
            {active!.kind === "attack" ? "Attack" : "Fault"} running · {remainingS}s
          </span>
        ) : null
      }
    >
      <div className="inject" data-testid="inject-panel">
        {running && active && (
          <div
            className={`inject__active inject__active--${active.kind}`}
            role="status"
            data-testid="inject-active"
          >
            <div>
              <strong>
                {SCENARIOS.find((s) => s.id === active.scenario)?.label ?? active.scenario}
              </strong>{" "}
              on <span className="mono">{active.channel}</span> · {remainingS}s left
              <div className="t-muted inject__meta">
                sent by {active.issued_by} · command {active.command_id.slice(0, 8)}
              </div>
            </div>
            {allowed && (
              <button
                type="button"
                className="toolbar__btn"
                onClick={onCancel}
                disabled={busy}
                data-testid="inject-cancel"
              >
                Stop
              </button>
            )}
          </div>
        )}

        {!allowed ? (
          <p className="t-muted" data-testid="inject-forbidden">
            Injecting a scenario needs the analyst or admin role. Your session is{" "}
            {role ?? "unknown"}.
          </p>
        ) : (
          <form className="inject__form" onSubmit={onSubmit} noValidate>
            <fieldset className="inject__scenarios" disabled={busy}>
              <legend className="t-label">Scenario</legend>
              {(["attack", "fault"] as const).map((kind) => (
                <div key={kind} className="inject__group">
                  <span className={`inject__kind inject__kind--${kind}`}>
                    {kind === "attack" ? "Attacks" : "Faults"}
                  </span>
                  {SCENARIOS.filter((s) => s.kind === kind).map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`toolbar__btn${scenarioId === s.id ? " is-active" : ""}`}
                      aria-pressed={scenarioId === s.id}
                      onClick={() => {
                        setScenarioId(s.id);
                        setError(null);
                      }}
                      data-testid={`scenario-${s.id}`}
                    >
                      {s.label}
                    </button>
                  ))}
                </div>
              ))}
              <p className="t-muted inject__description">{spec.description}</p>
            </fieldset>

            <div className="inject__fields">
              <label className="inject__field">
                <span className="t-label">Channel</span>
                <select
                  value={channel}
                  onChange={(e) => setChannel(e.target.value)}
                  disabled={busy}
                  data-testid="inject-channel"
                >
                  {CHANNELS.map((ch) => (
                    <option key={ch} value={ch}>
                      {ch}
                    </option>
                  ))}
                </select>
              </label>

              <label className="inject__field">
                <span className="t-label">Duration (s)</span>
                <input
                  type="number"
                  min={1}
                  max={MAX_INJECTION_DURATION_S}
                  step={1}
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  disabled={busy}
                  data-testid="inject-duration"
                />
              </label>

              {spec.params.map((p) => (
                <label key={p.name} className="inject__field">
                  <span className="t-label">
                    {p.label}
                    {p.seconds
                      ? " (s ago)"
                      : unit
                        ? ` (${unit}${p.perSecond ? "/s" : ""})`
                        : p.perSecond
                          ? " (/s)"
                          : ""}
                  </span>
                  <input
                    type="number"
                    step="any"
                    value={values[p.name] ?? ""}
                    onChange={(e) => setValues((v) => ({ ...v, [p.name]: e.target.value }))}
                    disabled={busy}
                    data-testid={`inject-param-${p.name}`}
                  />
                </label>
              ))}
            </div>

            {spec.id === "constant_spoof" && typeof liveValue === "number" && (
              <button
                type="button"
                className="link-btn"
                onClick={() => setValues((v) => ({ ...v, value: String(liveValue) }))}
                data-testid="inject-use-current"
              >
                Use current reading ({liveValue.toFixed(3)})
              </button>
            )}

            {error && (
              <p className="inject__error" role="alert" data-testid="inject-error">
                {error}
              </p>
            )}

            <div className="inject__actions">
              <button
                type="submit"
                className={`inject__submit inject__submit--${spec.kind}`}
                disabled={busy || !accessToken}
                data-testid="inject-submit"
              >
                {busy ? "Sending…" : running ? "Replace running scenario" : `Inject ${spec.kind}`}
              </button>
              <span className="t-muted inject__note">
                Audited and recorded in the ledger. Ends on its own after the duration.
              </span>
            </div>
          </form>
        )}
      </div>
    </GlassTile>
  );
}
