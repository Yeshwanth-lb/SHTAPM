# TODO

> Phase-based checklist on the reconciled roadmap (PRD phase authority D001;
> Doc06 detail mapped in D002). `[ ]` = not done, `[~]` = in progress,
> `[x]` = done + verified. Mark `[x]` ONLY when actually implemented and verified.
> Full task/test detail: PRD §20 + `docs/SHTAPM_Doc06_ImplementationPlan.md`.

## Pre-phase (planning / handoff)
- [x] Documentation authored (`docs/`)
- [x] Git repo + CLAUDE.md + GitHub push
- [x] PRD/Doc06 phase conflict reconciled
- [x] project-state/ handoff system created
- [x] project-state/ committed to Git (commit 30b03ee)

## P0 — Foundations & Spikes  (IN PROGRESS)

### Milestone 1 — Repository foundation & configuration  ✅ (verified, pending commit)
- [x] Monorepo structure per TRD §02.6
- [x] `docker-compose.yml` — 4 services; mosquitto+db functional, backend+frontend wired-empty behind `app` profile *(verified: `docker compose config` valid)*
- [x] `.env.example` — all TRD §02.7 vars (incl. `VITE_AURORA_MOTION`, `VITE_REDUCE_TRANSPARENCY_DEFAULT`)
- [x] CI + lint/test skeleton (pyproject ruff/black/pytest; ESLint/Prettier/Vitest configs; `.pre-commit-config.yaml`; `.github/workflows/ci.yml`) *(configs valid; linters execute in CI — not installed locally)*
- [x] `.gitignore` improved (model binaries, broker state, logs); root + service READMEs
- [~] Self-host Geist / Geist Mono fonts (no CDN) — **foundation only**: `@font-face` contract + `assets/fonts/` + OFL note done; woff2 binaries + exact vendoring pin deferred to P5 (npm package name/version unverifiable in P0 — not guessed)

