// Sensor detail panel (D052): opens from any Control Room instrument.
//
// Everything shown is already measured or recorded: the channel's live
// history (WebSocket + REST, a longer window than the tile), its trust per
// decision, the decisions that named it, its audit-ledger events and its
// documented provenance. Nothing is estimated for display.
import { useEffect, useMemo, useState } from "react";

import { TrendChart } from "../../components/charts/TrendChart";
import { useAnimatedNumber } from "../../lib/useAnimatedNumber";
import { apiGet } from "../../lib/api";
import { useApiResource } from "../../lib/useApiResource";
import type { ChannelOut } from "../channels/useChannels";
import { LIVE_DECISION_POLL_MS, useDecisions } from "../decisions/useDecisions";
import { useDeviceTelemetry } from "../telemetry/useDeviceTelemetry";
import {
  type ChannelState,
  type LedgerEvent,
  channelEvents,
  channelStats,
  channelVerdicts,
  formatEventTime,
  lastSeconds,
  trustSeries,
  trustTone,
} from "./model";

const RANGES = [
  { label: "1 min", seconds: 60 },
  { label: "5 min", seconds: 300 },
  { label: "20 min", seconds: 1200 },
] as const;
const HISTORY_POINTS = 1500; // ~20 min at the bench's ~1.2 s sample interval
const DECISIONS = 120;
const LEDGER_LINES = 200;

const SEVERITY_COLOR = {
  normal: "var(--status-info)",
  virtual: "var(--status-virtual)",
  caution: "var(--status-warning)",
  alarm: "var(--status-critical)",
} as const;

function fmt(v: number | null | undefined, digits = 3): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs < 0.5 * 10 ** -digits) return (0).toFixed(digits); // never "-0.000"
  return abs >= 100 ? v.toFixed(1) : abs >= 1 ? v.toFixed(2) : v.toFixed(digits);
}

