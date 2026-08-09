# Document 02 — Technical Requirements Document (TRD) *(enhanced)*
### SHTAPM — Self-Healing Trust-Aware Predictive Maintenance for Adversarially Resilient Industrial IoT
**Companion to:** PRD v1.0 · App Flow (03) · UI/UX "Aurora" (04) · Backend Schema (05) · Implementation Plan (06)
**Domain:** Remote water/wastewater pumping infrastructure · **Demonstrator:** bench water-pump rig, 6 live sensor channels
**Status:** Build-ready · **Version:** 1.1 (adds Aurora frontend stack + performance budgets)

> This document locks every technical decision so firmware, backend, and frontend stay coherent. Where the PRD said *what*, this says *how* and *with what*. Decisions here are frozen; changes go through a version bump. **v1.1** adds the libraries and performance budgets required by the Aurora design language (Doc 04) — glassmorphism, mesh gradients, bento motion — without changing any functional decision.

---

## 02.1 Guiding principles (non-negotiable)
1. **Safety and self-healing live at the edge.** The `sense → detect → attribute → decide → heal → actuate` loop runs entirely on the Raspberry Pi. The cloud/backend is never in the safety path. Hard rule.
2. **The backend is a read/observe + advisory-control plane.** Visualization, history, config, audit, and *advisory* commands (scenario injection, threshold config) — never safety-critical actuation.
3. **One canonical data contract** (Doc 05) is shared verbatim by firmware, backend, and frontend. No component invents field names.
4. **Everything degrades gracefully.** Broker/Wi-Fi/sensor/backend failure each has a defined fallback. No blank screens, no crashes, no silent data loss.
5. **Beauty must not cost a frame (new in v1.1).** The Aurora aesthetic (blur, mesh gradients, motion) is subordinate to the 1 Hz live stream and the < 500 ms self-heal / < 2 s sensor→UI budgets. Any visual that threatens those budgets is downgraded automatically (see §02.9).

---

## 02.2 Technology stack — locked decisions

| Layer | Decision | Version (pin) | Rationale / notes |
|-------|----------|---------------|-------------------|
| **Edge language** | Python | 3.11.x | Same language as ML; one toolchain; ample at 1 Hz. |
| **Edge ML** | scikit-learn (Isolation Forest), PyTorch (LSTM), Stable-Baselines3 (DQN) | sklearn 1.4, torch 2.2, sb3 2.3 | CPU-inferable on Pi 4 at demo scale. |
| **Edge runtime** | systemd services + supervisor script | — | Auto-restart, watchdog, clean boot. |
| **Messaging** | Eclipse Mosquitto (MQTT) | 2.0.x | Lightweight, local-hostable (no venue-Wi-Fi dependency). |
| **MQTT client** | `paho-mqtt` | 1.6.x | Mature. |
| **Backend framework** | **FastAPI** (Python) | 0.110.x | Async, native WebSocket, Pydantic validation; one language across backend+edge+ML. |
| **ASGI** | Uvicorn (+Gunicorn workers in prod) | uvicorn 0.29 | Standard. |
| **Real-time push** | **WebSocket** (FastAPI native) | — | Server→client live telemetry/decisions/ledger. Client never polls for live data. |
| **Time-series store** | **TimescaleDB** (Postgres ext) | PG 16 + TSDB 2.14 | Hypertables + retention for telemetry; one DB, relational + time-series. |
| **Relational** | PostgreSQL | 16.x | Users, devices, alerts, ledger, config. |
| **Cache / fan-out (optional)** | Redis | 7.x | Multi-client WS fan-out; optional for single-device demo. |
| **ORM / migrations** | SQLAlchemy 2.0 + Alembic | — | Typed models, versioned schema. |
| **Auth** | JWT (access+refresh), `python-jose`, `passlib[bcrypt]` | — | Stateless, RBAC-ready. |
| **Frontend framework** | **React 18 + Vite + TypeScript** | React 18.2, Vite 5 | SPA fits a single always-on live dashboard; Vite = fast HMR. **Next.js explicitly not used** — no SSR benefit, complicates the persistent-WebSocket model. |
| **Routing** | React Router | 6.x | Standard SPA routing. |
| **Server state** | TanStack Query | 5.x | REST history/config. |
| **Live UI state** | Zustand | 4.x | WS-fed live store (telemetry/decision/ledger). |
| **Live charts** | **uPlot** | 1.6 | Streams 1 Hz with thousands of points at 60fps, tiny CPU — essential for the Aurora "luminous line" without jank. |
| **Radial / gauges / heatmap** | **ECharts** | 5.5 | Trust ring/gauge, RUL gauge; GPU-friendly, glossy. |
| **Motion / animation (new)** | **Framer Motion** | 11.x | Bento bloom-in, FLIP reflow, tile hover-lift, log entry arrival, state crossfades. Declarative + `prefers-reduced-motion` aware. |
| **Ambient mesh gradient (new)** | CSS radial-gradients + blurred orb layers, animated via CSS `@keyframes` / Framer; **no heavy WebGL** by default | — | Aurora background as blurred DOM orbs keeps GPU cost low; a WebGL/shader upgrade is optional (see §02.9). |
| **Styling** | Tailwind CSS + CSS variables (Aurora tokens from Doc 04) | Tailwind 3.4 | Token-driven glass + status glow; dark-first. |
| **Component primitives** | shadcn/ui (Radix) | current | Accessible, unstyled-by-default; restyled to glass. |
| **Fonts (new — Aurora)** | **Geist** + **Geist Mono** (primary), Satoshi / Plus Jakarta Sans fallbacks | self-host via `@fontsource` or local | Geometric, thin-forward; matches Doc 04. Self-hosted (no external CDN dependency for the offline demo). |
| **WS client** | native `WebSocket` + reconnecting wrapper | — | Backoff + resume (Doc 03 error states). |
| **Edge acquisition** | Python drivers on Raspberry Pi OS (not MCU firmware) | RPi OS Bookworm 64-bit | Pi is the edge computer. |
| **Sensor libs** | `gpiozero`, `smbus2` (I²C), `spidev` (MCP3008), `w1thermsensor` (DS18B20), `adafruit-circuitpython-dht` | current | One lib per interface; no bit-banging. |
| **Testing** | pytest, Vitest + React Testing Library, Playwright, Locust | current | Matches PRD strategy. |
| **Container** | Docker + docker-compose (broker, db, backend, frontend) | — | One-command offline bring-up. |
| **Lint/format** | ruff + black (Py), eslint + prettier (TS), pre-commit | current | Enforced. |

