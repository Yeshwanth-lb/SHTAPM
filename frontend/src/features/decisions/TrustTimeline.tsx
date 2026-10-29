// Decisions over time (D060): all six trust scores on one chart, and a strip
// of what each decision concluded (normal / fault / attack / isolated).
// Input is the API's order, oldest first. Hand-rolled SVG like the other
// charts: plotted points are exactly the stored decisions.
import { useRef, useState, type PointerEvent } from "react";

import { CHANNELS, type Channel } from "../../types/contracts";
import { formatEventTime } from "../controlroom/model";
import type { DecisionOut } from "./useDecisions";

const COLORS: Record<Channel, string> = {
  temperature: "#f0a92b",
  vibration: "#4ea8de",
  pressure: "#8d97a3",
  humidity: "#4cc38a",
  gas: "#6b7480",
  current: "#b678f0",
};

const W = 1200;
const H = 240;
const PAD = { top: 10, right: 12, bottom: 20, left: 38 };

function trustOf(d: DecisionOut, ch: Channel): number | null {
  const v = d[`trust_${ch}` as keyof DecisionOut];
  return typeof v === "number" ? v : null;
}

export function verdictOf(d: DecisionOut): "attack" | "fault" | "isolated" | "normal" {
  if (d.attribution === "attack") return "attack";
  if (d.attribution === "fault") return "fault";
  if ((d.isolated_channels ?? []).length > 0) return "isolated";
  return "normal";
}

export function TrustTimeline({ rows }: { rows: DecisionOut[] }) {
  const [hidden, setHidden] = useState<Set<Channel>>(() => new Set());
  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const iw = W - PAD.left - PAD.right;
  const ih = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (rows.length <= 1 ? iw / 2 : (i / (rows.length - 1)) * iw);
  const y = (v: number) => PAD.top + ih - v * ih;

  const paths: Partial<Record<Channel, string>> = {};
  for (const ch of CHANNELS) {
    let d = "";
    rows.forEach((row, i) => {
      const v = trustOf(row, ch);
      if (v === null) return;
      d += `${d ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)} `;
    });
    paths[ch] = d;
  }

  if (rows.length === 0) {
    return <p className="t-muted">No decisions yet.</p>;
  }

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const sx = ((e.clientX - box.left) / box.width) * W;
    const i = Math.round(((sx - PAD.left) / iw) * (rows.length - 1));
    setHover(Math.max(0, Math.min(rows.length - 1, i)));
  };
  const toggle = (ch: Channel) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(ch)) next.delete(ch);
      else next.add(ch);
      return next;
    });
  const h = hover === null ? null : rows[hover];

  return (
    <div className="trust-timeline" data-testid="trust-timeline">
      <div className="trust-timeline__legend" role="group" aria-label="Show or hide channels">
        {CHANNELS.map((ch) => (
          <button
            key={ch}
            type="button"
            className={`legend-chip${hidden.has(ch) ? " is-off" : ""}`}
            onClick={() => toggle(ch)}
            aria-pressed={!hidden.has(ch)}
            data-testid={`legend-${ch}`}
          >
            <span className="legend-chip__swatch" style={{ background: COLORS[ch] }} />
            {ch}
            {h && (
              <span className="tabular legend-chip__value">
                {trustOf(h, ch)?.toFixed(2) ?? "—"}
              </span>
            )}
          </button>
        ))}
      </div>

      <svg
        ref={svgRef}
        className="trend__svg"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Trust of all channels over the last ${rows.length} decisions`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {[1, 0.7, 0.4, 0].map((v) => (
          <g key={v}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(v)}
              y2={y(v)}
              className={v === 0.7 || v === 0.4 ? "trend__ref" : "trend__grid"}
              stroke={
                v === 0.7
                  ? "var(--status-warning)"
                  : v === 0.4
                    ? "var(--status-critical)"
                    : undefined
              }
            />
            <text x={PAD.left - 6} y={y(v) + 3} className="trend__tick" textAnchor="end">
              {v.toFixed(1)}
            </text>
          </g>
        ))}
        {CHANNELS.filter((ch) => !hidden.has(ch)).map((ch) => (
          <path
            key={ch}
            d={paths[ch]}
            fill="none"
            stroke={COLORS[ch]}
            strokeWidth="1.6"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            className="trust-timeline__line"
          />
        ))}
        {hover !== null && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={PAD.top + ih}
            className="trend__crosshair"
          />
        )}
        <text x={PAD.left} y={H - 5} className="trend__tick">
          {formatEventTime(rows[0].ts)}
        </text>
        <text x={W - PAD.right} y={H - 5} className="trend__tick" textAnchor="end">
          {formatEventTime(rows[rows.length - 1].ts)}
        </text>
      </svg>

      <div
        className="verdict-strip"
        data-testid="verdict-strip"
        aria-label="What each decision concluded"
      >
        {rows.map((row, i) => (
          <span
            key={`${row.ts}-${i}`}
            className={`verdict-strip__cell verdict-strip__cell--${verdictOf(row)}${hover === i ? " is-hover" : ""}`}
            title={`${formatEventTime(row.ts)} · ${verdictOf(row)}${row.reason ? ` · ${row.reason}` : ""}`}
          />
        ))}
      </div>
      <div className="verdict-strip__key">
        <span>
          <i className="verdict-strip__cell--normal" /> normal
        </span>
        <span>
          <i className="verdict-strip__cell--fault" /> fault
        </span>
        <span>
          <i className="verdict-strip__cell--attack" /> attack
        </span>
        <span>
          <i className="verdict-strip__cell--isolated" /> isolated
        </span>
        {h && (
          <span className="verdict-strip__hover mono">
            {formatEventTime(h.ts)} · {verdictOf(h)}
            {h.reason ? ` · ${h.reason}` : ""}
          </span>
        )}
      </div>
    </div>
  );
}