export function SensorDetail({
  deviceId,
  accessToken,
  channel,
  unit,
  provenance,
  state,
  trust,
  onClose,
}: {
  deviceId: string;
  accessToken: string | null;
  channel: string;
  unit: string;
  provenance: ChannelOut | undefined;
  state: ChannelState;
  trust: number | null;
  onClose: () => void;
}) {
  const [range, setRange] = useState<number>(300);
  const { history, latest } = useDeviceTelemetry(deviceId, accessToken, {
    window: HISTORY_POINTS,
  });
  const decisions = useDecisions(deviceId, accessToken, DECISIONS, LIVE_DECISION_POLL_MS);
  const ledger = useApiResource<LedgerEvent[]>(
    () =>
      apiGet<LedgerEvent[]>(
        `/api/ledger/${encodeURIComponent(deviceId)}?limit=${LEDGER_LINES}`,
        accessToken!,
      ),
    [accessToken, deviceId],
    { enabled: accessToken !== null, pollMs: 3_000 },
  );

  // Escape closes; focus moves into the panel for keyboard users.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.getElementById("sensor-detail-close")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const series = history[channel as keyof typeof history] ?? [];
  const windowed = useMemo(() => lastSeconds(series, range), [series, range]);
  const stats = channelStats(windowed);
  const liveValue =
    latest !== null ? latest.sensors[channel as keyof typeof latest.sensors] ?? null : stats.now;
  const shown = useAnimatedNumber(liveValue);
  // Oldest first from the API; the helpers take newest first.
  const rows = [...(decisions.data ?? [])].reverse();
  const trustPts = trustSeries(rows, channel);
  const verdicts = channelVerdicts(rows, channel);
  const events = channelEvents(ledger.data ?? [], channel).slice(0, 12);
  const color = SEVERITY_COLOR[state.severity];
  const trustSev = trustTone(trust);

  return (
    <div className="drawer" data-testid="sensor-detail" role="presentation">
      <button
        type="button"
        className="drawer__scrim"
        aria-label="Close sensor details"
        onClick={onClose}
        tabIndex={-1}
      />
      <aside
        className="drawer__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="sensor-detail-title"
        data-severity={state.severity}
      >
        <header className="drawer__head">
          <div>
            <p className="t-label">Sensor</p>
            <h2 id="sensor-detail-title" className="drawer__title">
              {channel}
            </h2>
            <p className="drawer__sub t-muted">
              {provenance?.part ?? "Unknown part"}
              {provenance?.interface ? ` · ${provenance.interface}` : ""}
            </p>
          </div>
          <div className="drawer__now">
            <span className="drawer__value tabular" data-testid="sensor-detail-value">
              {fmt(liveValue === null ? null : shown)}
            </span>
            <span className="drawer__unit">{unit}</span>
          </div>
          <button
            id="sensor-detail-close"
            type="button"
            className="drawer__close"
            onClick={onClose}
            data-testid="sensor-detail-close"
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <div className="drawer__tags">
          <span className={`tag tag--${provenance?.source === "live" ? "info" : "muted"}`}>
            {provenance?.source === "live"
              ? "LIVE SENSOR"
              : provenance?.source === "placeholder"
                ? "PLACEHOLDER"
                : "SOURCE UNKNOWN"}
          </span>
          {state.tags.map((t) => (
            <span
              key={t.label}
              className={`tag tag--${t.severity === "normal" ? "muted" : t.severity}`}
            >
              {t.label}
            </span>
          ))}
          {state.tags.length === 0 && <span className="tag tag--muted">NORMAL</span>}
        </div>

        <section className="drawer__section">
          <div className="drawer__section-head">
            <h3 className="t-label">Live trend</h3>
            <div className="segmented" role="tablist" aria-label="Time range">
              {RANGES.map((r) => (
                <button
                  key={r.seconds}
                  type="button"
                  role="tab"
                  aria-selected={range === r.seconds}
                  className={`segmented__btn${range === r.seconds ? " is-active" : ""}`}
                  onClick={() => setRange(r.seconds)}
                  data-testid={`sensor-range-${r.seconds}`}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
          <TrendChart
            points={windowed}
            color={color}
            unit={unit}
            format={(v) => fmt(v)}
            label={`${channel} over the last ${range / 60} minutes`}
            testId="sensor-trend"
          />
        </section>

        <section className="stats" data-testid="sensor-stats">
          {(
            [
              ["Now", stats.now],
              ["Min", stats.min],
              ["Max", stats.max],
              ["Mean", stats.mean],
              ["Std dev", stats.std],
            ] as const
          ).map(([name, v]) => (
            <div key={name} className="stats__item">
              <span className="t-label">{name}</span>
              <strong className="tabular">{fmt(v)}</strong>
            </div>
          ))}
          <div className="stats__item">
            <span className="t-label">Samples</span>
            <strong className="tabular">{stats.n}</strong>
          </div>
        </section>

        <section className="drawer__section">
          <div className="drawer__section-head">
            <h3 className="t-label">Trust score</h3>
            <span className={`drawer__trust drawer__trust--${trustSev} tabular`}>
              {trust === null ? "—" : trust.toFixed(2)}
            </span>
          </div>
          <TrendChart
            points={trustPts}
            color={trustSev === "normal" ? "var(--status-healthy)" : SEVERITY_COLOR[trustSev]}
            domain={[0, 1]}
            height={140}
            format={(v) => v.toFixed(2)}
            references={[
              { value: 0.7, label: "trusted ≥ 0.70", tone: "caution" },
              { value: 0.4, label: "malicious < 0.40", tone: "alarm" },
            ]}
            label={`${channel} trust over the last ${trustPts.length} decisions`}
            testId="sensor-trust"
          />
        </section>

        <section className="verdicts" data-testid="sensor-verdicts">
          <div className="verdicts__item verdicts__item--alarm">
            <strong className="tabular">{verdicts.attack}</strong>
            <span>attack verdicts</span>
          </div>
          <div className="verdicts__item verdicts__item--caution">
            <strong className="tabular">{verdicts.fault}</strong>
            <span>fault verdicts</span>
          </div>
          <div className="verdicts__item">
            <strong className="tabular">{verdicts.total}</strong>
            <span>recent decisions</span>
          </div>
        </section>

        <section className="drawer__section">
          <h3 className="t-label">Events for this sensor (audit ledger)</h3>
          {events.length === 0 ? (
            <p className="t-muted drawer__empty" data-testid="sensor-events-empty">
              No isolation, recovery or failure recorded for {channel}.
            </p>
          ) : (
            <ol className="eventlog" data-testid="sensor-events">
              {events.map((line) => (
                <li key={line.key} className="eventlog__row">
                  <span className="mono t-muted">{formatEventTime(line.ts)}</span>
                  <span
                    className={`eventlog__mark${line.severity === "normal" ? "" : ` eventlog__mark--${line.severity}`}`}
                    aria-hidden="true"
                  />
                  <span>{line.text}</span>
                </li>
              ))}
            </ol>
          )}
        </section>

        {provenance?.note && (
          <section className="drawer__section">
            <h3 className="t-label">What this sensor measures</h3>
            <p className="drawer__note">{provenance.note}</p>
          </section>
        )}
      </aside>
    </div>
  );
}
