// Control-room instruments (D046): master caution, instrument tile,
// annunciator and event log. Presentation only -- state comes from model.ts.
import { Sparkline } from "../../components/charts/Sparkline";
import { useAnimatedNumber } from "../../lib/useAnimatedNumber";
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
        <CautionGlyph severity={state.severity} />
        <span>{state.lamp}</span>
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

/** Shape carries the state too, never colour alone (Doc04 accessibility). */
function CautionGlyph({ severity }: { severity: Severity }) {
  const common = { width: 14, height: 14, viewBox: "0 0 16 16", "aria-hidden": true } as const;
  if (severity === "alarm")
    return (
      <svg {...common} className="caution__glyph">
        <path d="M8 1.5 15 14H1z" fill="currentColor" />
        <path d="M8 6v3.6M8 11.4v.6" stroke="var(--caution-glyph-ink)" strokeWidth="1.6" />
      </svg>
    );
  if (severity === "caution" || severity === "virtual")
    return (
      <svg {...common} className="caution__glyph">
        <rect
          x="2"
          y="2"
          width="12"
          height="12"
          rx="2"
          transform="rotate(45 8 8)"
          fill="currentColor"
        />
        <path d="M8 5v3.6M8 10.4v.6" stroke="var(--caution-glyph-ink)" strokeWidth="1.6" />
      </svg>
    );
  return (
    <svg {...common} className="caution__glyph">
      <circle cx="8" cy="8" r="5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="m5.6 8.2 1.6 1.6 3.2-3.4" fill="none" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

function formatValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const abs = Math.abs(value);
  if (abs < 0.0005) return (0).toFixed(3); // never show "-0.000"
  return abs >= 100 ? value.toFixed(1) : abs >= 1 ? value.toFixed(2) : value.toFixed(3);
}

export function Instrument({
  channel,
  value,
  unit,
  points,
  trust,
  state,
  onOpen,
  twinValue = null,
}: {
  channel: string;
  value: number | null;
  unit: string;
  points: ChannelPoint[];
  trust: number | null;
  state: ChannelState;
  /** Opens the sensor detail panel; makes the tile a button (D052). */
  onOpen?: () => void;
  /** The digital twin's value while this channel is substituted (D054). */
  twinValue?: number | null;
}) {
  const tone = TONE_CLASS[state.severity];
  const trustSeverity = trustTone(trust);
  const healing = twinValue !== null && twinValue !== undefined;
  const shownValue = useAnimatedNumber(healing ? twinValue : value, undefined, { countUp: true });
  const shownTrust = useAnimatedNumber(trust, undefined, { countUp: true });
  return (
    <article
      className={`instrument${tone ? ` instrument--${tone}` : ""}${onOpen ? " instrument--clickable" : ""}`}
      data-testid={`instrument-${channel}`}
      data-severity={state.severity}
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      aria-label={onOpen ? `${channel}: open details` : undefined}
      onClick={onOpen}
      onKeyDown={
        onOpen
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onOpen();
              }
            }
          : undefined
      }
    >
      <header className="instrument__head">
        <span className="t-label">{channel}</span>
        {onOpen ? (
          <span className="instrument__open">Details →</span>
        ) : (
          <span className="t-muted mono" style={{ fontSize: 12 }}>
            {points.length > 0 ? `${points.length} pts` : ""}
          </span>
        )}
      </header>
      <div className={`instrument__value tabular${healing ? " instrument__value--twin" : ""}`}>
        <span className="t-metric" data-testid={`instrument-value-${channel}`}>
          {formatValue(value === null && !healing ? null : shownValue)}
        </span>
        <span className="instrument__unit">{unit}</span>
        {healing && <span className="instrument__twin">twin</span>}
      </div>
      {healing && (
        <div className="instrument__sensor-reads" data-testid={`instrument-sensor-${channel}`}>
          sensor reports {formatValue(value)} {unit} · not trusted
        </div>
      )}
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
        <span className="tabular">
          {trust === null || shownTrust === null ? "—" : shownTrust.toFixed(2)}
        </span>
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
