// Live-path smoke test (P0 M3.5c) — NO npm deps. Uses Node's built-in global
// WebSocket + fetch (Node >= 22). Connects to the backend /ws and verifies
// real telemetry frames arrive matching the frozen contract, proving:
//   Simulator -> Mosquitto -> Backend -> WebSocket -> client
//
// P4-M6: /ws now requires a JWT (?token=), so this script logs in first via
// POST /api/auth/login — credentials come from SMOKE_EMAIL/SMOKE_PASSWORD
// env vars (never hardcoded; pair with the SEED_ADMIN_EMAIL/PASSWORD used by
// `python -m app.core.seed`, backend/app/core/seed.py).
//
// Usage: node frontend/scripts/ws_smoke.mjs [wsUrl] [count]
const url = process.argv[2] || process.env.VITE_WS_URL || "ws://localhost:8002/ws";
const need = Number(process.argv[3] || 1);
const apiBase = process.env.VITE_API_BASE_URL || "http://localhost:8002";
const CHANNELS = ["temperature", "vibration", "pressure", "humidity", "gas", "current"];

if (typeof WebSocket === "undefined") {
  console.error("FAIL: global WebSocket unavailable (needs Node >= 22)");
  process.exit(2);
}

const email = process.env.SMOKE_EMAIL;
const password = process.env.SMOKE_PASSWORD;
if (!email || !password) {
  console.error("FAIL: SMOKE_EMAIL and SMOKE_PASSWORD env vars are required (/ws needs a token)");
  process.exit(2);
}

const loginResp = await fetch(`${apiBase}/api/auth/login`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ email, password }),
});
if (!loginResp.ok) {
  console.error(`FAIL: login to ${apiBase}/api/auth/login returned ${loginResp.status}`);
  process.exit(2);
}
const { access_token: token } = await loginResp.json();
const authedUrl = url + (url.includes("?") ? "&" : "?") + `token=${encodeURIComponent(token)}`;

let got = 0;
const ws = new WebSocket(authedUrl);
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
  console.log(
    `[smoke] telemetry #${got} device=${f.device_id} seq=${f.sample_seq} temp=${f.sensors.temperature}`,
  );
  if (got >= need) {
    clearTimeout(timer);
    ws.close();
    console.log("SMOKE OK");
    process.exit(0);
  }
});
