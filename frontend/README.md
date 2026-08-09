# frontend/ — Aurora admin dashboard (React + Vite + TS)

**P0 M3.5 status: minimal live-telemetry proof.** Not the Aurora dashboard (P5).

Present now:
- React 18 app: `index.html`, `src/main.tsx`, `src/App.tsx`.
- `src/hooks/useTelemetryWebSocket.ts` — connects `VITE_WS_URL`, accepts only
  frozen-contract telemetry frames, latest-per-device state, capped-backoff reconnect.
- `src/features/telemetry/TelemetryView.tsx` — plain table of the six channels
  (no Aurora/Tailwind/charts).
- `src/types/contracts.ts` — the frozen M2 TS mirror (reused verbatim).
- Vitest + jsdom + React Testing Library tests (run in CI — see below).
- `scripts/ws_smoke.mjs` — dependency-free Node live-path proof (global WebSocket).

Added in **P5** (not now): Aurora tokens/Tailwind, shadcn/Radix, uPlot/ECharts,
Framer Motion, Zustand, TanStack Query, routing, the full dashboard.

## Run (needs backend `/ws` reachable at `VITE_WS_URL`)
```bash
npm install
npm run dev          # http://localhost:5173
```

## Test / build
```bash
npm run test         # Vitest + RTL (jsdom)
npm run typecheck    # tsc --noEmit
npm run build        # tsc + vite build
```

## Live-path smoke (no npm; needs the stack running)
```bash
node scripts/ws_smoke.mjs ws://localhost:8000/ws 2
```

> Local note: in the current dev sandbox `npm install` is blocked by a
> TLS/proxy cert error, so frontend deps, Vitest/RTL, `tsc`, and `vite build`
> run in **CI**, not locally. Dependency versions here are pins for CI to
> resolve; they were not installed/verified locally.
