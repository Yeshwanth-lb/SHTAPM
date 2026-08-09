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

### Milestone 3+ (P0, NOT started)
- [ ] Hardware-free telemetry simulator/replay scaffold (D005)
- [ ] SPIKE: MQTT→backend→WS→React number render; measure E2E latency (software path — hardware-free)
- [ ] Gate: offline `docker compose up` clean on fresh machine; go/no-go recorded *(M1: `compose config` validated; full `up` not yet run)*

### P0 hardware-blocked (need Raspberry Pi + bench rig — DO NOT fake)
- [ ] SPIKE (Pi): read one sensor per interface; INA219 resolves pump current  🔒 hardware-blocked
- [ ] SPIKE (Pi): time LSTM + Isolation Forest forward pass (<500ms budget)  🔒 hardware-blocked

## P1 — Hardware / Acquisition
- [ ] Pi OS + I2C/SPI/1-Wire enabled
- [ ] One driver per sensor: `read() → {value, unit, ts, healthy}` + calibration + range clamp
- [ ] 1 Hz sampler → telemetry frame (contract) → local ring buffer
- [ ] `paho-mqtt` publisher → `…/telemetry`; retained LWT status; reconnect/backoff/buffered resume
- [ ] Relay driver + hardware/software watchdog (manual stop/start; watchdog → pump OFF on death)
- [ ] Gate: <1% dropped over 10 min; watchdog safe-state verified physically; buffered resume proven

## P2 — Anomaly Detection + Attribution + Trust  ⚠ (no Doc06 phase; from PRD P2)
- [ ] Preprocess: median/low-pass filter, min-max normalize, 30-sample sliding window
- [ ] Isolation Forest trained on clean baseline + scoring
- [ ] Cross-sensor physics/correlation attribution (fault vs attack) + reason tag  *(blocked: U02)*
- [ ] Beta-reputation trust update + banding (0.7/0.4) + recovery  *(blocked: U01)*
- [ ] Authenticated scenario-injection hook
- [ ] Gate: no false anomaly on clean 5-min baseline; spoof trust <0.4 in ≤3 windows; attribution ≥85%

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
