// "Two witnesses" coupling trace (D061): the signature of the Control Room.
//
// Current and vibration are the bench's physically coupled pair. Each reading
// is placed on a shared motor-state scale using the edge's OWN bands for that
// channel (D054): 0 = the top of its idle band, 1 = the bottom of its running
// band. A healthy pump draws the two lines together; an attack that pins one
// sensor to the other state tears them apart, and the span where one says
// IDLE while the other says RUNNING is filled red. Every point is a real
// reading; the only computation is that placement, and a contradiction is
// shaded only once it has held for three consecutive samples (one-sample
// ripples on the current trace are not evidence).
import type { ChannelMotorState } from "../../lib/api";
import type { ChannelPoint } from "../telemetry/useDeviceTelemetry";

const W = 1000;
const H = 150;
const PAD = { top: 14, bottom: 14, left: 0, right: 0 };
const LO = -0.35; // scale floor (below the idle band)
const HI = 1.45; // scale ceiling (above the running band)
const PERSIST = 3;

export function toScale(value: number, bands: ChannelMotorState): number {
  const span = bands.running_min - bands.idle_max;
  if (span <= 0) return 0;
  const s = (value - bands.idle_max) / span;
  return Math.max(LO, Math.min(HI, s));
}

type Side = "idle" | "running" | "between";
const side = (s: number): Side => (s <= 0 ? "idle" : s >= 1 ? "running" : "between");

/** Index ranges where the two witnesses contradict each other for at least
 *  PERSIST consecutive samples. Exported for testing. */
export function conflictSpans(a: number[], b: number[]): [number, number][] {
  const n = Math.min(a.length, b.length);
  const spans: [number, number][] = [];
  let start = -1;
  for (let i = 0; i <= n; i += 1) {
    const sa = i < n ? side(a[i]) : "between";
    const sb = i < n ? side(b[i]) : "between";
    const conflict = (sa === "idle" && sb === "running") || (sa === "running" && sb === "idle");
    if (conflict && start < 0) start = i;
    if (!conflict && start >= 0) {
      if (i - start >= PERSIST) spans.push([start, i - 1]);
      start = -1;
    }
  }
  return spans;
}

export function CouplingTrace({
  current,
  vibration,
  currentBands,
  vibrationBands,
}: {
  current: ChannelPoint[];
  vibration: ChannelPoint[];
  currentBands?: ChannelMotorState;
  vibrationBands?: ChannelMotorState;
}) {
  if (!currentBands || !vibrationBands || current.length < 2 || vibration.length < 2) {
    return (
      <div className="coupling coupling--empty" data-testid="coupling-trace">
        Waiting for both witnesses: the edge reports its motor-state bands with each decision.
      </div>
    );
  }
  const n = Math.min(current.length, vibration.length);
  const c = current.slice(-n).map((p) => toScale(p.value, currentBands));
  const v = vibration.slice(-n).map((p) => toScale(p.value, vibrationBands));
  const ih = H - PAD.top - PAD.bottom;
  const x = (i: number) => (n === 1 ? W / 2 : (i / (n - 1)) * W);
  const y = (s: number) => PAD.top + ih - ((s - LO) / (HI - LO)) * ih;
  const line = (arr: number[]) =>
    arr.map((s, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(s).toFixed(1)}`).join(" ");
  const spans = conflictSpans(c, v);

  return (
    <div className="coupling" data-testid="coupling-trace" data-conflicts={spans.length}>
      <div className="coupling__lanes" aria-hidden="true">
        <span style={{ top: `${(y(1) / H) * 100}%` }}>RUNNING</span>
        <span style={{ top: `${(y(0) / H) * 100}%` }}>IDLE</span>
      </div>
      <svg
        className="coupling__svg"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Current and vibration on one motor-state scale over the last ${n} samples${
          spans.length ? `; ${spans.length} contradiction span(s)` : ""
        }`}
      >
        <rect
          className="coupling__band coupling__band--run"
          x="0"
          y={PAD.top}
          width={W}
          height={y(1) - PAD.top}
        />
        <rect
          className="coupling__band coupling__band--idle"
          x="0"
          y={y(0)}
          width={W}
          height={H - PAD.bottom - y(0)}
        />
        <line className="coupling__rule" x1="0" x2={W} y1={y(1)} y2={y(1)} />
        <line className="coupling__rule" x1="0" x2={W} y1={y(0)} y2={y(0)} />
        {spans.map(([a, b]) => (
          <rect
            key={`${a}-${b}`}
            className="coupling__conflict"
            x={x(a)}
            y={PAD.top}
            width={Math.max(4, x(b) - x(a))}
            height={ih}
          />
        ))}
        <path className="coupling__line coupling__line--vibration" d={line(v)} />
        <path className="coupling__line coupling__line--current" d={line(c)} />
        <circle
          className="coupling__head coupling__head--vibration"
          cx={x(n - 1)}
          cy={y(v[n - 1])}
          r="5"
        />
        <circle
          className="coupling__head coupling__head--current"
          cx={x(n - 1)}
          cy={y(c[n - 1])}
          r="5"
        />
      </svg>
    </div>
  );
}
