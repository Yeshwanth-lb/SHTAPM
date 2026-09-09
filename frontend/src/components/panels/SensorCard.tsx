// One channel: current value, unit, provenance, freshness, recent history.
//
// The unavailable state is a first-class case, not an afterthought. Until a
// frame arrives there is no value, and the card says so rather than rendering
// a zero — a fabricated "0.0" is indistinguishable from a real reading of zero
// (which `current` legitimately is right now).
import { Sparkline, type SparklinePoint } from "../charts/Sparkline";
import { ChannelProvenanceBadge } from "./ChannelProvenanceBadge";
import type { ChannelSource } from "../../features/channels/useChannels";
import "./sensor-card.css";

export interface SensorCardProps {
  channel: string;
  /** null when no reading has been received yet. */
  value: number | null;
  unit: string | null;
  source: ChannelSource;
  part: string | null;
  /** ISO timestamp of the newest reading, or null. */
  updatedAt: string | null;
  history: SparklinePoint[];
}

/** Significant-figure formatting that never invents precision. */
export function formatValue(value: number | null): string {
  if (value === null || Number.isNaN(value)) return "—";
  if (Number.isInteger(value)) return String(value);
  const abs = Math.abs(value);
  const decimals = abs >= 100 ? 1 : abs >= 1 ? 2 : 3;
  return value.toFixed(decimals);
}

/** "12s ago" / "3m ago". Returns null when there is no timestamp. */
export function formatAge(iso: string | null, now: number = Date.now()): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, Math.round((now - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.floor(minutes / 60)}h ago`;
}

export function SensorCard({
  channel,
  value,
  unit,
  source,
  part,
  updatedAt,
  history,
}: SensorCardProps) {
  const unavailable = value === null;
  const age = formatAge(updatedAt);

  return (
    <article
      className={`sensor-card glass${unavailable ? " sensor-card--unavailable" : ""}`}
      data-testid={`sensor-card-${channel}`}
    >
      <header className="sensor-card__head">
        <h3 className="t-label">{channel}</h3>
        <ChannelProvenanceBadge source={source} />
      </header>

      <p className="sensor-card__value tabular">
        <span className="t-metric" data-testid={`sensor-value-${channel}`}>
          {formatValue(value)}
        </span>
        {unit && !unavailable && <span className="sensor-card__unit"> {unit}</span>}
      </p>

      {unavailable ? (
        <p className="sensor-card__meta t-muted" data-testid={`sensor-unavailable-${channel}`}>
          No reading received yet
        </p>
      ) : (
        <p className="sensor-card__meta t-muted mono">
          {part ?? "part not registered"}
          {age ? ` · ${age}` : ""}
        </p>
      )}

      <Sparkline points={history} label={`${channel} recent history`} />
    </article>
  );
}
