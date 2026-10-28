// Compact history line (Doc04 §04.5: "a luminous thread floating in glass").
//
// Hand-rolled SVG rather than a charting library: this draws one series of at
// most ~120 points, and adding a dependency is gated by CLAUDE.md. uPlot
// remains the right call for the dense multi-series cockpit charts later.
//
// Renders only what it is given. A flat line means the values really are flat
// (a placeholder constant looks exactly like that, deliberately); no point is
// interpolated or smoothed.
import { useId } from "react";

export interface SparklinePoint {
  ts: string;
  value: number;
}

export interface SparklineProps {
  points: SparklinePoint[];
  /** Stroke colour; defaults to the aurora teal token. */
  color?: string;
  width?: number;
  height?: number;
  label?: string;
}

/** Map values to an SVG path. Exported for testing. */
export function buildPath(points: SparklinePoint[], width: number, height: number): string {
  if (points.length === 0) return "";
  const pad = 2;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const usableH = height - pad * 2;

  // A constant series has zero span — centre it instead of dividing by zero.
  const y = (v: number) => (span === 0 ? height / 2 : pad + usableH - ((v - min) / span) * usableH);
  const x = (i: number) =>
    points.length === 1 ? width / 2 : (i / (points.length - 1)) * (width - pad * 2) + pad;

  return points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(2)},${y(p.value).toFixed(2)}`)
    .join(" ");
}

export function Sparkline({
  points,
  color = "var(--aurora-teal)",
  width = 260,
  height = 44,
  label,
}: SparklineProps) {
  const gradientId = `spark-fill-${useId().replace(/:/g, "")}`;
  if (points.length === 0) {
    return (
      <div className="spark spark--empty t-muted" data-testid="sparkline-empty">
        no history yet
      </div>
    );
  }

  const path = buildPath(points, width, height);
  const last = points[points.length - 1];
  const cursorY = Number(path.split(/[ ,]/).slice(-1)[0]);
  // Area under the line (D052): the same points, closed to the baseline --
  // depth for the eye, no extra data.
  const firstX = path.slice(1).split(",")[0];
  const area = `${path} L${width - 2},${height} L${firstX},${height} Z`;

  return (
    <svg
      className="spark"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label ?? `${points.length} recent samples`}
      data-testid="sparkline"
      data-points={points.length}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.14" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path className="spark__area" d={area} fill={`url(#${gradientId})`} stroke="none" />
      <path
        className="spark__line"
        d={path}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {/* Newest point, breathing (Doc04 §04.5): the live edge of the data. */}
      <circle
        className="spark__pulse"
        cx={width - 2}
        cy={cursorY}
        r="5"
        fill={color}
        aria-hidden="true"
      />
      <circle cx={width - 2} cy={cursorY} r="2.5" fill={color} data-testid="sparkline-cursor">
        <title>{`${last.value} at ${last.ts}`}</title>
      </circle>
    </svg>
  );
}
