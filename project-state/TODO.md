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
> Hardware-free **FOUNDATIONS complete** (commits 26de8c2 … 5a1af31, D013 at
> `1c784e5`, and the P2-ANOM-S1 `AdaptiveStealthFDI` addition at `b82f935` —
> all **committed and pushed**, verified 2026-08-30; `main`/`origin/main` are
> identical at `b82f935`). Formal P2 **acceptance suite now exists and has
> been run** — see `P2_RESUME.md` §1a for the full status matrix (7 PASS /
> 4 FAIL, 11/14 Doc06 scenarios attempted). The broader-`PhysicsRule` scoping
> decision is recorded as **`DECISIONS.md` D014** (2026-08-30, documentation-
> only): no new channel coverage added; see the P2 remaining-work section
> below. `[x]` = implemented + tested; a checked accuracy/acceptance item
> still carries whatever caveat is written next to it — read before citing.

### Foundations (hardware-free, done)
- [x] Preprocess: median/low-pass filter, min-max normalize, 30-sample window — `edge/anomaly/preprocess.py` (f75b9dc). Filter kernel/alpha are REQUIRED caller args (no spec value); window_size default 30 (documented).
- [x] Multivariate Isolation Forest detector — `edge/anomaly/iforest.py` (5a1af31): single IF over flattened 180-dim 30×6 window (D-A); empirical-CDF/rank severity (D-B); `flag_threshold` a REQUIRED config param (no baked value); hyperparameters optional passthroughs. **NOT tuned/validated on real data** (dataset-gated, U07; SWaT diagnostics found further tuning has limited upside — see below).
- [x] Beta-reputation trust core + per-channel engine + banding (0.7/0.4) — `edge/trust/beta.py` (26de8c2) + `edge/trust/engine.py` (9479968). λ=0.7 **PENDING U01 approval**, UNCHANGED by D013.
- [x] `c`/`k`/`h` signal providers — `edge/trust/{c_consistency,k_correlation,h_reliability}.py` (D009/D010; `d1e6d48`/`691847f`/`c56cb4d`). Provisional, unvalidated; `c`'s rank-based noise and `h`'s GAMMA=0.95 speed are now precisely implicated in P2-TRUST-H1/H2's failures (see below) — neither touched by D013.
- [x] Attribution-engine shell (none/fault/attack branch logic) — `edge/anomaly/attribution.py` (cbd7527); reuses frozen `Attribution` enum (contract unchanged).
- [x] **Minimal, provisional `PhysicsRule`** — `edge/anomaly/physics_rule.py` (D013, committed `1c784e5`): `TrendSignPhysicsRule` reuses D010's current↔vibration heuristic verbatim to unblock the `AttributionEngine` wiring path (previously fully non-functional — no rule existed at all). Narrow scope: only ever names current/vibration; empirically ~50–60% attribution reliability even there (verified via multi-seed testing, not a single lucky run).
- [x] Synthetic §12.4 injection framework (now 8 hardware-free injections) — `edge/injection/` (ee730fe; + `AdaptiveStealthFDI` added 2026-08-29, committed `b82f935`); magnitudes/durations/caps REQUIRED args (no spec values); dry-run excluded (physical). Test/eval labels only, not wire.
- [x] Hardware-free P2 pipeline orchestrator — `edge/anomaly/pipeline.py` (d1ec0da): frames→preprocess→detector→ChannelFlagPolicy→trust→attribution; internal `WindowOutcome` (no wire contract).
- [x] **`ChannelFlagPolicy` redesigned ("Candidate B")** — `edge/anomaly/policy.py` (rewritten, D013, committed `1c784e5`): per-channel, own-baseline, two-sided empirical-CDF test (`fit()` on clean windows, flag if current variance is an outlier vs. that channel's own history), replacing the original same-window cross-channel high-variance rule that misdirected on spikes/constant-spoofs. Fixes P2-ANOM-H2; improves P2-TRUST-H2's flag rate 5x (13%→68%) but doesn't fully resolve it (see below).

### P2 SWaT diagnostics (hardware-free, DIAGNOSTICALLY COMPLETE — probes, NOT acceptance)
- [x] SWaT.A1 evaluation harness — `edge/eval/swat_eval.py` (`60a4dbe`), per D011/D012.
- [x] Full untuned evaluation + 3-variant normalization study + 17-point threshold sweep + 4-hypothesis root-cause screen + targeted step=1/D012-signal diagnostics + IF hyperparameter grid — see `P2_RESUME.md` §3a for the complete campaign and decisive finding (**D012 signal coverage is the dominant demonstrated limitation**, not normalization/threshold/ChannelFlagPolicy/IF config).
- [x] **Normalization decision: RESOLVED** — per-window min-max (current default) confirmed better-aligned with the PRD's own ≤3-window criteria than train-fit alternatives; not changed.
- [x] **SWaT track declared diagnostically complete.** No further SWaT experiments/tuning planned unless explicitly requested.

### P2 formal acceptance suite (`edge/tests/test_p2_acceptance.py`; D013 committed `1c784e5`, P2-ANOM-S1 committed `b82f935`)
11 of 14 Doc06 scenarios attempted; full matrix in `P2_RESUME.md` §1a.
- [x] P2-ANOM-H2, P2-ANOM-S1, P2-TRUST-E1, P2-TRUST-E2, P2-TRUST-S1 — **PASS**.
- [x] P2-ANOM-H3, P2-ANOM-E2 — **PASS at committed seeds**, but verified only ~50–60% reliable across other seeds (documented in-test, not claimed as validated).
- [ ] P2-ANOM-H1, P2-ANOM-E1 — **FAIL** (IF/threshold/normalization clean-FP + oscillation; U07-gated validation limitation, not missing code).
- [ ] P2-TRUST-H1 — **FAIL** (`c`'s rank-based noise; validation limitation).
- [ ] P2-TRUST-H2 — **FAIL** (mechanism fixed by Candidate B; remaining gap is `h`'s GAMMA/window-budget tension with D009, untouched).

P2-ANOM-S1 (adaptive stealth FDI) uses the new `AdaptiveStealthFDI` injection
(`edge/injection/injections.py`, 2026-08-29): a bias capped at a caller-chosen
bound instead of growing unboundedly. It provably evades a test-local "naive
residual" check throughout, yet the real, unmodified `ConsistencyProvider`
(`c`) still degrades trust for the channel below `TRUSTED_MIN` — verified at
the committed fixture seed/parameters only, not multi-seed stress-tested.

### P2 remaining work — split by kind (see `P2_RESUME.md` §7a for full reasoning)
**Mandatory implementation blockers (missing code, not tuning):**
- [ ] Real bench hardware (Pi + rig) — pre-existing, blocks literal O2/O3/O4 regardless of any software work. Also the only path that could ever unblock D014's deferred current↔temperature candidate below.

**Resolved (decision, not new capability):**
- [x] Broader `PhysicsRule` scoping — **`DECISIONS.md` D014 (2026-08-30)**: no new channel coverage added, `TrendSignPhysicsRule` (D013) unchanged. `pressure` REJECTED (would reopen D010's atmospheric-only BMP180 finding); `humidity` REJECTED (contradicts PRD's own design-integrity note requiring temperature/humidity to stay uncorrelated); `gas` REJECTED (no documented physical basis to build on). `current`↔`temperature` DEFERRED as the sole future candidate, gated on real bench data that does not exist yet. **O3 (≥85%) remains structurally unreachable** — this decision does not change that.

**Documented validation limitations (implementation exists, accuracy/tuning is the open question):**
- [ ] P2-ANOM-H1/E1 — IF + threshold + normalization retuning against real clean-baseline data (U07-gated).
- [ ] P2-TRUST-H1 — `c`'s empirical-CDF-vs-own-training-distribution definition (U01, provisional) may need reconsidering, not new code.
- [ ] P2-TRUST-H2 — `h`'s GAMMA=0.95 (D009) vs. this scenario's 3-window budget; a parameter/design-tension decision, explicitly deferred, not touched by D013.
- [ ] P2-ANOM-H3/E2 reliability — inherent to the minimal rule's scope; closing this for real would need the broader `PhysicsRule` D014 declined to build now, not a parameter tweak.

**Unrelated to D013/P2-ANOM-S1/D014, still open:**
- [ ] Authenticated scenario-injection hook (FR-A4)  *(command payload blocked: U14)*
- [ ] O10 confusion matrix / ablations on a real dataset — blocked on hardware (SWaT/WADI structurally cannot satisfy this, D011).

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
