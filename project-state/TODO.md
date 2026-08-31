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
> **Physical hardware note (2026-08-31, `DECISIONS.md` D027):** the spikes
> below target the hardware actually in hand — **BMP280** (not the
> originally-documented BMP180) and **Raspberry Pi 5** (not the
> originally-documented Raspberry Pi 4). Six-channel design, the other four
> sensor parts (DS18B20, ADXL335, DHT22, MQ-135), and MCP3008/INA219 are
> unchanged. Neither substitution has been physically verified yet.
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
> **Hardware-free P2 has NO remaining mandatory software implementation**
> as of `d28de0b` (2026-08-30, end-of-day baseline — `main`/`origin/main`
> identical, working tree clean; see `P2_RESUME.md` §10 for the full
> handoff). Foundations complete (commits 26de8c2 … 5a1af31, D013 at
> `1c784e5`, P2-ANOM-S1 `AdaptiveStealthFDI` at `b82f935`). Formal P2
> **acceptance suite exists and has been run** — see `P2_RESUME.md` §1a for
> the full status matrix (7 PASS / 4 FAIL, 11/14 Doc06 scenarios attempted).
> The broader-`PhysicsRule` scoping decision is **`DECISIONS.md` D014**: no
> new channel coverage added. P2-TRUST-H2's root cause is **`DECISIONS.md`
> D015**: a joint D009/D010 structural limitation, both left unchanged, H2
> still FAIL. P2-TRUST-H1/P2-ANOM-H1/E1 share one rank-based-scoring root
> cause (documented `d28de0b`, no D016 created) — see `P2_RESUME.md` §7a.
> All 4 remaining FAILs are hardware/data-blocked or decision-required
> documented limitations, not missing code. See the P2 remaining-work
> section below. `[x]` = implemented + tested; a checked accuracy/acceptance
> item still carries whatever caveat is written next to it — read before
> citing.

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
- [ ] P2-ANOM-H1, P2-ANOM-E1 — **FAIL** (IF/threshold/normalization clean-FP + oscillation; U07-gated validation limitation, not missing code). Shares its rank-based-scoring root cause with P2-TRUST-H1 (analyzed 2026-08-30, see `P2_RESUME.md` §7a); has a fit-corpus-size-fixable excess but a nonzero floor regardless, not implemented.
- [ ] P2-TRUST-H1 — **FAIL** (`c`'s rank-based noise; validation limitation). Same rank-CDF architecture as P2-ANOM-H1/E1, but confirmed to have NO fit-corpus-size-fixable component (see `P2_RESUME.md` §7a) — no fix without redefining `c`.
- [ ] P2-TRUST-H2 — **FAIL** (root-caused and formally documented by D015: `ConstantSpoof`'s flat trend + D010's `k=1.0` non-paired default jointly floor `g`, independent of `h`'s GAMMA speed; D009/D010 both left unchanged, not a missing-code gap).

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
- [x] P2-TRUST-H2 scoping — **`DECISIONS.md` D015 (2026-08-30)**: root cause established as `ConstantSpoof`'s flat trend + D010's `k=1.0` non-paired default jointly flooring `g` at 0.3, independent of `h`; diagnostic replay confirmed removing GAMMA entirely still misses the 3-window budget. **D009 and D010 both left unchanged** (Option A); P2-TRUST-S1's collusion resistance fully preserved. **P2-TRUST-H2 remains FAIL; O4/AC2 is NOT satisfied** — this decision does not change that.

**Documented validation limitations (implementation exists, accuracy/tuning is the open question):**
- [ ] P2-ANOM-H1/E1 — IF + threshold + normalization retuning against real clean-baseline data (U07-gated). A fit-corpus-size improvement exists (simulator-only, analyzed 2026-08-30, `P2_RESUME.md` §7a) but is not implemented — doesn't resolve the literal zero-FP criterion.
- [ ] P2-TRUST-H1 — `c`'s empirical-CDF-vs-own-training-distribution definition (U01, provisional) may need reconsidering, not new code. Confirmed (2026-08-30, `P2_RESUME.md` §7a) to have no fit-corpus-size fix, unlike P2-ANOM-H1/E1.
- [ ] P2-ANOM-H3/E2 reliability — inherent to the minimal rule's scope; closing this for real would need the broader `PhysicsRule` D014 declined to build now, not a parameter tweak.

**Unrelated to D013/P2-ANOM-S1/D014, still open:**
- [ ] Authenticated scenario-injection hook (FR-A4)  *(command payload blocked: U14)*
- [ ] O10 confusion matrix / ablations on a real dataset — blocked on hardware (SWaT/WADI structurally cannot satisfy this, D011).

## P3 — Prognosis + RL + Self-Healing + Safety  ⚠ (no Doc06 phase; from PRD P3)
> **Readiness analysis performed 2026-08-30; U03/U04 scoped 2026-08-31
> (D016/D017); divergence/substitution behavioral design scoped 2026-08-31
> (D018); uncertainty-estimation method scoped 2026-08-31 (D019) — all
> documentation-only, no P3 code created.** See `P2_RESUME.md`
> §10/§11/§12/§13. P3 is next per the PRD build order but is still NOT
> implementation-ready as a whole. **D016:** prognosis and digital-twin are
> separate models; twin is single channel-agnostic model — no
> architecture/hyperparameter detail specified. **D017:** synthetic
> simulator data approved for **initial hardware-free digital-twin
> development/testing only** — NOT claimed sufficient for real-world
> accuracy; prognosis training stays blocked (no degradation-data source
> exists). **D018:** divergence measured against the isolated sensor's own
> continuing raw reading (an explicit backstop, NOT proof, NOT an
> independent reference — PRD's own R3 circularity risk carried forward,
> not resolved), using a fit-time z-score magnitude form; recovery reuses
> `TRUSTED_MIN=0.7`; 60s expiry without recovery escalates to Safe
> Pump-Stop; uncertainty stays edge-internal (frozen `DecisionMessage`
> **not** modified, existing `alerts` table used instead); P2 runs before
> P3 each cycle. **D019:** uncertainty-estimation method is a deterministic
> elapsed-substitution-time proxy (non-decreasing, bounded relative to the
> same 60s bound, resets per episode) — an explicit safety/confidence
> proxy, NOT a statistically calibrated error estimate; single-signal (no
> divergence, no reconstruction-stability); P3-HEAL-E1 wording clarified to
> *"Uncertainty flagged high (nearing cap); alert raised."* **Still open:**
> the time→uncertainty scaling formula, **U05's two numeric values**
> (uncertainty-cap, `divergence_threshold` — both data-gated), and **U06**
> (RL reward shaping). A synthetic dry-run signature needs its own new
> spec. The rule-based fallback is only partially independent (needs
> LSTM's `health`/`failure_eta`). Reusable now: the frozen
> `DecisionMessage`/`RLAction` contract and `RelayController.safe_off()`
> (P1). **Hardware-free plumbing implemented 2026-08-31 (`8cc5564`,
> committed and pushed):** `TwinReconstructor` Protocol seam
> (`edge/models/twin.py`, Protocol-only — no production implementation,
> none authorized by D016), `DivergenceScorer` (`edge/pipeline/
> divergence.py`, D018 pt.1's fit-time z-score form), `ElapsedTime
> UncertaintyProxy` (`edge/pipeline/uncertainty.py`, D019's method —
> scaling formula still a required, never-defaulted injected seam), and
> `SelfHealOrchestrator` (`edge/pipeline/self_heal.py`, D018 pts.2/3/5)
> wiring these to the existing `RelayController.safe_off()`. `divergence_
> threshold`, `uncertainty_cap`, and the scaling formula remain required
> parameters/injectable seams — no values chosen, U05 unchanged. 38 new
> tests pass hardware-free; full `edge/` suite unaffected (same 4
> pre-existing P2 failures, zero new regressions). No `DecisionMessage`/
> simulator/P2 change; no new decision recorded. **Further P3 work
> (numeric values, the scaling formula, real reconstruction-accuracy
> validation, prognosis, RL) still needs explicit direction — do not
> default to it.** **Since then (2026-08-31, committed + pushed through
> `66f790e`):** the P2→P3 adapter (`edge/pipeline/cycle.py`,
> `process_isolated_channels` — takes `isolated_channels`/`raw_values` as
> REQUIRED, caller-supplied inputs, never derives isolation from
> trust/band; validate-all-upfront so one bad channel can't side-effect a
> valid one) was implemented, then hardened with multi-channel and
> zero-side-effect tests. A concrete **LSTM digital-twin** was then
> implemented (`edge/models/lstm_twin.py`, `LSTMTwinReconstructor`):
> single-layer, unidirectional PyTorch LSTM → final hidden state → Linear
> → scalar (approved architecture shape, D016 leaves `hidden_size`
> unspecified — REQUIRED, no default), masked-channel input (never reads
> the missing channel's own data) + one-hot indicator, satisfying the
> existing `TwinReconstructor` Protocol unchanged. A diagnostic-only
> self-supervised training harness (`edge/eval/twin_training.py`) trains
> it on the existing simulator + `Preprocessor` only — **no meaningful
> reconstruction accuracy is claimed or validated**; the simulator's clean
> baseline has no cross-channel/temporal structure beyond each channel's
> own fitted mean. Two integration tests then proved the real
> `LSTMTwinReconstructor` (not a fixture stub) flows end-to-end through
> `SelfHealOrchestrator`/`process_isolated_channels`, producing a
> well-formed outcome. `divergence_threshold`, `uncertainty_cap`, and the
> scaling formula are still not chosen — U05/D019 unchanged. Isolation
> itself is still not decided anywhere in this repo (FR-RL2 makes it an
> RL-agent action; the agent and its deterministic fallback, FR-RL4, are
> unbuilt) — `process_isolated_channels` still needs a real
> `isolated_channels` source. 68 P3 tests pass hardware-free.**
> **Since then (2026-08-31, `DECISIONS.md` D020, documentation-only):**
> the elapsed-time→uncertainty scaling formula is **linear** (`f(x)=x`,
> output domain [0,1] now a specification requirement — not enforced at
> runtime by `ScalingFn`/`ElapsedTimeUncertaintyProxy`, which remain
> unconstrained/unchanged) and **`uncertainty_cap` = 0.8** (in the
> proxy's own output domain; ~48s of the 60s substitution budget). Both
> were policy choices, not data-gated (D019's proxy was never a
> calibrated error estimate, so no bench data would have resolved either).
> **`uncertainty_cap` remains a REQUIRED constructor argument — no default
> was added to any code.** U05 now narrows to exactly one remaining item:
> `divergence_threshold`'s numeric value, still fully data-gated. No code
> or test was created or modified by D020.
> **Since then (2026-08-31): an untrained prognosis architecture skeleton
> was implemented and committed hardware-free** (`LSTMPrognosisPredictor`/
> `_LSTMPrognosisNet`, `edge/models/lstm_prognosis.py`, `9f802df` — single-
> layer unidirectional LSTM → final hidden state → two heads, health
> `Linear(hidden_size,3)` + failure_eta `Linear(hidden_size,1)`;
> `hidden_size` REQUIRED, no default; trust-weighted input reuses the
> existing P2 `Window`/`TrustReading` structures; no Protocol added — no
> current consumer exists to type against, unlike the digital twin; no
> training, dataset, loss, optimizer, or pipeline integration included).
> **Then `DECISIONS.md` D021 (2026-08-31, documentation-only) adopted
> PRONOSTIA/FEMTO** (IEEE PHM 2012 bearing run-to-failure dataset, NASA
> PCoE-hosted) **as the initial external prognosis training/methodology
> dataset** — vibration + temperature ONLY, as a same-failure-mode-class
> proxy for pump-bearing degradation; explicitly NOT evidence of pump
> validation; pressure/humidity/gas/current remain unvalidated; real
> pump/bench validation still required; D017 unchanged. D021 does not
> resolve HealthState thresholds, failure_eta horizon/units, loss,
> optimizer, resampling/windowing, or how the other four channels are
> represented during any PRONOSTIA-based training run — all remain fully
> open. No dataset was downloaded, no training performed, no code or test
> was created or modified by D021.
> **Then the dataset was acquired and inspected read-only** (verified
> download from the NASA PCoE-hosted URL, byte-exact + zip-integrity
> checked, extracted only to the session scratchpad — never into this
> repo): confirmed 6 training + 11 test bearing experiments; vibration =
> 25.6kHz bursts (0.1s) every ~10s (not continuous); temperature =
> continuous 10Hz; real, dramatic degradation-to-failure signatures
> measured directly (vibration amplitude ~20-30x rise, temperature rise
> ~70→164 in Bearing1_1); RUL derivable via the Test_set/Full_Test_Set
> truncation-point pairing. **Since then, `DECISIONS.md` D022 (2026-08-31,
> documentation-only) resolved three narrow input-representation-mechanics
> choices**: temperature 10Hz→1Hz via 1-second block mean; vibration burst
> → one RMS-of-Euclidean-magnitude scalar per real burst, no interpolation
> across the ~10s gaps; and an explicit per-timestep `vibration_observed`
> indicator (not a reuse of `trust=0`, which cannot represent per-timestep
> absence — `trust[ch].trust` is one scalar per channel per whole window,
> not per-timestep) — widening the future prognosis input contract from
> `len(CHANNELS)` to `len(CHANNELS)+1`, **without redesigning the LSTM
> itself** (still single-layer, unidirectional, same two heads). D022 does
> NOT resolve the four non-covered channels, HealthState thresholds,
> failure_eta horizon/units, loss, optimizer, hyperparameters, or authorize
> training. D021 unchanged. No code, preprocessing, dataset loader, or test
> was created or modified by D022.
> **Then a PRONOSTIA preprocessing/loader layer was implemented and
> tested hardware-free** (`edge/eval/pronostia_prep.py`/`test_pronostia_
> prep.py`, 20 tests, real-data sanity-checked against the acquired
> dataset — not yet committed). Real-data testing surfaced genuine raw-
> data quality problems across the 17 bearings: a full **read-only audit**
> then measured them precisely (5 bearings with zero temperature files;
> 11 bearings with leading-edge vibration bursts before temperature
> coverage begins, 75 bursts/~13.5 min total; `Bearing1_1`'s 2 corrupted
> timestamp files). **Since then, `DECISIONS.md` D023 (2026-08-31,
> documentation-only) authorized three purely subtractive treatments** for
> these exact findings: (1) exclude the 5 zero-temperature bearings
> entirely; (2) a general rule discarding leading-edge vibration bursts
> before temperature coverage begins; (3) for `Bearing1_1` only, discard
> exactly `acc_02121.csv`/`acc_02122.csv` (corrupted timestamps) — NOT a
> general corruption-detection capability. No fabrication, interpolation,
> or reconstruction of any kind is authorized. No bearing changes train/
> test split membership; the official 6-learning/11-test split is
> preserved in membership, with usable counts becoming 4 training + 8
> test (12/17 total expected loadable once implemented). `Bearing1_1`
> needs both treatments 2 and 3 together. D023 does not resolve channel
> treatment, thresholds, horizon/units, loss, optimizer, or authorize
> training; D016–D022 unchanged. No code/loader/test was created or
> modified by D023 itself — the three treatments are not yet implemented.
> **Since then, `DECISIONS.md` D024 (2026-08-31, documentation-only)
> authorized the eventual four-channel availability-indicator
> representation** for pressure/humidity/gas/current (PRONOSTIA supplies
> none of these): Option B — `0.0` placeholders paired with one explicit
> per-timestep availability indicator per channel, extending D022's own
> `vibration_observed` mechanism. Establishes the eventual, fully-resulting
> prognosis input width as **11** (6 `CHANNELS` + 1 `vibration_observed`,
> D022-approved but not yet implemented in code + 4 new per-channel
> availability indicators) — **`edge/models/lstm_prognosis.py` remains
> committed and unchanged at input width 6; D024 does not implement this
> widening.** `trust` is explicitly prohibited from representing absence
> and keeps its FR-M3 meaning exactly; the four indicators are
> machine-readable absence markers only, never evidence that
> pressure/humidity/gas/current were measured, trained, or validated. D024
> authorizes the representation only, not training. D021–D023 unchanged.
> No code, test, or dataset file created or modified by D024.
> **Since then, `DECISIONS.md` D025 (2026-08-31, documentation-only)
> established the PRONOSTIA prognosis-target methodology**: RUL/failure_eta
> targets generated ONLY for the 4 usable training bearings (`Bearing1_1,
> 1_2, 2_1, 3_1`) — test-split bearings remain WITHOUT failure_eta targets,
> and `Validation_Set`/`Full_Test_Set` is explicitly NOT authorized.
> `RUL(t) = final_recorded_timestep − t`, final timestep = `RUL=0`
> (grounded in D021's own "run to actual physical failure" language),
> represented in **seconds** (numerically identical to 1Hz timesteps here).
> HealthState will use **bearing-relative/proportional RUL bands** (not
> fixed-second bands, given the ~17× lifetime variation across usable
> bearings) — **exact Warning/Critical proportions are NOT resolved by
> D025** and require a later, evidence-based decision. Any cross-bearing
> statistic used in target generation must be fit training-bearings-only.
> D025 does not authorize training, windowing/sampling, loss/optimizer/
> hyperparameters, acceptance metrics, RL, or pump validation; D021's
> methodology-validation-only scope is explicitly preserved; D021–D024
> unchanged. No code, label, or dataset file created or modified by D025.
> **Since then, `DECISIONS.md` D026 (2026-08-31, documentation-only)
> resolved D025's two remaining numeric HealthState proportions as
> explicit modeling-policy values**: Healthy = RUL > 20% of lifetime,
> Warning = 5% < RUL <= 20%, Critical = RUL <= 5%. Both are explicitly
> policy choices, not empirically derived or PRONOSTIA ground truth. The
> 5% Critical value is loosely, qualitatively informed by a read-only
> investigation of the 4 training bearings' own late-life behavior
> (~5-10% region) — not statistically proven. The 20% Warning value has
> **no empirical support** from the 4 bearings (their degradation-onset
> timing was found genuinely inconsistent) and is pure policy. D025's
> RUL/failure_eta methodology, leakage discipline, and label-semantics
> requirement all remain unchanged and apply in full to these numbers.
> D026 does not authorize windowing/sampling, loss, optimizer,
> hyperparameters, training, acceptance metrics, RL, pump validation, or
> Validation_Set/Full_Test_Set use. No code, label, or dataset file
> created or modified by D026.
- [ ] LSTM health (Healthy/Warning/Critical) + failure-ETA on trust-weighted windows  *(architecture skeleton implemented hardware-free 2026-08-31 — `LSTMPrognosisPredictor`/`_LSTMPrognosisNet`, `edge/models/lstm_prognosis.py`, `9f802df`: untrained, no accuracy/calibration claim, no Protocol, no pipeline integration, still 6-wide. Training-data source partially addressed: D021 adopts PRONOSTIA/FEMTO (acquired + inspected read-only) for vibration+temperature methodology validation only — pressure/humidity/gas/current still have no real data source. D022 resolves the temperature-downsampling method, vibration-burst-summary statistic, and a missing-vibration indicator (eventual input contract `len(CHANNELS)+1`). A preprocessing/loader layer exists (`edge/eval/pronostia_prep.py`, committed `c425de0`) and a full 17-bearing data-quality audit found 12/17 bearings usable after D023's three subtractive treatments (implemented and verified against real data). D024 authorizes the eventual four-channel availability-indicator representation (Option B, per-channel, eventual input width 11) — **implemented and committed** (`8b7aa6c`). D025 establishes the RUL/HealthState target-generation methodology (training-bearings-only RUL in seconds, proportional HealthState bands); **D026 resolves the numeric proportions (20% Warning / 5% Critical, explicit policy)**. HealthState methodology AND numeric thresholds are now both resolved on paper, and **target-generation code implementing D025/D026 exists** (`compute_prognosis_targets`, `edge/eval/pronostia_prognosis_targets.py`). **A training harness now exists and has been run against real PRONOSTIA data** (`edge/eval/pronostia_prognosis_training.py`, `68addbb`: 30-sample sliding windows, stride=1, target at each window's final timestep, leave-one-bearing-out cross-validation across the 4 D025 bearings, CrossEntropy+MSE multi-task loss, full evaluation metrics — window/stride/loss/optimizer-interface choices are implementation-level, documented in-module, not DECISIONS.md entries). The first real-data run collapsed to always predicting the majority HealthState class (macro F1 ~0.30, zero Warning/Critical recall in every fold); root-caused via a forward-pass-only diagnostic to unnormalized raw input values (e.g. temperature 70–164°C) saturating the LSTM's gates, confirmed on a fresh untrained network before any training occurred. **Fixed (`983eb04`)**: per-channel z-score input normalization + inverse-frequency class-weighted loss, both fit from training-split examples only per fold (leakage-safe). Re-running confirmed the collapse is gone (all three classes now predicted), but cross-bearing generalization remains inconsistent (1 of 4 folds macro F1 ~0.59, the other 3 weak) — a known small-sample limitation (only 4 bearings, confirmed heterogeneous degradation shapes even within one operating condition), not a code defect. **No claim of a validated/production-ready prognosis model is made.** Real pump/bench validation still required)*
- [x] Digital-twin: channel-agnostic reconstruction + uncertainty estimate  *(concrete LSTM reconstruction implemented + tested hardware-free 2026-08-31 — `LSTMTwinReconstructor`/`_LSTMTwinNet`, `edge/models/lstm_twin.py`, `43e114d`: single-layer unidirectional LSTM → final hidden state → Linear → scalar; `hidden_size` REQUIRED, no default; masked-channel input never reads the true value + one-hot indicator; satisfies the unmodified `TwinReconstructor` Protocol, integration-tested with `SelfHealOrchestrator` at `66f790e`. Diagnostic-only training harness at `edge/eval/twin_training.py` uses the existing simulator + Preprocessor only. **No meaningful reconstruction accuracy or real-world validation claimed** — the simulator's clean baseline has no cross-channel/temporal structure beyond each channel's own fitted mean. Uncertainty estimate implemented + tested hardware-free (`ElapsedTimeUncertaintyProxy`, `edge/pipeline/uncertainty.py`, D019) — scaling formula (linear, D020) and uncertainty-cap (0.8, D020) both resolved as policy decisions, documentation-only; still required, never-defaulted constructor arguments in code, no value baked in)*
- [ ] DQN over state `[health, anomaly_flag, T1..T6, failure_eta]` + reward  *(blocked: U06)*
- [ ] Deterministic rule-based RL fallback (fail-safe)
- [x] Self-heal: isolate/re-weight + bounded uncertainty-capped virtual substitution  *(orchestration plumbing implemented + tested hardware-free 2026-08-31 — `SelfHealOrchestrator`, `edge/pipeline/self_heal.py`, `8cc5564`: recovery at reused `TRUSTED_MIN`, 60s expiry reused from the Doc05-documented default, wired to the existing `RelayController.safe_off()`. P2→P3 adapter (`process_isolated_channels`, `edge/pipeline/cycle.py`, `fe4042e`/`0cc4d31`) wires an existing P2 `WindowOutcome` through, taking `isolated_channels`/`raw_values` as REQUIRED caller-supplied inputs (never derived from trust/band), validate-all-upfront. Now integration-tested with the real `LSTMTwinReconstructor` (`66f790e`). 68 tests total incl. exact-boundary-equality, simultaneous-conditions, repeated-escalation, multi-channel, and zero-side-effect cases. `uncertainty_cap` (0.8) and the scaling formula (linear) resolved by D020 (policy, documentation-only — still REQUIRED constructor arguments, no default added); `divergence_threshold` remains the sole open numeric value, data-gated (U05). Nothing in this repo yet decides *which* channels are isolated (FR-RL2/FR-RL4 unbuilt); not validated on real hardware)*
- [x] Divergence detection → escalate to Safe Pump-Stop  *(implemented + tested hardware-free 2026-08-31 — `DivergenceScorer`, `edge/pipeline/divergence.py`, `8cc5564`: fit-time z-score of the twin-vs-isolated-sensor residual (D018 pt.1), wired through `SelfHealOrchestrator` to the existing `RelayController.safe_off()`; numeric `divergence_threshold` remains a REQUIRED parameter, no value chosen — still data-gated, U05)*
- [ ] Dry-run detection → autonomous Safe Pump-Stop
- [ ] Gate: rule fallback engages if policy missing; divergence→safe-stop (60s-expiry-without-recovery also escalates, D018); dry-run stops before damage; self-heal <500ms

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
