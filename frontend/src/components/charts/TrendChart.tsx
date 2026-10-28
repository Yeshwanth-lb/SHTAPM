// Large interactive trend chart for the sensor detail panel (D052).
//
// Hand-rolled SVG like Sparkline (no chart dependency, CLAUDE.md). Draws the
// points it is given -- no smoothing, no interpolation -- with a min/max
// axis, optional reference lines (e.g. trust bands 0.7 / 0.4) and a hover
// crosshair that reads out the nearest REAL sample.
import { useId, useMemo, useRef, useState, type PointerEvent } from "react";

import type { SparklinePoint } from "./Sparkline";

export interface ReferenceLine {
  value: number;
  label: string;
  tone: "caution" | "alarm" | "muted";
}

export interface TrendChartProps {
  points: SparklinePoint[];
  color?: string;
  height?: number;
  unit?: string;
  /** Fixed y-range (e.g. trust 0..1); default fits the data. */
  domain?: [number, number];
  references?: ReferenceLine[];
  format?: (v: number) => string;
  label: string;
  testId?: string;
}

const W = 640;
const PAD = { top: 10, right: 12, bottom: 22, left: 52 };

const TONE: Record<ReferenceLine["tone"], string> = {
  caution: "var(--status-warning)",
  alarm: "var(--status-critical)",
  muted: "var(--text-muted)",
};

function timeLabel(ts: string): string {
  const d = new Date(ts.endsWith("Z") || /[+-]\d\d:\d\d$/.test(ts) ? ts : `${ts}Z`);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function TrendChart({
  points,
  color = "var(--status-info)",
  height = 200,
  unit = "",
  domain,
  references = [],
  format = (v) => v.toFixed(3),
  label,
  testId = "trend-chart",
}: TrendChartProps) {
  const gid = `trend-${useId().replace(/:/g, "")}`;
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const geometry = useMemo(() => {
    if (points.length === 0) return null;
    const values = points.map((p) => p.value);
    let [lo, hi] = domain ?? [Math.min(...values), Math.max(...values)];
    if (!domain) {
      const span = hi - lo || Math.abs(hi) * 0.05 || 1;
      lo -= span * 0.08;
      hi += span * 0.08;
    }
    const iw = W - PAD.left - PAD.right;
    const ih = height - PAD.top - PAD.bottom;
    const x = (i: number) =>
      PAD.left + (points.length === 1 ? iw / 2 : (i / (points.length - 1)) * iw);
    const y = (v: number) => PAD.top + ih - ((v - lo) / (hi - lo)) * ih;
    const line = points
      .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
      .join(" ");
    const area = `${line} L${x(points.length - 1).toFixed(1)},${PAD.top + ih} L${x(0).toFixed(1)},${PAD.top + ih} Z`;
    const ticks = [hi, (hi + lo) / 2, lo];
    return { lo, hi, x, y, line, area, ticks, ih };
  }, [points, domain, height]);

  if (!geometry) {
    return (
      <div className="trend trend--empty t-muted" data-testid={`${testId}-empty`}>
        No samples in this window yet.
      </div>
    );
  }

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = svgRef.current?.getBoundingClientRect();
    if (!box || box.width === 0) return;
    const sx = ((e.clientX - box.left) / box.width) * W;
    const iw = W - PAD.left - PAD.right;
    const i = Math.round(((sx - PAD.left) / iw) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  };

  const h = hover === null ? null : points[hover];

  return (
    <div className="trend" data-testid={testId}>
      <svg
        ref={svgRef}
        className="trend__svg"
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={label}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
        data-points={points.length}
      >
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.3" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        {geometry.ticks.map((t, i) => (
          <g key={i}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={geometry.y(t)}
              y2={geometry.y(t)}
              className="trend__grid"
            />
            <text x={PAD.left - 8} y={geometry.y(t) + 3} className="trend__tick" textAnchor="end">
              {format(t)}
            </text>
          </g>
        ))}
        {references
          .filter((r) => r.value >= geometry.lo && r.value <= geometry.hi)
          .map((r) => (
            <g key={r.label}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={geometry.y(r.value)}
                y2={geometry.y(r.value)}
                stroke={TONE[r.tone]}
                className="trend__ref"
              />
              <text
                x={W - PAD.right - 4}
                y={geometry.y(r.value) - 4}
                className="trend__ref-label"
                fill={TONE[r.tone]}
                textAnchor="end"
              >
                {r.label}
              </text>
            </g>
          ))}
        <path className="trend__area" d={geometry.area} fill={`url(#${gid})`} />
        <path
          className="trend__line"
          d={geometry.line}
          fill="none"
          stroke={color}
          strokeWidth="1.6"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
          pathLength={1}
        />
        <text x={PAD.left} y={height - 6} className="trend__tick">
          {timeLabel(points[0].ts)}
        </text>
        <text x={W - PAD.right} y={height - 6} className="trend__tick" textAnchor="end">
          {timeLabel(points[points.length - 1].ts)}
        </text>
        {h && hover !== null && (
          <g className="trend__hover">
            <line
              x1={geometry.x(hover)}
              x2={geometry.x(hover)}
              y1={PAD.top}
              y2={PAD.top + geometry.ih}
              className="trend__crosshair"
            />
            <circle cx={geometry.x(hover)} cy={geometry.y(h.value)} r="4" fill={color} />
          </g>
        )}
      </svg>
      <div className="trend__readout mono tabular" aria-live="off">
        {h ? (
          <>
            <span>{timeLabel(h.ts)}</span>
            <strong>
              {format(h.value)} {unit}
            </strong>
          </>
        ) : (
          <span className="t-muted">Hover the chart to read any sample</span>
        )}
      </div>
    </div>
  );
}
