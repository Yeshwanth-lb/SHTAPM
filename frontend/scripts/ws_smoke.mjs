// Live-path smoke test (P0 M3.5c) — NO npm deps. Uses Node's built-in global
// WebSocket (Node >= 22). Connects to the backend /ws and verifies real
// telemetry frames arrive matching the frozen contract, proving:
//   Simulator -> Mosquitto -> Backend -> WebSocket -> client
//
// Usage: node frontend/scripts/ws_smoke.mjs [wsUrl] [count]
const url = process.argv[2] || process.env.VITE_WS_URL || "ws://localhost:8002/ws";
const need = Number(process.argv[3] || 1);
const CHANNELS = ["temperature", "vibration", "pressure", "humidity", "gas", "current"];

if (typeof WebSocket === "undefined") {
  console.error("FAIL: global WebSocket unavailable (needs Node >= 22)");
  process.exit(2);
}

let got = 0;
const ws = new WebSocket(url);
const timer = setTimeout(() => {
  console.error(`TIMEOUT: received ${got}/${need} telemetry frames`);
  process.exit(1);
}, 15000);

ws.addEventListener("open", () => console.error(`[smoke] connected ${url}`));
ws.addEventListener("error", (e) => console.error("[smoke] ws error", e?.message ?? e));
ws.addEventListener("message", (ev) => {
  let f;
  try {
    f = JSON.parse(ev.data);
  } catch {
    return;
  }
  if (f.type !== "telemetry") return;
  const ok =
    typeof f.device_id === "string" &&
    f.sensors &&
    CHANNELS.every((c) => typeof f.sensors[c] === "number");
  if (!ok) {
    console.error("FAIL: off-contract telemetry frame", JSON.stringify(f));
    clearTimeout(timer);
    process.exit(1);
  }
  got += 1;
  console.log(`[smoke] telemetry #${got} device=${f.device_id} seq=${f.sample_seq} temp=${f.sensors.temperature}`);
  if (got >= need) {
    clearTimeout(timer);
    ws.close();
    console.log("SMOKE OK");
    process.exit(0);
  }
});