## 02.3 Backend & IoT communication setup
- **MQTT topics:** `shtapm/{device_id}/telemetry` (1 Hz, QoS 0) · `…/decision` (QoS 1) · `…/ledger` (QoS 1) · `…/command` (backend→edge advisory, QoS 1) · `…/status` (retained LWT online/offline, QoS 1).
- **Backend flow:** Mosquitto → FastAPI subscriber tasks → Pydantic validation → TimescaleDB/Postgres write (async, off hot path) → **immediate** WebSocket fan-out.
- **WS channels (server→client, one multiplexed connection):** `telemetry`, `decision`, `ledger`, `device_status`, `system_health`, `alert` — each frame tagged by `type`.
- **Latency budget:** WS fan-out fires on message receipt independent of the DB write, keeping **sensor→UI < 1 s target**.
- **New — Ambient Health Field feed:** the backend derives a single `system_health` rollup (`healthy|warning|critical`) per device (and fleet) and pushes it on the `system_health`/`decision` channels so the frontend can drive the Aurora background mood (Doc 04 §04.5). No new safety logic — purely a presentation-state derivation from existing `health_state`/`attribution`.

## 02.4 Database & auth summary (full model in Doc 05)
- **Provider:** self-hosted PostgreSQL 16 + TimescaleDB (docker); cloud-swappable later.
- **Schema:** relational + hypertables for `sensor_readings` / `decisions`.
- **Auth:** JWT access (15 min) + rotating refresh (7 day). bcrypt passwords. RBAC: `operator`, `analyst`, `admin`. App-level device scoping + DB-level RLS (Doc 05).

## 02.5 Hosting & deployment
| Component | Demo (primary) | Optional cloud (future) |
|-----------|----------------|--------------------------|
| Edge node | Raspberry Pi 4, systemd, on-device Mosquitto+backend option | edge stays physical |
| Broker | Mosquitto (docker) on Pi or demo laptop | Managed MQTT (HiveMQ/EMQX) |
| Backend | Uvicorn (docker) | Fly.io / Render / VM |
| Database | Postgres+TimescaleDB (docker) | Managed PG + TSDB |
| Frontend | Vite build via nginx (docker) | Static host (Vercel/Netlify/nginx) |
> **Demo golden rule:** whole stack runs on a **single machine via `docker-compose up`** with **no internet** (fonts self-hosted, no external CDNs) — venue Wi-Fi can never sink the demo.

