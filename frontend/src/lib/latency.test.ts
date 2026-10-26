import { describe, expect, it } from "vitest";

import { BrowserLatencyTracker, IMPLAUSIBLE_LATENCY_MS, percentile } from "./latency";

const T0 = Date.parse("2026-09-24T10:00:00.000Z");
const at = (offsetMs: number) => new Date(T0 + offsetMs).toISOString();

describe("BrowserLatencyTracker", () => {
  it("reports null, not zero, before any frame", () => {
    const s = new BrowserLatencyTracker().snapshot();
    expect(s.samples).toBe(0);
    expect(s.p50Ms).toBeNull();
    expect(s.clockSkewSuspected).toBe(false);
  });

  it("measures receipt minus the frame's own timestamp", () => {
    const t = new BrowserLatencyTracker();
    [100, 200, 300, 400].forEach((lat, i) => t.record(at(i * 1000), T0 + i * 1000 + lat));
    const s = t.snapshot();
    expect(s.samples).toBe(4);
    expect(s.p50Ms).toBe(200);
    expect(s.p95Ms).toBe(400);
    expect(s.maxMs).toBe(400);
  });

  it("withholds percentiles when any frame arrives before it was sent", () => {
    const t = new BrowserLatencyTracker();
    t.record(at(0), T0 + 150);
    t.record(at(1000), T0 + 900); // -100 ms: clocks disagree
    const s = t.snapshot();
    expect(s.negativeSamples).toBe(1);
    expect(s.p50Ms).toBeNull();
    expect(s.clockSkewSuspected).toBe(true);
  });

  it("excludes implausibly late frames instead of clamping them", () => {
    const t = new BrowserLatencyTracker();
    t.record(at(0), T0 + 120);
    t.record(at(0), T0 + IMPLAUSIBLE_LATENCY_MS + 1);
    const s = t.snapshot();
    expect(s.samples).toBe(1);
    expect(s.implausibleSamples).toBe(1);
    expect(s.p50Ms).toBe(120);
    expect(s.clockSkewSuspected).toBe(true);
  });

  it("ignores malformed timestamps", () => {
    const t = new BrowserLatencyTracker();
    t.record("not a time", T0);
    expect(t.snapshot().samples).toBe(0);
  });

  it("keeps only the most recent window of samples", () => {
    const t = new BrowserLatencyTracker(3);
    [900, 900, 10, 20, 30].forEach((lat) => t.record(at(0), T0 + lat));
    const s = t.snapshot();
    expect(s.samples).toBe(3);
    expect(s.maxMs).toBe(30);
  });
});

describe("percentile", () => {
  it("uses nearest rank, matching the backend tracker", () => {
    expect(percentile([10, 20, 30, 40], 0.5)).toBe(20);
    expect(percentile([10, 20, 30, 40], 0.95)).toBe(40);
    expect(percentile([7], 0.5)).toBe(7);
  });

  it("refuses an empty sample", () => {
    expect(() => percentile([], 0.5)).toThrow();
  });
});