### Milestone 2 — Shared data contract  ✅ (verified, pending commit)
- [x] Freeze canonical telemetry/decision/ledger contract (D006/**D007**)
- [x] Pydantic v2 canonical models `backend/app/schemas/contracts.py` *(14 tests pass: valid accepted, invalid/shorthand/nested-healing/missing-payload_hash rejected)*
- [x] Mirrored TS types `frontend/src/types/contracts.ts` + runtime mirror test *(authored; tsc/vitest NOT run locally — npm blocked by TLS/proxy; runs in CI/P5)*

### Milestone 3 — Hardware-free telemetry path (IN PROGRESS)
- [x] **M3.1** Telemetry simulator (D005/D008): deterministic generator (6 frozen channels, 1 Hz-ready), MQTT publisher to `shtapm/{device_id}/telemetry` (QoS 0), tests
- [x] **M3.2** MQTT broker integration: existing publisher → Mosquitto → subscriber verifier; frozen-contract validated on receive. **Real round trip verified against `eclipse-mosquitto:2.0`** via project compose (32/32 pass incl. the integration test; it self-skips when no broker). Also: fixed `docker compose up` partially — mosquitto pulls + starts (full-stack `up` still a later gate).
- [x] **M3.3** Backend MQTT telemetry ingestion: FastAPI lifespan starts a paho consumer (`shtapm/+/telemetry`), validates via frozen contract → in-memory `TelemetryStore`; graceful under broker-down; `/healthz` liveness. **Real path simulator→Mosquitto→backend verified** (46/46 with broker; 44 pass + 2 skip without). No DB/auth/WS/REST-history.
- [x] **M3.4** Backend WebSocket fan-out: `/ws` telemetry frames (Doc05 §05.8 envelope) via a `TelemetryBroadcaster` seam fed by the consumer sink; optional `?device_id` filter; bounded per-client queues. **Real MQTT→backend→WS path verified** (56/56 with broker; 53 pass + 3 skip without). No auth (P4), no decision/ledger frames yet.
- [~] **M3.5** Minimal React live-telemetry consumer (code complete; verification split — see below)
  - [x] M3.5a React 18 scaffold, Vite react plugin, Vitest+jsdom+RTL config
  - [x] M3.5b `useTelemetryWebSocket` + `TelemetryView` + `App`, reuse frozen contract, plain state, capped-backoff reconnect, contract-guarded frames
  - [~] M3.5c live-path proof: MQTT→backend ingestion verified live under uvicorn (`/healthz` telemetry_count>0, mqtt_connected:true); **Backend→WS→external client NOT verifiable in this sandbox** (uvicorn WS upgrade → 403 with both websockets & wsproto; likely localhost Upgrade interception). App-level WS proven by M3.4 TestClient tests. Node `scripts/ws_smoke.mjs` authored.
  - 🔒 CI-only (npm TLS-blocked locally): RTL tests, `tsc`, `vite build` — run in CI (Option A gate). package.json version pins unverified locally.
- [x] SPIKE: end-to-end MQTT→backend→WS→React path VERIFIED; **hardware-free E2E latency VERIFIED** via `frontend/scripts/latency_probe.mjs` (sim publish `ts` → WS receipt): 3×60=180 samples, p50=2ms, p95=3–5ms, max=6–14ms → PASS `<2000ms`
- [ ] Physical sensor→UI/DOM latency + under-load (Aurora, real rig) — 🔒 hardware-dependent, NOT verified
- [x] **P0 offline four-service stack — VERIFIED end-to-end (hardware-free)** — `docker compose up --build` starts all four; backend reachable on **host :8002** (`/healthz` `mqtt_connected:true`, `--host` = runtime-built IPv4 wildcard), frontend served on **:5173**; simulator→Mosquitto→backend ingestion (`telemetry_count` rises, `devices:["pump-01"]`); **live WS frames confirmed with an external WS client on `ws://localhost:8002/ws`** (`ws_clients` rose). Docker builds succeed via the per-machine corporate-CA drop-in (D-note); simulator stays host-side (D008). *Browser GUI render not run in-sandbox (no GUI); WS-client receipt of the frozen-contract frames proves the browser path.*
- [ ] Gate close-out (formal): measure sensor→UI E2E latency (<2s) under load; browser GUI render on a workstation — nice-to-have, hardware-free

### P0 hardware-blocked (need Raspberry Pi + bench rig — DO NOT fake)
- [ ] SPIKE (Pi): read one sensor per interface; INA219 resolves pump current  🔒 hardware-blocked
- [ ] SPIKE (Pi): time LSTM + Isolation Forest forward pass (<500ms budget)  🔒 hardware-blocked

## P1 — Hardware / Acquisition  (hardware-free software COMPLETE; physical gates blocked)
- [x] **C1** sensor driver abstraction — `SensorDriver`/`Reading` interface + `Sensor` (calibration, range-clamp, health, ts) + fakes (511537c). Real GPIO/I2C/1-Wire driver bodies remain 🔒 hardware-blocked.
- [x] **C2** 1 Hz sampler → frozen telemetry frame via shared `build_telemetry` → bounded overwrite ring buffer; monotonic `sample_seq`; 1–10 Hz; injected clock (3bbbf19).
- [x] **C3** resilient MQTT publisher — retained LWT `online`/`offline`, online-on-connect, FR-Q4 buffered resume (`ceil(rate×60)`) + FIFO replay, reconnect backoff (3a82229); real-broker integration verified.
- [x] **C2→C3 runtime** — `AcquisitionRuntime` (sample_once→publish) + hardware-free dev CLI `edge/main.py` (345fdde); real-broker integration verified.
- [x] **C4** relay + deadman watchdog software abstraction — default OFF, `on`/`off`/`safe_off`, watchdog expiry→OFF, explicit reset/recovery, injected clock (10d39be).
- [ ] Pi OS + I2C/SPI/1-Wire enabled  🔒 hardware-blocked
- [ ] **Physical acquisition gate** (needs Pi/rig — DO NOT fake): <1% dropped over 10 min on real sensors; **INA219 pump-current resolved**; **physical relay safe-stop** clicks pump OFF before damage; watchdog defaults pump OFF on real process death  🔒 hardware-blocked

## P2 — Anomaly Detection + Attribution + Trust  ⚠ (no Doc06 phase; from PRD P2)
> Hardware-free **FOUNDATIONS complete** (commits 26de8c2 … 5a1af31); actual P2 **VALIDATION NOT done**.
> `[x]` here = scaffolding/plumbing implemented + unit/interface-tested — NOT a detection/trust/attribution accuracy claim.

### Foundations (hardware-free, done)
- [x] Preprocess: median/low-pass filter, min-max normalize, 30-sample window — `edge/anomaly/preprocess.py` (f75b9dc). Filter kernel/alpha are REQUIRED caller args (no spec value); window_size default 30 (documented).
- [x] Multivariate Isolation Forest detector — `edge/anomaly/iforest.py` (5a1af31): single IF over flattened 180-dim 30×6 window (D-A); empirical-CDF/rank severity (D-B); `flag_threshold` a REQUIRED config param (no baked value); hyperparameters optional passthroughs. **NOT tuned/validated on real data** (dataset-gated, U07). Tests SKIP in CI until scikit-learn added to CI deps (follow-up).
- [x] Beta-reputation trust core + per-channel engine + banding (0.7/0.4) — `edge/trust/beta.py` (26de8c2) + `edge/trust/engine.py` (9479968). λ=0.7 **PENDING U01 approval**; signal-agnostic (c/k/h supplied, not defined).
- [x] Attribution-engine shell (none/fault/attack branch logic) + `PhysicsRule` seam — `edge/anomaly/attribution.py` (cbd7527); reuses frozen `Attribution` enum (contract unchanged); real physics rule NOT implemented (U02).
- [x] Synthetic §12.4 injection framework (7 hardware-free injections) — `edge/injection/` (ee730fe); magnitudes/durations REQUIRED args (no spec values); dry-run excluded (physical). Test/eval labels only, not wire.
- [x] Hardware-free P2 pipeline orchestrator — `edge/anomaly/pipeline.py` (d1ec0da): frames→preprocess→detector→ChannelFlagPolicy→trust→attribution; internal `WindowOutcome` (no wire contract).

### P2 diagnostics (hardware-free, done — probes, NOT acceptance)
- [x] IF behaviour probe on the simulator + §12.4 injections — `edge/eval/if_eval.py` (d17942f). Finding: **~21.6% clean-vs-clean FP** at the eval-fixture threshold; constant-spoof "detection" under per-window min-max is a normalization flatness artifact, not cross-sensor detection.
- [x] Preprocessing comparison (per-window min-max vs train-fit global min-max vs z-score) — `edge/eval/preproc_experiment.py` (d17942f). Clean FP 0.216 / 0.035 / 0.041; per-window min-max washes out additive bias; global/z-score preserve it but assume stationarity.
- [ ] **Normalization decision DEFERRED to real SWaT/WADI/TEP evaluation** (U07) — no production preprocessing change approved; FR-P1 "min-max" doesn't mandate per-window vs global.

### P2 validation + decisions — NOT done
- [ ] c/k/h signal definitions (consistency / cross-sensor correlation / historical reliability)  *(blocked: U01/U02)*
- [ ] `ChannelFlagPolicy` per-channel localization from the window-level IF result  *(undecided; needs multivariate per-feature attribution — not from IF internals)*
- [ ] Real cross-sensor physics/correlation attribution rule + tolerances + reason tag  *(blocked: U02; bench pressure = atmospheric proxy → dataset-gated)*
- [ ] IF hyperparameter tuning + flag threshold + real clean-baseline fit  *(dataset-gated: U07; simulator validates plumbing/marginal faults only, NOT cross-sensor spoof)*
- [ ] Add `scikit-learn` to CI deps so the IF test module runs in CI  *(follow-up)*
- [ ] Authenticated scenario-injection hook (FR-A4)  *(command payload blocked: U14)*
- [ ] Dataset evaluation on SWaT/WADI (or TEP substitute)  *(blocked: U07)*
- [ ] Gate: no false anomaly on clean 5-min baseline; spoof trust <0.4 in ≤3 windows; attribution ≥85% (O3); O10 confusion matrix  *(NOT validated — needs U01/U02 + dataset)*

## P3 — Prognosis + RL + Self-Healing + Safety  ⚠ (no Doc06 phase; from PRD P3)
- [ ] LSTM health (Healthy/Warning/Critical) + failure-ETA on trust-weighted windows  *(blocked: U03/U04)*
- [ ] DQN over state `[health, anomaly_flag, T1..T6, failure_eta]` + reward  *(blocked: U06)*
- [ ] Deterministic rule-based RL fallback (fail-safe)
- [ ] Self-heal: isolate/re-weight + bounded uncertainty-capped virtual substitution  *(blocked: U05)*
- [ ] Divergence detection → escalate to Safe Pump-Stop
- [ ] Dry-run detection → autonomous Safe Pump-Stop
- [ ] Gate: rule fallback engages if policy missing; divergence→safe-stop; dry-run stops before damage; self-heal <500ms

## P4 — Backend + Ledger
- [ ] SQLAlchemy models (all Doc05 tables) + Alembic migration
- [ ] TimescaleDB hypertables (`sensor_readings`, `decisions`) + continuous aggregates + retention
- [ ] `devices.health_state` rollup on decision insert
- [ ] Auth: register/login/refresh/logout; bcrypt; JWT access+refresh; RBAC dependency
- [ ] Row-Level Security + per-request `app.user_id`/`app.role`
- [ ] Seed: 3 roles + device + thresholds + 6 sensors (with `display_hue`)
- [ ] Mosquitto config (auth/topics/persistence)
- [ ] Subscriber tasks (telemetry/decision/ledger/status) Pydantic→DB (off hot path)
- [ ] WebSocket gateway + connection manager (per-device scope, token auth), immediate fan-out
- [ ] `system_health` WS frame (Aurora feed)
- [ ] REST endpoints (Doc05 §05.7)
- [ ] Define `…/command` inject payload — 🔒 BLOCKED U14 (unspecified in docs; do not invent)
- [ ] Ledger verify service (walk chain, report `broken_at`)
- [ ] Gate: MQTT→WS <1s; role checks pass; tamper caught; malformed input never downs a service

## P5 — Dashboard / Aurora
- [ ] Vite + TS app; Tailwind + Aurora tokens (Doc04 §04.2); shadcn/Radix restyled glass; Framer presets
- [ ] `components/aurora/`: MeshBackground (health-reactive), GlassTile, TactileToggle
- [ ] Glass auth screens + token handling + silent refresh; protected layout (sidebar rail, top bar, latency chip)
- [ ] `useWebSocket` reconnecting hook + Zustand live store; `useHealthField`; TanStack Query REST clients
- [ ] Pages wired to real data: Overview, Device Detail cockpit, Alerts, Ledger, Analytics, Devices, Settings, Users, System
- [ ] All empty/error/demo states (Doc03 §03.6)
- [ ] uPlot live charts (60s scroll, luminous line, breathing cursor, 140ms ease, per-channel hue)
- [ ] Fault=amber glow / Attack=rose glow+shimmer / VIRTUAL=dashed violet + purple aura + pulsing chip
- [ ] Trust constellation (ECharts) + dense bar fallback; RUL/health gauge + hero numeral
- [ ] RL Action Log + Ledger stream in glass wells (bloom-in, mono truncated hash, verify cascade, tamper fracture)
- [ ] System-health micro-tiles + live E2E latency chip (teal/amber/rose)
- [ ] Gate: AA contrast over brightest aurora; color+shape/label never color-alone; reduced-motion + reduce-transparency parity; no console errors

## P6 — End-to-End Integration + Demo Hardening
- [ ] Full stack on real rig via compose; run PRD §18.4 script end to end
- [ ] Latency-probe harness: synthetic physical event → DOM update <2s (Aurora live)
- [ ] Recorded-session replay/fallback profile behind a toggle
- [ ] Chaos passes: Wi-Fi drop, broker kill, sensor unplug, backend restart (mid-stream)
- [ ] Performance/soak: 60-min 60fps; GPU-budget (≤4 orbs / ≤6 blur layers); fps<50 auto-downgrade proven
- [ ] Production compose profile + single-machine offline demo profile
- [ ] Automate PRD §18.3 pre-flight self-check; tune `VITE_AURORA_MOTION` for demo GPU
- [ ] Backup/export (session telemetry + ledger) + teardown script
- [ ] Gate: §18.4 runs twice (live + fallback); sensor→UI <2s under load; all chaos recovers; AC1–AC10 green

## P7 — Quantitative Evaluation  ⚠ (no Doc06 phase; from PRD P7)
- [ ] Run pipeline on SWaT/WADI (and/or TEP) with injection taxonomy (§12.4)  *(blocked: U07)*
- [ ] Ablations: PdM-only vs +anomaly vs +static-trust vs +dynamic-trust(full)
- [ ] Metrics: RUL/health accuracy attack-vs-clean; fault-vs-attack confusion matrix; detection/isolation latency; false-isolation rate; uptime-vs-%compromise curve
- [ ] Adaptive white-box adversary test  *(scope: U13)*
- [ ] Gate: AC9 — SWaT/WADI (or documented substitute) + ablations + confusion matrix

---
**Legend of blockers:** U01–U14 tracked in `DECISIONS.md` (UNDECIDED section). Do not silently resolve.
