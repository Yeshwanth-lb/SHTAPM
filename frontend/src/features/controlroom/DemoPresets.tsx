// One-click rehearsed scenarios (D056): the three bench-proven scenarios of
// DEMO_CARD.md with their values built in, so nothing is typed on stage.
//
// Each needs a motor state (a spoof to 0 A only contradicts a RUNNING motor;
// a +0.8 A bias only contradicts an IDLE one). The edge's own motor-state
// reading (D054) gates the buttons, so the wrong combination cannot be sent.
import { useEffect, useState } from "react";

import {
  cancelScenario,
  describeRequestFailure,
  getActiveInjection,
  injectScenario,
  type InjectionOut,
  type InjectRequest,
  type LiveStateOut,
} from "../../lib/api";
import { useApiResource } from "../../lib/useApiResource";

interface Preset {
  id: string;
  title: string;
  expect: string;
  tone: "alarm" | "caution";
  needs: "running" | "idle";
  request: InjectRequest;
}

export const PRESETS: Preset[] = [
  {
    id: "spoof",
    title: "Spoof attack",
    expect: "Current forced to 0 A while the motor runs → ATTACK",
    tone: "alarm",
    needs: "running",
    request: {
      scenario: "constant_spoof",
      channel: "current",
      duration_s: 40,
      params: { value: 0 },
    },
  },
  {
    id: "bias",
    title: "Bias attack",
    expect: "+0.8 A added while the motor is off → ATTACK",
    tone: "alarm",
    needs: "idle",
    request: { scenario: "bias_fdi", channel: "current", duration_s: 40, params: { bias: 0.8 } },
  },
  {
    id: "stuck",
    title: "Stuck sensor",
    expect: "Current frozen while the motor runs → FAULT",
    tone: "caution",
    needs: "running",
    request: { scenario: "stuck_at", channel: "current", duration_s: 40, params: {} },
  },
];

const NEEDS_TEXT = { running: "Switch the motor ON first", idle: "Switch the motor OFF first" };

export function DemoPresets({
  deviceId,
  accessToken,
  live,
}: {
  deviceId: string;
  accessToken: string;
  live: LiveStateOut | null;
}) {
  const active = useApiResource<InjectionOut | null>(
    () => getActiveInjection(deviceId, accessToken),
    [accessToken, deviceId],
    { pollMs: 2_000 },
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  const motor = live?.motor_state?.current?.state ?? null;
  const running = active.data?.active ? active.data : null;
  const left = running ? Math.max(0, Math.round((Date.parse(running.expires_at) - now) / 1000)) : 0;

  async function fire(preset: Preset) {
    setBusy(preset.id);
    setError(null);
    try {
      await injectScenario(deviceId, preset.request, accessToken);
      active.refresh();
    } catch (err) {
      setError(`Not sent: ${describeRequestFailure(err)}`);
    } finally {
      setBusy(null);
    }
  }

  async function stop() {
    try {
      await cancelScenario(deviceId, accessToken);
      active.refresh();
    } catch (err) {
      setError(`Could not stop: ${describeRequestFailure(err)}`);
    }
  }

  return (
    <section className="presets" data-testid="demo-presets">
      <header className="presets__head">
        <span className="t-label">Demo scenarios</span>
        <span className="presets__motor t-muted">
          motor:{" "}
          <strong className={`presets__motor-state presets__motor-state--${motor ?? "unknown"}`}>
            {motor ? motor.toUpperCase() : "—"}
          </strong>
        </span>
      </header>

      {running ? (
        <div className="presets__running" data-testid="preset-running">
          <span>
            <strong>{running.scenario.replace(/_/g, " ")}</strong> on {running.channel} ·{" "}
            <span className="tabular">{left}s</span> left
          </span>
          <button type="button" className="toolbar__btn" onClick={() => void stop()}>
            Stop
          </button>
          <span
            className="presets__progress"
            style={{ width: `${(left / running.duration_s) * 100}%` }}
          />
        </div>
      ) : (
        <div className="presets__grid">
          {PRESETS.map((p) => {
            const ready = motor === p.needs;
            return (
              <button
                key={p.id}
                type="button"
                className={`preset preset--${p.tone}`}
                disabled={!ready || busy !== null}
                onClick={() => void fire(p)}
                data-testid={`preset-${p.id}`}
                title={ready ? p.expect : NEEDS_TEXT[p.needs]}
              >
                <strong>{busy === p.id ? "Sending…" : p.title}</strong>
                <span>{ready ? p.expect : NEEDS_TEXT[p.needs]}</span>
              </button>
            );
          })}
        </div>
      )}
      {error && (
        <p className="presets__error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
