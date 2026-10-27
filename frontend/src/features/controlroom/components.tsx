// Control-room instruments (D046): master caution, instrument tile,
// annunciator and event log. Presentation only -- state comes from model.ts.
import { Sparkline } from "../../components/charts/Sparkline";
import type { ChannelPoint } from "../telemetry/useDeviceTelemetry";
import {
  type AnnunciatorWindow,
  type CautionState,
  type ChannelState,
  type LogLine,
  type Severity,
  formatEventTime,
  trustTone,
} from "./model";

const TONE_CLASS: Record<Severity, string> = {
  normal: "",
  virtual: "virtual",
  caution: "caution",
  alarm: "alarm",
};

const SPARK_COLOR: Record<Severity, string> = {
  normal: "var(--text-primary)",
  virtual: "var(--status-virtual)",
  caution: "var(--status-warning)",
  alarm: "var(--status-critical)",
};

export function MasterCaution({
  state,
  acknowledged,
  onAcknowledge,
}: {
  state: CautionState;
  acknowledged: boolean;
  onAcknowledge: () => void;
}) {
  const tone = TONE_CLASS[state.severity];
  const abnormal = state.severity !== "normal";
  return (
    <section
      className={
        `caution${tone ? ` caution--${tone === "virtual" ? "caution" : tone}` : ""}` +
        (abnormal && !acknowledged ? " caution--unacked" : "")
      }
      role={state.severity === "alarm" ? "alert" : "status"}
      data-testid="master-caution"
      data-severity={state.severity}
    >
      <div className="caution__lamp" data-testid="caution-lamp">
        {state.lamp}
      </div>
      <div className="caution__text">
        <strong data-testid="caution-title">{state.title}</strong>
        {state.detail && <span data-testid="caution-detail">{state.detail}</span>}
      </div>
      {abnormal && (
        <button
          type="button"
          className="toolbar__btn"
          onClick={onAcknowledge}
          disabled={acknowledged}
          data-testid="caution-ack"
        >
          {acknowledged ? "Acknowledged" : "Acknowledge"}
        </button>
      )}
    </section>
  );
}

function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  return abs >= 100 ? value.toFixed(1) : abs >= 1 ? value.toFixed(2) : value.toFixed(3);
}

export function Instrument({
  channel,
  value,
  unit,
  points,
  trust,
  state,
}: {
  channel: string;
  value: number | null;
  unit: string;
  points: ChannelPoint[];
  trust: number | null;
  state: ChannelState;
}) {
  const tone = TONE_CLASS[state.severity];
  const trustSeverity = trustTone(trust);
  return (
    <article
      className={`instrument${tone ? ` instrument--${tone}` : ""}`}
      data-testid={`instrument-${channel}`}
      data-severity={state.severity}
    >
      <header className="instrument__head">
        <span className="t-label">{channel}</span>
        <span className="t-muted mono" style={{ fontSize: 11 }}>
          {points.length > 0 ? `${points.length} pts` : ""}
        </span>
      </header>
      <div className="instrument__value tabular">
        <span className="t-metric" data-testid={`instrument-value-${channel}`}>
          {formatValue(value)}
        </span>
        <span className="instrument__unit">{unit}</span>
      </div>
      <Sparkline
        points={points.slice(-90)}
        color={SPARK_COLOR[state.severity]}
        height={36}
        label={`${channel} recent trend`}
      />
      <div className="trustbar" data-testid={`instrument-trust-${channel}`}>
        <span>TRUST</span>
        <span className="trustbar__track">
          <span
            className={`trustbar__fill${
              trustSeverity === "normal" ? "" : ` trustbar__fill--${trustSeverity}`
            }`}
            style={{ width: `${Math.round((trust ?? 0) * 100)}%` }}
          />
        </span>
        <span className="tabular">{trust === null ? "—" : trust.toFixed(2)}</span>
      </div>
      <div className="instrument__tags">
        {state.tags.map((tag) => (
          <span
            key={tag.label}
            className={`tag tag--${tag.severity === "normal" ? "muted" : tag.severity}`}
            data-testid={`instrument-tag-${channel}`}
          >
            {tag.label}
          </span>
        ))}
      </div>
    </article>
  );
}

export function Annunciator({ windows }: { windows: AnnunciatorWindow[] }) {
  return (
    <div className="annunciator" role="list" data-testid="annunciator">
      {windows.map((w) => {
        const tone = TONE_CLASS[w.severity];
        return (
          <div
            key={w.channel}
            role="listitem"
            className={`annunciator__window${tone ? ` annunciator__window--${tone}` : ""}`}
            data-testid={`annunciator-${w.channel}`}
            data-severity={w.severity}
          >
            {w.label}
          </div>
        );
      })}
    </div>
  );
}

export function EventLog({ lines }: { lines: LogLine[] }) {
  if (lines.length === 0) {
    return (
      <p className="t-muted" data-testid="eventlog-empty">
        No events recorded yet. Isolations, recoveries, sensor failures, pump starts/stops and safe
        stops appear here as they are written to the audit ledger.
      </p>
    );
  }
  return (
    <ol className="eventlog" data-testid="eventlog">
      {lines.map((line) => (
        <li key={line.key} className="eventlog__row" data-testid="eventlog-row">
          <span className="mono t-muted">{formatEventTime(line.ts)}</span>
          <span
            className={`eventlog__mark${line.severity === "normal" ? "" : ` eventlog__mark--${line.severity}`}`}
            aria-hidden="true"
          />
          <span>{line.text}</span>
        </li>
      ))}
    </ol>
  );
}
