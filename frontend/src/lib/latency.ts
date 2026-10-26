// Sensor -> browser latency, measured where the frame is actually received.
//
// The backend's `e2e_latency_ms` covers edge publish -> backend receipt only
// (backend/app/services/latency_tracker.py). This measures the whole path the
// PRD NFR-P1/AC6 target is about: the Pi's sampling timestamp (`ts`, already in
// every telemetry frame) against the browser's clock at receipt. No wire field is
// added; the frozen contract is untouched.
//
// Frames carry no backend timestamp, so the backend -> browser leg cannot be
// isolated on its own without a contract change. It is included in this figure.
//
// CLOCK SKEW: this compares two machines' clocks (the Pi and the viewing laptop).
// Both must run NTP for the figure to mean anything. A negative delta is
// impossible unless the clocks disagree; an implausibly large one means skew or
// buffered frames replayed after an outage. Both are counted and excluded, never
// clamped, and any negative sample withholds the percentiles entirely -- the same
// rule the backend tracker uses.

export const DEFAULT_LATENCY_WINDOW = 120;
export const IMPLAUSIBLE_LATENCY_MS = 60_000;

export interface LatencySnapshot {
  samples: number;
  p50Ms: number | null;
  p95Ms: number | null;
  maxMs: number | null;
  negativeSamples: number;
  implausibleSamples: number;
  clockSkewSuspected: boolean;
}

export class BrowserLatencyTracker {
  private readonly window: number;
  private samples: number[] = [];
  private negative = 0;
  private implausible = 0;

  constructor(window: number = DEFAULT_LATENCY_WINDOW) {
    this.window = window;
  }

  /** Record one frame. Malformed timestamps are ignored, never guessed. */
  record(frameTs: string, receivedAtMs: number = Date.now()): void {
    const sentAtMs = Date.parse(frameTs);
    if (Number.isNaN(sentAtMs)) return;
    const delta = receivedAtMs - sentAtMs;
    if (delta < 0) {
      this.negative += 1;
      return;
    }
    if (delta > IMPLAUSIBLE_LATENCY_MS) {
      this.implausible += 1;
      return;
    }
    this.samples.push(delta);
    if (this.samples.length > this.window) this.samples.shift();
  }

  snapshot(): LatencySnapshot {
    const sorted = [...this.samples].sort((a, b) => a - b);
    const base = {
      samples: sorted.length,
      negativeSamples: this.negative,
      implausibleSamples: this.implausible,
    };
    if (this.negative > 0) {
      return { ...base, p50Ms: null, p95Ms: null, maxMs: null, clockSkewSuspected: true };
    }
    if (sorted.length === 0) {
      return {
        ...base,
        p50Ms: null,
        p95Ms: null,
        maxMs: null,
        clockSkewSuspected: this.implausible > 0,
      };
    }
    return {
      ...base,
      p50Ms: percentile(sorted, 0.5),
      p95Ms: percentile(sorted, 0.95),
      maxMs: sorted[sorted.length - 1],
      clockSkewSuspected: this.implausible > 0,
    };
  }
}

/** Nearest-rank percentile, matching the backend so the two figures compare. */
export function percentile(sorted: number[], fraction: number): number {
  if (sorted.length === 0) throw new Error("percentile of an empty sample");
  const index = Math.max(0, Math.min(sorted.length - 1, Math.round(fraction * sorted.length) - 1));
  return sorted[index];
}