## 02.6 Folder structure & naming conventions (strict)
```
shtapm/
├── docker-compose.yml   .env.example
├── edge/                        # Raspberry Pi edge node
│   ├── drivers/  ds18b20.py adxl335.py bmp180.py dht22.py mq135.py ina219.py
│   ├── acquisition/             # sampler, buffer, mqtt_publisher
│   ├── pipeline/                # preprocess, anomaly, trust, prognosis(lstm), rl_agent, self_heal
│   ├── actuation/               # relay, watchdog, safe_stop
│   ├── ledger/                  # hash_chain writer
│   ├── config/  thresholds.yaml device.yaml
│   ├── models/  iforest.pkl lstm.pt dqn.zip
│   ├── main.py                  # supervisor loop
│   └── tests/
├── backend/  app/{api,ws,mqtt,models,schemas,core,services,main.py}  alembic/  tests/
├── frontend/                    # React + Vite + TS
│   ├── src/
│   │   ├── pages/               # route-level
│   │   ├── components/          # charts/ panels/ ui/ aurora/   (aurora/ = mesh bg, glass tile, tactile toggle)
│   │   ├── features/            # telemetry/ trust/ ledger/ devices/
│   │   ├── hooks/               # useWebSocket, useLiveTelemetry, useAuth, useHealthField
│   │   ├── store/               # zustand
│   │   ├── api/                 # TanStack Query clients
│   │   ├── lib/                 # ws client, formatters, motion presets
│   │   ├── styles/              # tokens.css (Aurora), tailwind config
│   │   └── types/               # TS types (mirror Doc 05 contract)
│   └── tests/
└── docs/
```
**Conventions:** Python `snake_case`/`PascalCase`; TS `camelCase`/`PascalCase`, components `PascalCase.tsx`. Branches `feat|fix|chore/…`, Conventional Commits. Domain terms are identical everywhere (`trust_score`, `anomaly_flag`, `failure_eta`) across firmware, DB, API, UI. **The contract is sacred.** Aurora-specific UI lives under `components/aurora/` so the design language is swappable without touching data logic.

## 02.7 Environment variables (names only)
```
# Database
POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD DATABASE_URL
# Auth
JWT_SECRET_KEY JWT_ACCESS_TTL_MIN JWT_REFRESH_TTL_DAYS PASSWORD_BCRYPT_ROUNDS
# MQTT
MQTT_HOST MQTT_PORT MQTT_USERNAME MQTT_PASSWORD MQTT_TLS_ENABLED
# Backend
BACKEND_HOST BACKEND_PORT CORS_ALLOWED_ORIGINS LOG_LEVEL WS_MAX_CLIENTS
# Frontend (VITE_ prefix)
VITE_API_BASE_URL VITE_WS_URL VITE_DEMO_MODE VITE_AURORA_MOTION VITE_REDUCE_TRANSPARENCY_DEFAULT
# Edge node
DEVICE_ID SAMPLE_RATE_HZ WINDOW_SIZE MODEL_DIR THRESHOLD_CONFIG_PATH EDGE_MQTT_HOST EDGE_MQTT_PORT FALLBACK_REPLAY_PATH
# Ops
ENVIRONMENT SENTRY_DSN(optional)
```
> `VITE_AURORA_MOTION` (full|reduced|off) and `VITE_REDUCE_TRANSPARENCY_DEFAULT` let the demo/venue tune the aesthetic vs performance without code changes.

## 02.8 Hardware / firmware stack
- **Not a microcontroller build.** Raspberry Pi 4 is the edge computer running Python (RPi OS Bookworm 64-bit). Sensors interface via GPIO/I²C/SPI/1-Wire.
- **Interfaces:** DS18B20 → 1-Wire GPIO4; DHT22 → GPIO; ADXL335 & MQ-135 → MCP3008 (SPI); BMP180 & INA219 → I²C; relay/buzzer/LEDs → GPIO out.
- **Dev env:** VS Code Remote-SSH to Pi; `venv`; hardware libs per §02.2. No Arduino/PlatformIO.
- **Firmware discipline:** each driver exposes `read() -> {value, unit, ts, healthy: bool}`; a failed read returns `healthy=False` and never throws into the loop.

## 02.9 Performance budgets for the Aurora aesthetic (new)
Beauty is gated by hard budgets; the frontend self-downgrades to protect the live stream.

| Concern | Budget / rule | Downgrade path |
|---------|---------------|----------------|
| Live chart render | 60fps at 1 Hz ingest; ring buffer 60–120 pts | Drop glow shadow → flat line if fps < 50 |
| `backdrop-filter` blur | ≤ 6 simultaneous blurred glass layers on screen | Reduce blur radius; fall back to semi-opaque solid (`VITE_REDUCE_TRANSPARENCY`) |
| Ambient mesh orbs | ≤ 4 orbs, CSS/DOM blurred, repaint-throttled | Freeze to static gradient (also the `prefers-reduced-motion` path) |
| Motion | transform/opacity/filter only; 140–500ms eases | `VITE_AURORA_MOTION=reduced\|off` disables non-essential motion |
| Sensor→UI E2E | **< 2 s hard, < 1 s target** — measured continuously (system-health tile) | Aurora effects shed first, data path never |
| Self-heal loop (edge) | **< 500 ms** — unaffected by any UI concern (edge-resident) | n/a |
> Rule of thumb encoded in code review: **if a visual effect and the data budget conflict, the effect loses, automatically and silently.**

---

### TRD intent, in one line
A single-language-per-tier, edge-safe, offline-demonstrable IoT stack — FastAPI + MQTT/WebSocket + TimescaleDB behind a React/Vite dashboard skinned in the Aurora glass-and-mesh language — where the beautiful UI is always subordinate to the 1 Hz live stream and the sub-second self-heal.
