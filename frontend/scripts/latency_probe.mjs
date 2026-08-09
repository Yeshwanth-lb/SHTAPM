// P0 hardware-free latency probe — NO deps (Node >= 22 global WebSocket).
//
// Measures: simulator *publish timestamp* (telemetry `ts`) → *WebSocket client
// receipt*. This is NOT physical-sensor → DOM-render latency; it is the
// hardware-free path (the simulator stands in for the edge, D005), and the
// browser's React render adds only a few ms over WS receipt.
//
// Requires the same host clock for publisher (simulator) and this probe — both
// run on the host, so the comparison is valid.
//
// Usage: node frontend/scripts/latency_probe.mjs [wsUrl] [samples]
//   e.g. node frontend/scripts/latency_probe.mjs ws://localhost:8002/ws 60
//
// PASS iff p95 < 2000 ms AND max < 2000 ms (PRD NFR-P1 / AC6; <1s target).

const url = process.argv[2] || process.env.VITE_WS_URL || "ws://localhost:8002/ws";
const need = Number(process.argv[3] || 50);
const TIMEOUT_MS = 90000;

if (typeof WebSocket === "undefined") {
  console.error("FAIL: global WebSocket unavailable (needs Node >= 22)");
  process.exit(2);
}

const latencies = [];
let received = 0;
let invalidTs = 0;
let negative = 0;
let nonTelemetry = 0;

const ws = new WebSocket(url);
const timer = setTimeout(() => finish("TIMEOUT"), TIMEOUT_MS);

ws.addEventListener("open", () => console.error(`[probe] connected ${url}; need ${need} samples`));
ws.addEventListener("error", (e) => console.error("[probe] ws error", e?.message ?? e));
ws.addEventListener("message", (ev) => {
  let f;
  try {
    f = JSON.parse(ev.data);
  } catch {
    return;
  }
  if (f.type !== "telemetry") {
    nonTelemetry++;
    return;
  }
  received++;
  const t = Date.parse(f.ts); // f.ts is ISO-8601 UTC ms, e.g. 2026-08-10T00:00:00.123Z
  if (Number.isNaN(t)) {
    invalidTs++;
    console.error(`[probe] DISCARD invalid ts: ${JSON.stringify(f.ts)}`);
    return;
  }
  const d = Date.now() - t;
  if (d < 0) {
    negative++;
    console.error(`[probe] DISCARD negative latency ${d}ms (ts=${f.ts}) — clock skew?`);
    return;
  }
  latencies.push(d);
  if (latencies.length >= need) {
    clearTimeout(timer);
    finish("OK");
  }
});

function pct(arr, p) {
  const s = [...arr].sort((a, b) => a - b);
  const idx = Math.min(s.length - 1, Math.max(0, Math.ceil((p / 100) * s.length) - 1));
  return s[idx];
}

function finish(reason) {
  try {
    ws.close();
  } catch {
    // ignore
  }
  const n = latencies.length;
  console.log("=== P0 latency probe: simulator publish ts → WS client receipt ===");
  console.log(`url=${url} reason=${reason}`);
  console.log(
    `telemetry_received=${received} valid_samples=${n} discarded_invalid_ts=${invalidTs} ` +
      `discarded_negative=${negative} non_telemetry_frames=${nonTelemetry}`,
  );
  if (n === 0) {
    console.log("RESULT: FAIL (no valid samples)");
    process.exit(1);
  }
  const min = Math.min(...latencies);
  const max = Math.max(...latencies);
  const p50 = pct(latencies, 50);
  const p95 = pct(latencies, 95);
  console.log(`min=${min}ms p50=${p50}ms p95=${p95}ms max=${max}ms (n=${n})`);
  const pass = p95 < 2000 && max < 2000 && n >= need;
  console.log(`RESULT: ${pass ? "PASS" : "FAIL"} (require p95<2000 AND max<2000, n>=${need})`);
  process.exit(pass ? 0 : 1);
}
