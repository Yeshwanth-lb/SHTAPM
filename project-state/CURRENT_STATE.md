# CURRENT_STATE

> Implementation memory for SHTAPM. A fresh session reads this first, then
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/` — not duplicated here.

**Last updated:** 2026-08-31, end of session — **`983eb04` is the local
`main` HEAD** (commits ahead of `origin/main`, not yet pushed; working
tree clean once this documentation sync is committed). This session: P3 scoping closed U03/U04
(`DECISIONS.md` D016/D017), the divergence/substitution behavioral design
(D018), and the uncertainty-estimation method (D019) — followed by the
smallest hardware-free P3 slice those decisions authorize (Protocol-only
twin seam, `DivergenceScorer`, `ElapsedTimeUncertaintyProxy`,
`SelfHealOrchestrator`, pushed as `8cc5564`), then a P2→P3 cycle-wiring
scoping pass and adapter (`process_isolated_channels`, `fe4042e`) with a
hardening pass (`0cc4d31`), then a digital-twin architecture scoping pass
and its implementation: a concrete **LSTM digital twin**
(`LSTMTwinReconstructor`, `43e114d`) plus integration tests proving it
flows end-to-end through the existing orchestration (`66f790e`) — see the
new P3 sections below for full detail. **Since then, `DECISIONS.md` D020
(2026-08-31, documentation-only) resolved `uncertainty_cap` (0.8) and the
elapsed-time→uncertainty scaling formula (linear, output domain [0,1]) as
policy decisions — both remain required, never-defaulted constructor
arguments in code, no default added.** `divergence_threshold` remains the
sole open U05 numeric value, still data-gated; **no meaningful
reconstruction accuracy or real-world validation is claimed anywhere in
this slice**. **Since then, an untrained hardware-free prognosis
architecture skeleton was implemented and committed** (`LSTMPrognosisPredictor`/
`_LSTMPrognosisNet`, `edge/models/lstm_prognosis.py`, `9f802df` — single-
layer unidirectional LSTM, two heads, no Protocol, no training/pipeline
integration), **then `DECISIONS.md` D021 (2026-08-31, documentation-only)
adopted PRONOSTIA/FEMTO** (IEEE PHM 2012 bearing run-to-failure dataset)
**as the initial external prognosis training/methodology dataset** —
vibration + temperature ONLY, as a same-failure-mode-class proxy for
pump-bearing degradation; explicitly NOT evidence of pump validation;
pressure/humidity/gas/current remain unvalidated; real pump/bench
validation still required; D017 unchanged. D021 does not resolve
HealthState thresholds, failure_eta horizon/units, loss, optimizer,
resampling/windowing, or the other four channels' treatment — all remain
open. No dataset downloaded, no training performed, no code/tests modified
by D021. **Then PRONOSTIA was acquired and inspected read-only**
(NASA PCoE-hosted URL, verified byte-exact + zip-integrity, extracted only
to the session scratchpad — never into this repo): 6 training + 11 test
bearing experiments confirmed; vibration = 25.6kHz bursts every ~10s
(periodic, not continuous); temperature = continuous 10Hz; real
degradation-to-failure signatures directly measured (vibration amplitude
~20-30x rise, temperature rise ~70→164 in Bearing1_1); RUL derivable via
the Test_set/Full_Test_Set truncation pairing. **Since then, `DECISIONS.md`
D022 (2026-08-31, documentation-only) resolved three narrow input-
representation-mechanics choices**: temperature 10Hz→1Hz via 1-second
block mean; vibration burst → one RMS-of-Euclidean-magnitude scalar per
real burst (no interpolation across the ~10s gaps); an explicit
per-timestep `vibration_observed` indicator (not `trust=0`, which cannot
represent per-timestep absence given `trust[ch].trust` is one scalar per
channel per whole window) — widening the future prognosis input contract
from `len(CHANNELS)` to `len(CHANNELS)+1` **without redesigning the LSTM**
(still single-layer, unidirectional, same two heads). D022 does not
resolve the four non-covered channels, HealthState thresholds, failure_eta
horizon/units, loss, optimizer, hyperparameters, or authorize training;
D021 unchanged. No code, preprocessing, dataset loader, or test created or
modified by D022. **Then a PRONOSTIA preprocessing/loader layer was
implemented** (`edge/eval/pronostia_prep.py`/`test_pronostia_prep.py`, 20
tests, real-data sanity-checked against the acquired dataset — not yet
committed), and real-data testing plus a full **read-only 17-bearing
audit** measured genuine raw-data quality problems: 5 bearings with zero
temperature files; 11 bearings with leading-edge vibration bursts before
temperature coverage begins (75 bursts, ~13.5 min total); `Bearing1_1`'s 2
corrupted-timestamp files (`acc_02121.csv`/`acc_02122.csv`). **Since then,
`DECISIONS.md` D023 (2026-08-31, documentation-only) authorized three
purely subtractive treatments** for exactly these findings — exclude the 5
zero-temperature bearings; a general leading-edge-burst-trimming rule; a
`Bearing1_1`-only exclusion of those 2 named corrupted files (explicitly
NOT a general corruption-detection capability) — with no fabrication,
interpolation, or reconstruction of any kind authorized. No bearing
changes train/test split membership; the official 6-learning/11-test
split is preserved in membership, with usable counts becoming 4 training +
8 test (12/17 total expected loadable once implemented; `Bearing1_1` needs
both the trimming rule and its own file exclusion together). D023 does not
resolve channel treatment, thresholds, horizon/units, loss, optimizer, or
authorize training; D016–D022 unchanged. **The three treatments were
subsequently implemented in `edge/eval/pronostia_prep.py` and verified
against the real dataset (12/17 bearings loadable, matching the audit
exactly) — still uncommitted.** **Since then, `DECISIONS.md` D024
(2026-08-31, documentation-only) authorized the eventual four-channel
availability-indicator representation** for pressure/humidity/gas/current
(PRONOSTIA supplies none of these): Option B — `0.0` placeholders paired
with one explicit per-timestep availability indicator per channel,
extending D022's `vibration_observed` mechanism. Establishes the eventual,
fully-resulting prognosis input width as **11** (6 `CHANNELS` + 1
`vibration_observed`, D022-approved but not yet implemented in code + 4
new per-channel availability indicators) — **`edge/models/lstm_prognosis.py`
remains committed and unchanged at input width 6; D024 does not implement
this widening.** `trust` is explicitly prohibited from representing
absence and keeps its FR-M3 meaning exactly; the four indicators are
machine-readable absence markers only, never evidence that
pressure/humidity/gas/current were measured, trained, or validated. D024
authorizes the representation only, not training. D021–D023 unchanged. No
code, test, or dataset file created or modified by D024. **Since then,
`DECISIONS.md` D025 (2026-08-31, documentation-only) established the
PRONOSTIA prognosis-target methodology**: RUL/failure_eta targets
generated ONLY for the 4 usable training bearings (`Bearing1_1, 1_2, 2_1,
3_1`); test-split bearings remain WITHOUT failure_eta targets;
`Validation_Set`/`Full_Test_Set` explicitly NOT authorized. `RUL(t) =
final_recorded_timestep − t`, final timestep = `RUL=0` (grounded in
D021's own "run to actual physical failure" language), in **seconds**
(numerically identical to 1Hz timesteps). HealthState will use
**bearing-relative/proportional RUL bands** (not fixed-second bands,
given the ~17× lifetime variation across usable bearings) — **exact
Warning/Critical proportions are NOT resolved**, pending a later,
evidence-based decision. Cross-bearing statistics used in target
generation must be fit training-bearings-only. No training, windowing,
loss/optimizer/hyperparameters, acceptance metrics, RL, or pump
validation authorized; D021's methodology-validation-only scope
preserved; D021–D024 unchanged; no code/label/dataset file created or
modified by D025. **Since then, `DECISIONS.md` D026 (2026-08-31,
documentation-only) resolved D025's two remaining numeric HealthState
proportions as explicit modeling-policy values**: Healthy = RUL > 20% of
lifetime, Warning = 5% < RUL <= 20%, Critical = RUL <= 5%. Neither is
empirically derived or PRONOSTIA ground truth — 5% is loosely,
qualitatively informed by a read-only investigation of the 4 training
bearings' own late-life behavior (not statistically proven); 20% has no
empirical support at all (onset timing was found genuinely inconsistent
across the four bearings) and is pure policy. D025's RUL/failure_eta
methodology, leakage discipline, and label-semantics requirement remain
entirely unchanged and apply in full to these numbers. D026 authorizes
no windowing/sampling, loss, optimizer, hyperparameters, training,
acceptance metrics, RL, pump validation, or Validation_Set/Full_Test_Set
use; no code/label/dataset file created or modified by D026.
**Hardware-free
P2 still
has no remaining mandatory software implementation** (unchanged from the
prior session — see `P2_RESUME.md` §10 for that handoff). See
`DECISIONS.md` D013–D019 and `P2_RESUME.md` §1a/§3a/§7a/§9/§10/§14 for
full detail; this file gives the short version. P0/P1 sections below are
unchanged and still accurate as of 2026-08-10.)

---

## Snapshot
- **Current phase:** P4 — Backend + Ledger, hardware-free implementation + tests COMPLETE across all six planned milestones (M1–M6: DB models/migration, auth core, telemetry persistence, REST API, ledger service, WS auth — see the dedicated "P4" section near the end of this file for full detail). **Not yet committed.** P0–P3 status below is unchanged from the prior session and still accurate.
- **P0–P3 phase summary (unchanged since 2026-08-31):** P2 — Anomaly / Trust / Attribution (hardware-free FOUNDATIONS complete, incl. c/k/h + `ChannelFlagPolicy` + a minimal `PhysicsRule`; formal P2 acceptance suite now exists and has partially passed — see below). P0 + P1 hardware-free paths complete + verified. P3 — hardware-free self-healing plumbing **plus a concrete LSTM digital twin, both integration-tested** (D016–D019 implementation, the P2→P3 cycle adapter, and `LSTMTwinReconstructor`; numeric values, scaling formula, real reconstruction validation, prognosis, and RL all still open — see below).
- **Current milestone:** `66f790e` (LSTM digital-twin implementation + its `SelfHealOrchestrator`/`process_isolated_channels` integration tests, 2026-08-31 — **local `main` only, 2 commits ahead of `origin/main`**; see the new P3 sections below for full detail). Previous P2 milestone, still accurate: D013 (`DECISIONS.md`, committed at `1c784e5`) — `ChannelFlagPolicy` redesigned ("Candidate B": per-channel own-baseline two-sided test) and a minimal provisional `PhysicsRule` (`TrendSignPhysicsRule`, reusing D010's `k` heuristic) implemented to unblock `AttributionEngine`. Since then (2026-08-29), the one remaining hardware-free P2 acceptance gap was closed: a new `AdaptiveStealthFDI` injection type + its P2-ANOM-S1 scenario, **committed and pushed as `b82f935`** (verified 2026-08-30 — `main`/`origin/main` identical at `b82f935`). The formal P2 acceptance suite (`edge/tests/test_p2_acceptance.py`) now attempts 11/14 Doc06 scenarios: **7/11 PASS** (full matrix: `P2_RESUME.md` §1a). The broader-`PhysicsRule` scoping decision was closed and recorded as **D014** (2026-08-30, documentation-only — no new code): no new channel coverage added; `current`↔`temperature` deferred as the sole future candidate, gated on real bench data. The P2-TRUST-H2 root cause was re-analyzed and recorded as **D015** (2026-08-30, documentation-only): the gap is a joint D009/D010 structural limitation, not primarily GAMMA — both decisions left unchanged, H2 remains FAIL.
- **Overall completion:**
  - **P0 hardware-free: VERIFIED** — offline four-service stack (simulator→Mosquitto→backend→WebSocket→frontend) + E2E latency probe (p95 3–5 ms).
  - **P1 hardware-free: COMPLETE** — C1 driver abstraction, C2 sampler/ring buffer, C3 MQTT buffered-resume/LWT, C2→C3 runtime, C4 relay/watchdog. All unit + real-broker-integration verified.
  - **P2 hardware-free FOUNDATIONS: COMPLETE** — preprocess/windowing, injection framework (now 8 injections incl. `AdaptiveStealthFDI`), Beta trust core + engine, c/k/h signal providers, `ChannelFlagPolicy` (Candidate B, D013), a minimal provisional `PhysicsRule` (D013), attribution engine, pipeline orchestrator, multivariate IF detector.
  - **P2 SWaT DIAGNOSTICS: DIAGNOSTICALLY COMPLETE** (probes, not acceptance) — full campaign (normalization study, threshold sweep, root-cause screen, targeted diagnostics, IF hyperparameter grid) converged on **D012 signal coverage as the dominant demonstrated limitation** of the SWaT proxy validation. Normalization decision RESOLVED (per-window min-max confirmed, not changed). No further SWaT work planned unless explicitly requested — see `P2_RESUME.md` §3a.
  - **P2 FORMAL ACCEPTANCE: PARTIALLY done.** 7/11 attempted Doc06 scenarios PASS (D013 + the 2026-08-29 P2-ANOM-S1 addition); 4 FAIL with precisely diagnosed root causes; O3 structurally unreachable with the current minimal `PhysicsRule`. Full matrix + mandatory-blocker-vs-validation-limitation breakdown: `P2_RESUME.md` §1a/§7a.
  - **P3 hardware-free: PLUMBING + CONCRETE LSTM TWIN COMPLETE, integration-tested** (2026-08-31, local `main` `66f790e`, 2 commits ahead of pushed `origin/main`) — `DivergenceScorer` (D018 pt.1), `ElapsedTimeUncertaintyProxy` (D019), `SelfHealOrchestrator` wired to the existing `RelayController.safe_off()`, the P2→P3 adapter `process_isolated_channels` (`edge/pipeline/cycle.py`, takes `isolated_channels`/`raw_values` as REQUIRED caller-supplied inputs, never derives isolation from trust/band), and a concrete `LSTMTwinReconstructor` (`edge/models/lstm_twin.py` — single-layer unidirectional LSTM → final hidden state → Linear → scalar, `hidden_size` required no default) satisfying the unmodified `TwinReconstructor` Protocol, now integration-tested end-to-end with the orchestrator/adapter. `divergence_threshold`, `uncertainty_cap`, and the scaling formula remain required parameters/injectable seams — no values chosen (U05 unchanged). **No meaningful reconstruction accuracy or real-world validation is claimed** — the simulator's clean baseline has no cross-channel/temporal structure beyond each channel's own fitted mean. Prognosis/LSTM-health (blocked, D017), RL/DQN + its deterministic fallback (U06, FR-RL2/RL4 — also the still-missing source of *which* channels get isolated for real) are all NOT started.
  - **BLOCKED / PENDING (need Pi/rig — not faked):** **on-Pi LSTM+IF <500 ms** timing, **physical relay safe-stop**, and **physical sensor→DOM / under-load latency**. Real P2 accuracy validation (O2/O3/O4 on real sensors) is also gated here.
  - **P1 physical hardware: PARTIALLY VERIFIED (2026-09-07, commit `054caa681f5097c840ddb4764a8b1b40021e3b4e`).** Real drivers now exist and were each individually hardware-validated for all five physical-sensor channels — `edge/drivers/ina219.py` (current), `edge/drivers/dht22.py` (humidity), `edge/drivers/ds18b20.py` (temperature), `edge/drivers/adxl335.py` (vibration), `edge/drivers/bmp280.py` (pressure, replacing the originally-documented BMP180 per D027 — added `3e34bd1`, 2026-09-03, register map + Bosch compensation formulas validated against the physical sensor first via `edge/scripts/bmp280_hwtest.py`, `7285a2c`). Gas (MQ-135) remains the only channel with no driver at all. **Bench wiring has changed three times since the first ADXL335-only validation**: ADXL335 (vibration) and BMP280 (pressure) were briefly both wired in alongside each other (`d419d6b`, 2026-09-03), then DS18B20 (temperature) was added as a third real sensor (`adc2eb6`, 2026-09-04), then the bench was reconfigured down to DS18B20 as the sole physically-connected sensor (`8fa7363`, 2026-09-04, same day) — and then reconfigured a third time, back to **ADXL335 as the sole physically-connected sensor** (`054caa6`, 2026-09-07, this time via the config-driven registry's `_DEFAULT_CHANNEL_SPECS` table rather than a hand-edited import/construction block), which is the current state. `edge/main.py` is wired to match: `vibration` uses the real `ADXL335Driver`; `temperature`, `pressure`, `humidity`, `gas`, and `current` all use fake constants — temperature because DS18B20 is currently disconnected (not because its driver doesn't exist), pressure/humidity/current likewise for BMP280/DHT22/INA219, gas because no driver exists yet. **First real end-to-end MQTT telemetry confirmed** (2026-09-03, with ADXL335 as the then-sole real sensor): `PYTHONPATH=backend:. python edge/main.py` on the Pi publishes `shtapm/pump-01/telemetry` at 1 Hz with contiguous `sample_seq`, and the real `vibration` value visibly responded to physically handling the sensor (captured samples: 0.527 → 0.645 → 0.625 → 0.625 g) — full captured payloads in `IMPLEMENTATION_LOG.md`'s 2026-09-03 entry. **Re-confirmed on this third reconfiguration (2026-09-07, commit `054caa6`), and for the first time alongside a live `decision_diagnostic` MQTT stream** (the best-effort diagnostic publisher added earlier this session): both `shtapm/pump-01/telemetry` and `shtapm/pump-01/decision_diagnostic` published every second, `sample_seq` contiguous, `vibration` varying, `anomaly_flag=false`/`anomaly_severity=0.0` (expected `NullDetector` behavior, not a detection claim), `execution_mode=live`/`model_status=diagnostic_unvalidated` self-identifying correctly on real hardware — full detail in `IMPLEMENTATION_LOG.md`'s 2026-09-07 entry. Pump remained off throughout; no isolation, substitution, actuation, or self-healing was executed (observe-only path, unchanged). **No accuracy, calibration, or validation claim is made for ADXL335, P2's computations, or the decision_diagnostic payload's content** — only that the pipeline runs and publishes correctly end-to-end on real hardware. Neither P0 nor P1 is *fully* physically done until BMP280/INA219/DHT22/DS18B20 are reconnected alongside ADXL335 and a gas driver is implemented.
  - **P4 hardware-free: M1–M6 IMPLEMENTED + TESTED (2026-09-05, committed `3d6a715`)** — DB models/migration, auth (JWT+RBAC), telemetry persistence, REST API (Doc05 §05.7 minus `/inject`, U14-blocked), ledger hash-chain service + verify + export, WS auth/scoping. Deliberately NOT done in that slice: continuous aggregates/retention, DB-level RLS (app-level scoping instead), `health_state` rollup (no decision producer writes `decisions` with health data yet), the `system_health` WS push frame (REST poll only), Mosquitto broker config. **Since then (2026-09-06, commit `a241915`): a `decision_diagnostic` partial-ingestion path was added** — a new, separate `shtapm/{device_id}/decision_diagnostic` MQTT topic (NOT the frozen Doc05 `.../decision` topic/`DecisionMessage`), its own consumer/persistence sink, writing partial `decisions` rows (`anomaly_flag`/`anomaly_severity`/6 trust columns only; `health_state`/`failure_eta`/`rl_action`/`isolated_channels`/`substituted_channels`/`attribution`/`reason` stay `NULL`). `GET /api/devices/:id/decisions` needed no code change to expose these. Real ledger/status MQTT ingestion, and ingestion of an actual full `DecisionMessage`, remain NOT built. No live Postgres/Docker in this dev sandbox — migration is Postgres-only and unverified against a real database; unit tests use portable SQLite. Full detail: the "P4" section near the end of this file, `IMPLEMENTATION_LOG.md`, and `REPRODUCIBILITY.md`.

## Hardware-free E2E latency — VERIFIED (2026-08-10)
- Probe: `frontend/scripts/latency_probe.mjs` (no deps). Measures **simulator publish timestamp (`ts`) → WebSocket client receipt** — NOT physical sensor→DOM.
- **3 runs × 60 samples = 180 valid** (0 invalid/negative/discarded): p50 = **2 ms**, p95 = **3–5 ms**, max = **6–14 ms**.
- **PASS** vs PRD NFR-P1/AC6 `<2000 ms` (well under the <1s target).
- Unverified: physical sensor→DOM rendering and under-load (Aurora, real rig) latency — needs Pi/rig + headless browser.
- **Repository:** github.com/Yeshwanth-lb/SHTAPM (branch `main`; M1 d841404 … M3.5 8483283; CI-repair fab702b; offline-stack 75cef26; CA fixes c663ed6/6835b8e; port-remap/MQTT-retry/bind-fix committing now)

## Completed
- Requirements + design docs authored (`docs/` — PRD, TRD, App Flow, Aurora UI/UX, Backend Schema, Impl Plan).
- `CLAUDE.md` project instructions committed.
- Git repo initialized and pushed to GitHub.
- PRD ↔ Doc06 phase conflict identified and reconciled (see `DECISIONS.md` D001/D002).
- Reconciled implementation roadmap agreed (PRD phase authority; Doc06 = detailed task/test spec mapped into PRD phases).
- Project-state / handoff files created and committed (30b03ee).
- **P0 Milestone 1** (committed d841404) — monorepo skeleton (TRD §02.6); docker-compose (mosquitto+db functional, backend+frontend wired-empty behind `app` profile); `.env.example`; Python + frontend lint/test tooling + CI + pre-commit skeleton; self-hosted font foundation; `.gitignore` hardened; READMEs.
- **P0 Milestone 2** (committed e1f2e4a) — froze the canonical telemetry/decision/ledger contract per **D007** (Doc05 §05.8 authoritative). Pydantic v2 models in `backend/app/schemas/contracts.py`, mirrored TS in `frontend/src/types/contracts.ts`, accept/reject tests.
- **P0 Milestone 3.1** (committed 0b1c4dd) — hardware-free telemetry simulator in top-level `simulator/` (D005/D008): deterministic generator emitting the frozen contract + MQTT publisher to `shtapm/{device_id}/telemetry`. Fixed root pytest wiring so the whole suite runs in one command.
- **P0 Milestone 3.2** (committed aa1563c) — connected simulator → Mosquitto → subscriber verifier. Real round trip verified against `eclipse-mosquitto:2.0`.
- **P0 Milestone 3.3** (committed 4c578c5) — backend MQTT telemetry ingestion: consumer + `TelemetryStore` + FastAPI lifespan + `/healthz`.
- **P0 Milestone 3.4** (committed 728838f) — backend WebSocket fan-out: `app/ws/{frames,broadcaster,routes}.py` + consumer `add_sink` seam; `/ws` Doc05 §05.8 frames.
- **P0 Milestone 3.5** (uncommitted) — minimal React consumer: `frontend/src/{App,main}.tsx`, `hooks/useTelemetryWebSocket.ts`, `features/telemetry/TelemetryView.tsx`, `lib/ws.ts` + RTL tests; `scripts/ws_smoke.mjs`. Reuses frozen TS contract, plain React state, capped-backoff reconnect. MQTT→backend live-verified under uvicorn; WS-serving-to-client + RTL/build gated to CI (sandbox blocks — see below).

## P2 — hardware-free foundations (2026-08-10) — plumbing COMPLETE, validation NOT
All unit/interface-tested (math/shape/branch/plumbing only — NO detection/trust/attribution accuracy claim):
- **Beta trust core** (26de8c2) `edge/trust/beta.py` — signal-agnostic `BetaState` (α₀=β₀=1, `T=α/(α+β)`), documented weights 0.4/0.3/0.3, bands 0.7/0.4, `combine_g`. **λ=0.7 = PENDING U01 approval** (analyzed default, not a spec number).
- **Synthetic §12.4 injection framework** (ee730fe) `edge/injection/` — 7 hardware-free injections (drift/spike/stuck-at + bias-FDI/ramp-FDI/replay/constant-spoof) as pure stream transforms; magnitudes/durations REQUIRED args (no spec values); `dry-run` excluded (physical). Ground-truth labels are test/eval-only, not wire.
- **Anomaly foundation** (f75b9dc) `edge/anomaly/{preprocess,detector}.py` — documented pipeline (median→low-pass→30-window→per-window min-max; kernel/alpha required args, window_size default 30); `AnomalyDetector` protocol + `NullDetector` + internal `AnomalyResult`.
- **Trust-engine shell** (9479968) `edge/trust/engine.py` — one `BetaState` per channel, `SignalProvider` seam for c/k/h (NO definitions), per-channel independence.
- **Attribution-engine shell** (cbd7527) `edge/anomaly/attribution.py` — documented none/fault/attack branch logic over an injected `PhysicsRule` seam; reuses frozen `Attribution` enum (contract unchanged); NO physics equations.
- **Pipeline orchestrator** (d1ec0da) `edge/anomaly/pipeline.py` — frames→preprocess→detector→`ChannelFlagPolicy`→trust→attribution; internal `WindowOutcome` (no wire contract). `ChannelFlagPolicy` (window-level→per-channel bridge) is an injected seam, NOT implemented.
- **Multivariate Isolation Forest detector** (5a1af31) `edge/anomaly/iforest.py` — single sklearn IF over flattened 180-dim 30×6 window (D-A); empirical-CDF/rank severity on stored clean-baseline scores (D-B); `flag_threshold` a REQUIRED config param (no baked value); IF hyperparameters optional passthroughs; fixed `random_state` allowed. **scikit-learn dep**: `edge/requirements.txt` pins `scikit-learn==1.4.*`; the IF test module **skips in CI until sklearn is added to CI deps** (separate follow-up) — verified locally (sklearn present).

### P2 NOT done — explicitly pending (superseded 2026-08-26 — see D013 update below; kept for historical trace)
- ~~c/k/h signal definitions... UNDECIDED~~ — **RESOLVED (provisional), D009/D010, implemented since before this session.**
- ~~`ChannelFlagPolicy` localization... UNDECIDED~~ — **RESOLVED (provisional, redesigned "Candidate B"), D013.**
- ~~Real physics attribution rule... UNDECIDED~~ — **PARTIALLY RESOLVED (minimal, provisional, narrow scope), D013** — see below for what remains.
- **IF tuning** — still UNTUNED; dataset-gated (U07). SWaT diagnostics (2026-08-25) now show hyperparameter changes have limited upside even where real signal exists — see `P2_RESUME.md` §3a.
- ~~Dataset evaluation... access pending~~ — **DONE.** SWaT.A1 access granted, harness built, full diagnostic campaign run and diagnostically complete (`P2_RESUME.md` §3a). SWaT/WADI structurally cannot satisfy O3 regardless (D011).
- **P2 acceptance tests:** now actually run (D013 + the 2026-08-29
  P2-ANOM-S1 addition, `edge/tests/test_p2_acceptance.py`) — 7/11 attempted
  PASS, 4 FAIL (root causes precisely diagnosed). Full matrix: `P2_RESUME.md`
  §1a.
- **O3 (≥85% attribution accuracy)** — still NOT produced, and **structurally
  unreachable** with the current minimal `PhysicsRule` (only names
  current/vibration, ~50–60% reliable even there) — a mandatory
  implementation blocker (broader rule), not a tuning gap. **O10** still NOT
  produced (blocked on hardware, not software).
- **Authenticated scenario-injection hook (FR-A4)** — not started (command payload U14).

### P2 — D013 (2026-08-25, committed `1c784e5`): ChannelFlagPolicy redesign + minimal PhysicsRule + first acceptance suite
See `DECISIONS.md` D013 and `P2_RESUME.md` §1a/§3a/§7a for full detail. Summary:
- `ChannelFlagPolicy` redesigned ("Candidate B": per-channel, own-baseline,
  two-sided empirical-CDF test) — fixes the P2-ANOM-H2 spike-misdirection bug;
  improves P2-TRUST-H2's flag rate 5x (13%→68%) without fully resolving it.
- Minimal, provisional `PhysicsRule` (`TrendSignPhysicsRule`, reuses D010's
  `k` heuristic verbatim) implemented — unblocks `AttributionEngine`'s wiring
  path (previously fully non-functional). Narrow scope, ~50–60% reliable.
- First-ever formal P2 acceptance suite written and run: **6/10 PASS**
  (P2-ANOM-H2, H3\*, E2\*, P2-TRUST-E1/E2/S1; \*=fixture-sensitive, ~50–60%
  reliable, not validated), **4 FAIL** (P2-ANOM-H1/E1, P2-TRUST-H1/H2 — all
  precisely root-caused, all documented validation limitations not missing
  code), **1 not attempted** (P2-ANOM-S1, no adaptive injection type).
- **D009 (`h`/GAMMA), D010's `k` formula, D011, D012, and IF/`c`'s own
  behavior are all explicitly UNCHANGED** by D013.
- **Full `pytest edge/` (2026-08-25): 327 passed, 4 failed, 2 skipped** — zero
  regressions outside the 4 documented, expected failures.
- **Committed and pushed** — `edge/anomaly/{policy,physics_rule}.py`,
  `edge/tests/{test_policy,test_physics_rule,test_p2_acceptance}.py`,
  `edge/eval/swat_eval.py` (plumbing only) are all on `origin/main` as of
  `1c784e5` (verified 2026-08-29 — corrects the "UNCOMMITTED" note that stood
  here through 2026-08-26).

### P2 — P2-ANOM-S1 (2026-08-29): AdaptiveStealthFDI injection + acceptance scenario
See `P2_RESUME.md` §1a/§7a/§9 for full detail. Summary:
- New 8th §12.4 injection, `AdaptiveStealthFDI` (`edge/injection/injections.py`):
  bias ramps then holds at a caller-chosen `residual_cap`, unlike unbounded
  `Drift`/`RampFDI` or instant `BiasFDI`/`ConstantSpoof`.
- Its P2-ANOM-S1 scenario (`edge/tests/test_p2_acceptance.py`) verifies the
  injection provably stays under a test-local "naive residual" bound
  throughout, then asserts the real, UNMODIFIED pipeline's trust for that
  channel still drops below `TRUSTED_MIN` — **PASS**, driven by the existing
  `ConsistencyProvider` (`c`) reacting to a sustained per-sample bias that a
  window-variance-based check (IF/`ChannelFlagPolicy`) does not; `channel_flags`
  never fires in this scenario. Verified at the committed fixture
  seed/parameters only — not multi-seed stress-tested.
- P2 acceptance now stands at **7/11 attempted PASS** (up from 6/10).
- **D009, D010, D011, D012, D013, and every existing IF/preprocessing/c/k/h/
  ChannelFlagPolicy/PhysicsRule behavior are explicitly UNCHANGED** — only a
  new injection type and its test were added.
- **Full `pytest edge/` (2026-08-29): 332 passed, 4 failed (same 4
  pre-existing, documented failures), 2 skipped** — zero regressions.
- **Committed and pushed (2026-08-30)** — `docs: correct D013 project state
  documentation` (`ea437c6`) and `feat: add AdaptiveStealthFDI injection`
  (`b82f935`); `main` and `origin/main` are identical at `b82f935`.

### P2 — D014 (2026-08-30): broader-`PhysicsRule` scoping decision, no expansion
See `DECISIONS.md` D014 and `P2_RESUME.md` §5/§7/§7a for full detail. Summary:
- Scoping review of the four channels `TrendSignPhysicsRule` (D013) doesn't
  cover — `temperature`, `pressure`, `humidity`, `gas`. Conclusion: **no new
  channel coverage added**; `TrendSignPhysicsRule` is unchanged.
- `pressure` REJECTED — would reopen D010's already-recorded finding that
  BMP180 reads atmospheric pressure only, not water-line/discharge pressure.
- `humidity` REJECTED — the PRD's own "Design integrity note" (§12) and risk
  R6 explicitly require temperature/humidity to stay uncorrelated in the
  trust engine.
- `gas` REJECTED — no documented mechanical/electrical/thermal linkage to
  any other channel exists anywhere in the PRD/TRD.
- `current`↔`temperature` DEFERRED as the sole future candidate — physically
  plausible (I²R heating under load) and not PRD-forbidden, but no
  coefficient/lag/threshold is documented anywhere and no bench data has
  been collected. Gated on real bench hardware, not available here.
- **D009, D010, D011, D012, D013, and `AttributionEngine`'s single-
  `PhysicsRule` architecture are all explicitly UNCHANGED.** No code was
  modified by this decision — documentation-only.
- **O3 (≥85% attribution accuracy) remains structurally unreachable** — this
  decision does not change that and was never intended to.

### P2 — D015 (2026-08-30): P2-TRUST-H2 root cause established, D009/D010 unchanged
See `DECISIONS.md` D015 and `P2_RESUME.md` §1a/§6/§7/§7a for full detail. Summary:
- Read-only diagnostic replay (this pass, not committed) established that
  P2-TRUST-H2's gap is **not primarily `h`'s GAMMA speed**: the committed
  test uses `ConstantSpoof`, whose flat/zero trend leaves `k=1.0` the whole
  time (D010's non-paired-channel default, compounded by a documented
  flat-trend blind spot in the trend-sign rule) — this alone structurally
  floors `g` at 0.3, independent of `h`.
- Confirmed by replaying the scenario with `h` hypothetically collapsed to 0
  instantly (i.e. GAMMA/D009 entirely removed): trust still does not cross
  0.4 until window 5 after onset, not window 3. Only when `k` is *also*
  hypothetically forced to 0 does the trace reproduce D009's own
  approval-trail arithmetic (`T_3=λ³=0.343<0.4`) at exactly window 3 —
  meaning that arithmetic was implicitly valid only for an attack/channel
  combination where `g` can reach 0, which a flat spoof under D010's
  current `k` rule never allows, on any channel.
- **Decision (Option A): D009 and D010 both left unchanged.** P2-TRUST-H2
  is formally documented as a structural limitation, not fixed.
  P2-TRUST-S1's collusion resistance (the entire reason D009's GAMMA is
  slow) is fully preserved.
- **P2-TRUST-H2 remains FAIL. O4/AC2 is NOT claimed satisfied.** No code
  or test was changed — documentation-only.

### P3 — hardware-free self-healing plumbing (2026-08-31, committed + pushed `8cc5564`)
Implements the smallest hardware-free slice `DECISIONS.md` D016–D019
authorize: digital twin -> elapsed-time uncertainty proxy -> substitution
-> z-score divergence backstop -> existing Safe Pump-Stop interface. No new
decision was created by this work. Summary:
- `edge/models/twin.py` — `TwinReconstructor` Protocol (digital-twin
  reconstruction seam, D016). **Protocol-only, no production
  implementation** — D016 specifies no architecture/hyperparameters and
  none was authorized for this slice. Docstring explicitly warns future
  implementations not to read `window.features[missing_channel]` (would
  collapse the divergence backstop to near-zero).
- `edge/pipeline/divergence.py` — `DivergenceScorer`: fit-time z-score of
  the twin-vs-isolated-sensor residual (D018 pt.1's approved form).
  `divergence_threshold` is a REQUIRED caller parameter — NOT chosen, still
  data-gated (U05).
- `edge/pipeline/uncertainty.py` — `ElapsedTimeUncertaintyProxy`: D019's
  deterministic elapsed-substitution-time method. The elapsed→uncertainty
  scaling formula is a required, never-defaulted injected seam — NOT
  chosen (D019, still open; no functional form is constrained by any doc).
- `edge/pipeline/self_heal.py` — `SelfHealOrchestrator`: wires the above to
  D018's behavioral rules (recovery at reused `TRUSTED_MIN`; the existing
  Doc05-documented `substitution_max_seconds=60` default reused as a single
  named, overridable constant — not duplicated/hardcoded elsewhere; cycle
  sequencing after P2) and to the existing `RelayController.safe_off()`
  Safe Pump-Stop interface. `uncertainty_cap` is a REQUIRED caller
  parameter — NOT chosen (U05, still open; noted in the prior scoping
  analysis as policy-decidable rather than data-gated, but not decided
  here). The three signals (divergence, elapsed time, uncertainty) are
  kept independent by construction — none of the three comparisons gates
  another's computation.
- Implementation went through a dedicated plan → build → strict code
  review → pre-commit fix pass: the review found no specification
  violation and no active bug, and flagged two design concerns since
  addressed (the twin-masking docstring warning above, and missing
  `__init__.py` in the two new packages) plus test-coverage gaps (exact
  threshold/cap equality, simultaneous divergence+expiry, repeated
  escalation) closed with 4 additional tests.
- 38 tests total (`edge/tests/test_divergence.py`,
  `test_uncertainty.py`, `test_self_heal.py`), all fixture values
  explicitly labelled `*_FIXTURE` and never presented as specification.
- **Full `edge/` suite (2026-08-31): 343 passed, 4 failed (the same 4
  pre-existing P2 failures — P2-ANOM-H1/E1, P2-TRUST-H1/H2, unrelated to
  this change), 2 skipped** — zero regressions.
- **No `DecisionMessage`, simulator, or P2-internal file modified.** No new
  `D0XX` decision created — this is implementation of already-approved
  D016–D019, not a new specification.
- **Committed and pushed** — `feat: add hardware-free P3 self-healing
  plumbing` (`8cc5564`); `main`/`origin/main` identical, verified
  (`git rev-list --left-right --count` = `0 0`).
- **Still open / NOT done by this slice:** `divergence_threshold` and
  `uncertainty_cap` numeric values (U05), the elapsed-time→uncertainty
  scaling formula (D019), any production digital-twin (D016 authorizes no
  architecture), prognosis/LSTM (D017, blocked on a degradation-data
  source), RL/DQN (U06), and the P2→P3 cycle-wiring glue (which channels
  actually get passed to `SelfHealOrchestrator` each cycle is not yet
  built). **Superseded below** — the cycle-wiring glue and a concrete
  digital-twin were both since implemented; re-read the two sections
  immediately following this one for the current state of each claim.

### P3 — P2→P3 cycle adapter + hardening (2026-08-31, committed + pushed `fe4042e`, `0cc4d31`)
A read-only scoping pass first established that P2 exposes no
isolation-state object anywhere in this repo, and that FR-RL2 makes
isolation an RL-agent action ("Isolate Sensor") whose agent and
deterministic fallback (FR-RL4) are both unbuilt — so the adapter was
scoped to take isolation as an explicit, required input rather than
inventing a trust/band-derived rule. Summary:
- `edge/pipeline/cycle.py` — `process_isolated_channels(outcome,
  isolated_channels, raw_values, orchestrator)`: wires an existing P2
  `WindowOutcome` into `SelfHealOrchestrator`, processing only the
  channels the caller explicitly names. `isolated_channels` and
  `raw_values` are REQUIRED, no default, never derived from
  `outcome.trust`/`TrustBand`. Validates every named channel against
  `outcome.trust`/`raw_values` **before** acting on any of them
  (two-pass), so one invalid/missing entry cannot trigger a real side
  effect — including a Safe Pump-Stop — for a different, valid channel
  named in the same call.
- Hardening pass (`0cc4d31`) closed four review gaps: multi-channel
  isolation tests for both `SelfHealOrchestrator` and
  `process_isolated_channels` (proving per-channel episode/divergence
  state doesn't cross-contaminate), a discriminating low-trust
  pass-through test (closing a false-positive gap in an
  only-tested-with-high-trust test), and the validate-all-upfront change
  above plus its zero-side-effect proof test.
- **9 + 5 = 14 new tests**; full P3 suite reached **52 passed** at this
  point. `edge/anomaly/pipeline.py`, `edge/trust/*`, `contracts.py`,
  `simulator/`, `edge/actuation/*`, and `edge/pipeline/self_heal.py` were
  never modified — only imported from.
- **Still open:** exactly what fed `isolated_channels` for real — nothing
  in this repo decides which channels are isolated; that remains an
  RL-agent action (FR-RL2) or its deterministic fallback (FR-RL4), both
  unbuilt. The adapter is tested only with explicit test-fixture isolated
  sets.

### P3 — hardware-free LSTM digital twin + integration tests (2026-08-31, committed + pushed `43e114d`, `66f790e`)
A digital-twin architecture scoping pass established that FR-H2 ("LSTM
digital-twin") plus the frozen TRD §02.2 stack ("PyTorch (LSTM)") make
LSTM a binding architecture family, while D016 leaves every hyperparameter
open, and that the existing D005/D008 simulator's clean baseline has no
cross-channel or temporal structure beyond each channel's own fitted mean
— so nothing trained against it can establish meaningful reconstruction
accuracy, only that the ML plumbing works. Summary:
- `edge/models/lstm_twin.py` — `LSTMTwinReconstructor` / `_LSTMTwinNet`:
  the approved smallest architecture exactly — single-layer, unidirectional
  PyTorch LSTM → final hidden state → Linear → one scalar. `hidden_size`
  is REQUIRED, no default anywhere (D016 specifies no layer
  sizes/hyperparameters). `build_masked_input` zeroes the missing
  channel's six-wide value slot **without ever reading it** (structurally,
  not just zeroing after reading) and concatenates a one-hot
  missing-channel indicator, repeated at every timestep, over the existing
  30-timestep window. Satisfies the existing, unmodified
  `TwinReconstructor` Protocol. `save`/`from_checkpoint` use
  `torch.save`/`torch.load(weights_only=True)` (state-dict only, no
  arbitrary-object unpickling); no checkpoint is committed to the repo.
- `edge/eval/twin_training.py` — diagnostic-only self-supervised
  training harness (same "probes, not acceptance" status as
  `if_eval.py`/`swat_eval.py`): masks every channel of every clean-baseline
  window from the existing simulator + `Preprocessor` (no injections, no
  new simulator/preprocessing capability), MSE loss against the true
  masked value. `epochs` and `optimizer` are REQUIRED arguments with no
  default — the optimizer is never constructed inside the training
  function; every diagnostic Adam instantiation is bound to a
  locally-named `ADAM_OPTIMIZER_FIXTURE`, explicitly not an approved
  project optimizer choice. Activates the already-frozen `torch==2.2.*`
  pin in `edge/requirements.txt` (no other dependency changed).
- Two integration tests (`66f790e`) then proved the **real**
  `LSTMTwinReconstructor` (not a fixture stub) conforms to
  `TwinReconstructor` and produces a well-formed `SelfHealOutcome` when
  driven directly through `SelfHealOrchestrator.process_isolated_channel`
  and through the full `WindowOutcome -> process_isolated_channels ->
  SelfHealOrchestrator` chain. Both assert only well-formedness
  (types/finiteness), never a specific reconstruction value or
  escalate/no-escalate branch, since the network is untrained/arbitrarily
  initialized.
- Both increments went through a dedicated plan → build → strict review →
  approved fix pass each. **14 + 2 = 16 new tests**; full P3 suite reached
  **68 passed**. Full relevant `edge/` suite: 371→ same 4 pre-existing P2
  failures throughout, zero regressions introduced by any P3 work this
  session.
- **No `DecisionMessage`, P2 internals, trust, actuation, simulator, or
  existing P3 production code modified. No new `D0XX` decision created.**
  `divergence_threshold`, `uncertainty_cap`, and the scaling formula
  remain exactly as open as before this work — nothing about implementing
  the twin required or implied any of the three.
- **Still open / NOT done:** any claim of meaningful reconstruction
  accuracy (data-gated, and the simulator itself cannot supply the needed
  structure even synthetically); `divergence_threshold`, `uncertainty_cap`,
  the scaling formula (U05/D019); prognosis (D017); RL/DQN + fallback and
  the real isolation-decision source (U06, FR-RL2/RL4); a real P2→P3
  cycle caller that determines `isolated_channels` on its own.
- **Committed, NOT yet pushed** — `43e114d` (LSTM twin) and `66f790e`
  (integration tests) sit on local `main`, 2 commits ahead of
  `origin/main` (which still ends at `0cc4d31`).

## P2 diagnostics (2026-08-10) — behaviour probes, NOT acceptance (commit d17942f)
Diagnostic-only tooling under `edge/eval/` (not on pytest `testpaths`, not in the production pipeline; scikit-learn-gated tests). All magnitudes + flag threshold are EVALUATION FIXTURES, not project specs. **No P2 acceptance criterion is claimed passed.**
- **IF behaviour probe** (`edge/eval/if_eval.py`) — real `IsolationForestDetector` on the simulator + the 7 §12.4 injections. Finding: **clean-vs-clean false-positive rate ≈ 21.6%** at the eval-fixture threshold 0.95 → per-window min-max on the simulator's structureless independent-noise windows does not calibrate tightly; "detected" flags sit on that FP floor and are not reliable separation.
- **Preprocessing comparison** (`edge/eval/preproc_experiment.py`) — per-window min-max (A, current) vs train-fit global min-max (B) vs train-fit z-score (C), all feeding the UNCHANGED detector:
  - clean FP: **A 0.216 · B 0.035 · C 0.041** (B/C ≈ ideal ~5% for a 0.95 threshold).
  - **per-window min-max washes out constant additive bias** within a fully-injected window (bias_fdi inside 0.989 ≈ clean, A) → B/C preserve it (inside 1.000, flagged).
  - **constant-spoof under A "detects" as a normalization flatness artifact** (flat channel → all-zeros), NOT cross-sensor spoof detection; B/C correctly do NOT detect a plausible constant near the mean (inside 0.79/0.81 < 0.95) — the honest limitation: a plausible constant spoof needs **cross-sensor physics**.
  - New risk of B/C: they assume **stationarity** (train-fit params) → would flag legitimate operating-point drift on real signals; the stationary, physics-free simulator structurally favours global normalization and cannot show per-window's robustness.
- **Decision:** **normalization choice DEFERRED to real SWaT/WADI/TEP evaluation (U07).** No production preprocessing/detector/pipeline change approved or made. FR-P1 "min-max normalize" does not mandate per-window vs global — both remain doc-compatible.
- **Reproduce:** `PYTHONPATH=backend:. python -m edge.eval.if_eval` · `… -m edge.eval.preproc_experiment`.

## In progress
- P2: foundations, SWaT diagnostics, D013's formal acceptance pass, the
  2026-08-29 P2-ANOM-S1 addition, the D014 broader-`PhysicsRule` scoping
  decision, and the D015 P2-TRUST-H2 scoping decision are all complete.
  D013 and P2-ANOM-S1 are committed and pushed (`main`/`origin/main` at
  `b82f935`); D014 and D015 are documentation-only decisions (no code).
  Remaining work is now down to one mandatory implementation blocker — real
  bench hardware — plus the two documented validation limitations still
  genuinely open: `c`'s rank-based noise (P2-TRUST-H1) and IF/normalization
  (P2-ANOM-H1/E1) — see `P2_RESUME.md` §7a.
- P3: U03/U04/D018/D019 scoping, the U05 readiness analysis, the
  implementation plan, the hardware-free plumbing slice (`8cc5564`, pushed),
  the P2→P3 cycle adapter + hardening (`fe4042e`/`0cc4d31`, pushed), and
  the LSTM digital twin + its integration tests (`43e114d`/`66f790e`,
  **committed, NOT yet pushed**) are all complete — see the P3 sections
  above. Remaining P3 work is genuinely open, not merely undocumented: the
  two numeric values (U05), the scaling formula (D019), meaningful
  reconstruction-accuracy validation (data-gated, and the simulator itself
  can't supply it), prognosis (D017), and RL/DQN + fallback + the real
  isolation-decision source (U06).

## Next
**Not assumed to be coding — read `P2_RESUME.md` §10–§14 first.**
Hardware-free P2 has no remaining mandatory software implementation (its 4
documented FAILs are all hardware/data-blocked or decision-required
limitations, not missing code — none are fixable by more coding without
either real bench data or a new specification decision touching `c`, `k`'s
non-paired default, or GAMMA). For P3, **U03/U04 are resolved**
(`DECISIONS.md` D016/D017 — separate channel-agnostic digital-twin model;
synthetic data approved for initial hardware-free twin development only,
not validation), **the divergence/substitution behavioral design is
resolved** (`DECISIONS.md` D018 — twin-vs-isolated-sensor backstop
semantics, z-score divergence form, `TRUSTED_MIN`-based recovery, 60s
expiry→Safe-Stop, edge-internal uncertainty with no `DecisionMessage`
change, P2-then-P3 sequencing), and **the uncertainty-estimation method is
resolved provisionally** (`DECISIONS.md` D019 — deterministic
elapsed-substitution-time proxy, single-signal, safety/confidence proxy
NOT a calibrated error estimate). As of 2026-08-31, D016–D019 are all
recorded and the hardware-free plumbing they authorize is now fully
implemented and integration-tested: `DivergenceScorer`,
`ElapsedTimeUncertaintyProxy`, `SelfHealOrchestrator`, the
`process_isolated_channels` P2→P3 adapter, and a concrete
`LSTMTwinReconstructor` satisfying the unmodified `TwinReconstructor`
Protocol — see the P3 sections above for full detail.
**`DECISIONS.md` D020 (2026-08-31, documentation-only) resolved
`uncertainty_cap` (0.8, in the proxy's own output domain) and the
elapsed-time→uncertainty scaling formula (linear, `f(x)=x`, output domain
[0,1] now a specification requirement) — both as policy decisions, since
D019's proxy was never a calibrated error estimate and no bench data would
have resolved either. Both remain required, never-defaulted constructor
arguments in code; no default was added anywhere.** **U05 now narrows to
exactly one remaining item: `divergence_threshold`'s numeric value**,
still fully data-gated (needs real reconstruction-error and
fault/attack-separation statistics); U06 remains open; **no meaningful
reconstruction accuracy has been validated** — the simulator's clean
baseline structurally cannot supply the cross-channel/temporal signal
needed, so no amount of further hardware-free training changes that.
Nothing in this repo yet decides *which* channels are isolated for real —
FR-RL2 makes that an RL-agent action, and both the agent and its
deterministic fallback (FR-RL4) remain unbuilt; `process_isolated_channels`
is exercised only with test-fixture isolated sets. An untrained prognosis
architecture skeleton now exists (`edge/models/lstm_prognosis.py`,
`9f802df`); `DECISIONS.md` D021 (2026-08-31) adopted PRONOSTIA/FEMTO
(acquired + inspected read-only, scratchpad-only) as an external
vibration+temperature methodology-validation dataset only; `DECISIONS.md`
D022 (2026-08-31) then resolved the temperature-downsampling method
(1-second block mean), the vibration-burst-summary statistic (RMS of
Euclidean magnitude), and a missing-vibration `vibration_observed`
indicator (widening the future input contract to `len(CHANNELS)+1`, LSTM
shape unchanged). A preprocessing/loader layer implementing D022 now
exists (`edge/eval/pronostia_prep.py`/`test_pronostia_prep.py`, 20 tests,
**not yet committed** — still untracked). Real-data testing against all 17
bearings, followed by a full read-only audit, found genuine raw-data
quality problems (5 bearings with zero temperature files; 11 bearings with
leading-edge vibration bursts before temperature coverage begins; `Bearing1_1`'s
2 corrupted-timestamp files). `DECISIONS.md` D023 (2026-08-31) then
authorized three purely subtractive treatments for exactly these findings
(exclude the 5 zero-temperature bearings; a general leading-edge-burst-
trimming rule; a `Bearing1_1`-only exclusion of its 2 named corrupted
files, explicitly not a general corruption-detection capability) — no
fabrication/interpolation/reconstruction of any kind authorized, no bearing
changes split membership, expecting 12/17 bearings loadable (4 training + 8
test) once implemented. **The three D023 treatments were subsequently
implemented and verified against the real dataset**: `edge/eval/
pronostia_prep.py` now loads exactly 12/17 real bearings (4/6 training,
8/11 test), matching the audit exactly. `DECISIONS.md` D024 (2026-08-31)
authorized the eventual four-channel availability-indicator representation
for pressure/humidity/gas/current (Option B, per-channel, `0.0`
placeholders + explicit per-timestep availability indicators, extending
D022's `vibration_observed` mechanism) — establishing the eventual
resulting prognosis input width as 11. **This widening was subsequently
implemented and committed** (`edge/models/lstm_prognosis.py`, `8b7aa6c`:
`build_prognosis_input`, `PROGNOSIS_INPUT_WIDTH_D024=11`), and the
PRONOSTIA-to-prognosis glue layer was implemented and committed
(`edge/eval/pronostia_prognosis_input.py`, `c425de0`,
`pronostia_sequence_to_prognosis_input`) — both real, tested code, no
training performed. `DECISIONS.md` D025 (2026-08-31) then established the
RUL/HealthState target-generation methodology (training-bearings-only RUL
in seconds, proportional HealthState bands). A series of read-only
investigations of the 4 training bearings' vibration-RMS trajectories
followed (baseline-window/statistic/dispersion sensitivity, degradation-
metric comparison, temporal-stability characterization, operating-
condition dependency, final decision-readiness assessment) — all
concluded D025's methodology should be kept, and that the two remaining
numeric proportions should be adopted as explicit policy rather than
claimed as empirically derived, given n=4 and the genuinely inconsistent
Warning-onset timing found across bearings. `DECISIONS.md` D026
(2026-08-31) then recorded those two numbers: Healthy = RUL > 20% of
lifetime, Warning = 5% < RUL <= 20%, Critical = RUL <= 5% — both
explicit policy, 5% loosely qualitatively informed by the investigation,
20% with no empirical support at all. **HealthState methodology AND
numeric thresholds are both now resolved on paper, and target-generation
code implementing D025/D026 now exists and is tested** (`compute_prognosis_targets`,
`edge/eval/pronostia_prognosis_targets.py`).

**Since then: a training harness was implemented** (`edge/eval/pronostia_prognosis_training.py`,
`68addbb`) — 30-sample sliding windows (stride=1, matching P2's own
documented window-size precedent; target = each window's final-timestep
RUL/HealthState, the only interpretation compatible with
`_LSTMPrognosisNet`'s existing final-hidden-state forward path), leave-
one-bearing-out cross-validation across the 4 D025 training bearings
(zero sample-level overlap, fresh network per fold), CrossEntropy +
per-bearing-normalized-RUL MSE multi-task loss, and full HealthState/RUL
evaluation metrics. Window size/stride/loss/optimizer-interface are
documented, implementation-level choices in the module's own docstring —
not DECISIONS.md entries (resolvable by repository precedent/standard
practice, not irreversible policy calls).

**Then it was actually run against the real, already-downloaded PRONOSTIA
dataset** (session scratchpad, never committed). The first run (unweighted
loss, 3 epochs, hidden_size=16) collapsed to always predicting the
majority HealthState class in every fold (macro F1 ~0.30, zero recall on
Warning/Critical) — 80% "accuracy" was purely the Healthy-class base rate,
not real learning. Increasing epochs alone did not help (identical
predictions regardless of hidden_size/epochs), which ruled out "just needs
more training" and pointed at a structural issue. A forward-pass-only
diagnostic (no training) confirmed the cause: raw, unnormalized channel
values (Bearing1_1's temperature spans 70→164°C over its lifetime) were
saturating the LSTM's gates so severely that even a **fresh, untrained**
network's output barely varied across the entire bearing lifespan.
**Fixed (`983eb04`)**: `compute_channel_stats()`/`normalize_examples()`
(per-raw-channel z-score standardization; the D022/D024 availability
indicator columns are never normalized) and `class_weights()` (inverse-
frequency `CrossEntropyLoss` weighting for D026's real ~80/15/5 class
split) — both fit from training-split examples only, per fold, mirroring
D025's own leakage discipline; wired into `run_leave_one_bearing_out` as
opt-out defaults. Re-running (class-weighted + normalized, 15 epochs,
hidden_size=32) confirmed the collapse is gone — all three HealthState
classes are now genuinely predicted in every fold. **Cross-bearing
generalization is still inconsistent**: 1 of 4 folds (Bearing1_2 held out)
reaches macro F1 ~0.59 with strong Healthy/Critical recall; the other 3
folds are weak (macro F1 0.30–0.38), and Warning recall is 0.0 in 2 of 4
folds. This is consistent with — not contradicted by — this session's own
earlier finding that Bearing1_1 and Bearing1_2 (same nominal operating
condition) have substantially different degradation trajectories: with
only 4 bearings and one held out per fold, generalizing to an unseen
bearing's possibly-dissimilar degradation shape is a genuine small-sample
limitation, not a remaining code defect. **No claim of a validated or
production-ready prognosis model is made anywhere in this work** — this
run's purpose was to prove the pipeline (windowing → training → LOBO →
metrics) works correctly end-to-end on real data, which it now does.

Real pump/bench validation remains required regardless — PRONOSTIA stays
D021's methodology-validation-only proxy, never pump ground truth. The
next session should explicitly ask the user whether to: (a) once real
hardware/bench data exists (hardware setup planned next), retune P2's
Isolation Forest against real clean-baseline data (U07) and resolve
`divergence_threshold` (U05), (b) scope U06 (RL reward shaping) — the
sole blocker on the DQN agent, not hardware-dependent, could happen
anytime, (c) resolve one of the standing P2 decision-required items
(λ=0.7 sign-off/U01, `c`'s redefinition, FR-A4's payload/U14), (d) once
real pump data exists, retrain prognosis on it using the now-implemented,
now-debugged `edge/eval/pronostia_prognosis_training.py` harness, or
(e) something else entirely. Do not default to further P3 implementation,
and do not create a new decision without the same propose-then-approve
sequence used for D014–D026. P2 work otherwise remains blocked on
real bench hardware (also the only path that could unblock D014's deferred
current↔temperature candidate).

**Since then, `DECISIONS.md` D027 (2026-08-31, documentation-only) approved
two physical hardware substitutions** for the hardware actually in hand:
**BMP280 replaces the documented BMP180** for the Pressure channel (same
atmospheric-pressure-proxy semantics already established by D010/D014 —
never water-line/discharge pressure; BMP180 and BMP280 are NOT register-
compatible, so any future driver targets BMP280's own register map, not a
BMP180 implementation) and **Raspberry Pi 5 replaces the documented
Raspberry Pi 4** as the edge node (existing architecture/interfaces
preserved; Pi 5's GPIO access requires a `gpiozero` `lgpio` pin factory
instead of `RPi.GPIO`, not yet physically verified). The six logical
telemetry channels — names, order, and the remaining four physical parts
(DS18B20, ADXL335, DHT22, MQ-135) plus MCP3008/INA219 — are entirely
unchanged. **D010 and D014's own historical text is untouched** — D027
documents the substitution as a new, separate entry, not a retroactive
edit of either. `docs/SHTAPM_PRD-4.md` and `docs/SHTAPM_Doc02_TRD.md`
remain exactly as originally written (still naming BMP180/Raspberry Pi 4)
— D027 is the authoritative current-hardware record, layered on top of,
not overwriting, the original planning documents. **No driver code,
hardware wiring, or physical verification has occurred** — the P0/P1
hardware-blocked spikes remain exactly as blocked as before, now simply
targeting BMP280/Pi 5 instead of BMP180/Pi 4.

## Environment gates (honest — sandbox limits, not code failures)
- **Docker image builds** (backend `pip`, frontend `npm`) fail cert-verify inside the build (gateway MITMs TLS; base images lack its CA). So the full four-service `up` can't be built here. Dockerfiles are standard/correct — no insecure workarounds added; they build on CI / a normal machine (frontend build already green in CI).
- Real uvicorn **WS serving to an external client** returns HTTP 403 in this sandbox (localhost `Upgrade` interception); app-level WS proven via Starlette TestClient (M3.4). Works under normal serving/CI.
- `npm install` blocked locally → no lockfile; RTL/`tsc`/`vite build` verified in CI.
- To verify the full stack + browser render, run on a machine without the TLS interception:
  `cp .env.example .env` → set `POSTGRES_PASSWORD` → `docker compose up --build` → open `http://localhost:5173`, `curl http://localhost:8002/healthz`, and run the host simulator (README). (Backend host port is 8002 → container 8000; browser WS = `ws://localhost:8002/ws`, baked via compose build.args.)
- Note: integration tests need a broker + paho-mqtt; they self-skip otherwise. Backend runtime now needs fastapi/paho (`backend/requirements.txt`); tests need httpx (dev extra). Docker daemon started to verify; quit Docker Desktop if unwanted.
- P0 gate: clean offline `docker compose up` + go/no-go.
- Hardware spikes (sensor/interface reads, INA219, on-Pi LSTM+IF timing) stay **hardware-blocked** until a Pi/rig is available (`TODO.md`).

## Contract authority (frozen — read before touching any message)
- **D007:** Doc05 §05.8 is authoritative for wire field names/shapes. Full channel names; flat `isolated[]`/`substituted[]`; ledger keeps `payload_hash`; `type` is a WS-envelope concern only (MQTT payloads omit it). Canonical Python = `backend/app/schemas/contracts.py`; TS mirror MUST stay in sync.
- **U14:** `…/command` inject payload is unspecified — do not invent; blocks P4 injection.

## Standing caveats (honest state)
- Fonts (M1): foundation only — woff2 binaries + `@fontsource` pin deferred to P5.
- Local tooling gaps in this env: linters (ruff/black/eslint) and TypeScript are NOT installed; npm is blocked by a TLS/proxy cert error. Python tests run via an isolated venv; ruff/black/eslint/tsc/vitest execute in CI. Do not claim they ran locally.
- `docker compose config` validated; full `docker compose up` on a clean machine not yet run (P0 gate, later milestone).

## Known blockers
Blocking questions are tracked in the roadmap discussion; the ones that gate *code* (not yet resolved — DO NOT silently assume):
- P2: Beta math IMPLEMENTED (signal-agnostic core, 26de8c2) with λ=0.7 **pending U01 approval** (unchanged); `c`/`k`/`h` are RESOLVED (provisional, D009/D010) — `c`'s rank-based noise (P2-TRUST-H1) remains an open question, **not an implementation bug**: analysis (2026-08-30, documentation-only, `P2_RESUME.md` §7a) found `c` shares its empirical-CDF-rank scoring architecture with `IsolationForestDetector.score()` (P2-ANOM-H1/E1) and is already at its Uniform(0,1) theoretical floor on clean data regardless of fit-corpus size — unlike ANOM-H1/E1 (which has a measurable, unimplemented, simulator-only fit-corpus-size improvement available), TRUST-H1 has no fix without redefining `c` itself. **P2-TRUST-H2's root cause RESOLVED (as a decision, not a fix) by D015 (2026-08-30)**: not primarily `h`'s GAMMA speed — `ConstantSpoof`'s flat trend leaves `k=1.0` (D010's non-paired-channel default) the whole time, structurally flooring `g` at 0.3 independent of `h`; diagnostic replay confirmed removing GAMMA entirely still misses the 3-window budget. `D009`/`D010` both left unchanged; P2-TRUST-S1's collusion resistance preserved; **H2 remains FAIL, O4/AC2 NOT satisfied**.
- P2: fault-vs-attack physics/correlation attribution RULE — a minimal, provisional `PhysicsRule` now exists (D013, `TrendSignPhysicsRule`), unblocking `AttributionEngine`'s wiring; still only ever names current/vibration, ~50–60% reliable even there. **Broadening scope RESOLVED (as a decision) by D014 (2026-08-30)**: `pressure`/`humidity`/`gas` REJECTED (D010 conflict / PRD design-integrity note / no documented basis); `current`↔`temperature` DEFERRED as the sole future candidate, gated on real bench data that doesn't exist yet. O3 remains structurally unreachable regardless.
- P2: `ChannelFlagPolicy` (window-level IF → per-channel flags) RESOLVED (provisional, redesigned "Candidate B", D013) — per-channel own-baseline two-sided test, no longer cross-channel. Still U07-gated for real-data `tail_fraction` tuning.
- P2: IF hyperparameters + flag threshold UNTUNED — dataset-gated; SWaT diagnostics (2026-08-25) now show hyperparameter changes have limited upside even where real signal exists (`P2_RESUME.md` §3a).
- P2/P7: SWaT.A1 access GRANTED, harness built, full diagnostic campaign run and **diagnostically complete** — gates all P2 detection/attribution/trust real-data ACCEPTANCE and O3/O10 metrics regardless, since SWaT/WADI structurally cannot satisfy O3 or the literal six-channel semantics (D011). Real accuracy validation now needs bench hardware, not more dataset work.
- P2: P2-ANOM-S1 (adaptive/stealth injection type) — **RESOLVED (2026-08-29)**: `AdaptiveStealthFDI` implemented (`edge/injection/injections.py`) and its acceptance scenario PASSES; verified at the committed fixture seed/parameters only, not multi-seed stress-tested.
- P3: LSTM — one shared model or two? **RESOLVED (2026-08-31, `DECISIONS.md` D016)**: two separate models (prognosis; digital-twin), twin is a single channel-agnostic model, not per-channel. No architecture/hyperparameter detail specified. **A concrete `LSTMTwinReconstructor` now exists** (`edge/models/lstm_twin.py`, `43e114d`, 2026-08-31): single-layer, unidirectional LSTM → final hidden state → Linear → scalar (the approved architecture shape); `hidden_size` remains REQUIRED, no default (D016 specifies no hyperparameters). Satisfies the unmodified `TwinReconstructor` Protocol; integration-tested with `SelfHealOrchestrator`/`process_isolated_channels` at `66f790e`. **No meaningful reconstruction accuracy or real-world validation is claimed.**
- P3: digital-twin training-data source. **RESOLVED for initial dev only (2026-08-31, `DECISIONS.md` D017)**: synthetic (D005/D008 simulator + P2 injection framework) approved for hardware-free digital-twin development/testing — explicitly NOT claimed sufficient/validated for real-world reconstruction accuracy. **A diagnostic-only self-supervised training harness now exists** (`edge/eval/twin_training.py`, `43e114d`) using only the existing simulator + `Preprocessor` — confirmed the simulator's clean baseline has no cross-channel/temporal structure beyond each channel's own fitted mean, so even successful hardware-free training only proves the ML plumbing works, not reconstruction quality. Prognosis training remains blocked: no degradation-trajectory data source exists or is specified.
- P3: divergence/substitution behavioral design. **RESOLVED (2026-08-31, `DECISIONS.md` D018)**: divergence measured against the isolated sensor's own continuing raw reading — an explicit backstop, NOT proof, NOT an independent reference (PRD's own R3 circularity risk carried forward, not resolved); fit-time z-score magnitude form (not min-max, not rank/CDF); recovery reuses `TRUSTED_MIN=0.7` (no new hysteresis); 60s expiry without recovery escalates to Safe Pump-Stop; uncertainty stays edge-internal, frozen `DecisionMessage` **not modified**, existing `alerts` table used instead; P2 runs before P3 each cycle. **Hardware-free plumbing implementing this design exists and is now integration-tested** (`edge/pipeline/{divergence,self_heal,cycle}.py`, committed/pushed through `0cc4d31`, 2026-08-31, 68 tests total) — `divergence_threshold` remains a REQUIRED parameter, no value chosen.
- P3: uncertainty-estimation method (FR-H2). **RESOLVED provisionally (2026-08-31, `DECISIONS.md` D019)**: deterministic elapsed-substitution-time proxy — starts at minimum when substitution begins, non-decreasing during that episode, bounded relative to the existing `substitution_max_seconds=60` (D018, not a new time constant), resets per episode. An explicit safety/confidence proxy, NOT a statistically calibrated estimate of reconstruction error. Single-signal only — divergence and reconstruction-stability explicitly NOT added as inputs. Edge-internal, no `DecisionMessage` change. Also approved: P3-HEAL-E1 wording clarified to "Uncertainty flagged high (nearing cap); alert raised." **Hardware-free plumbing implementing this method exists** (`edge/pipeline/uncertainty.py`, committed/pushed `8cc5564`, 2026-08-31). **The scaling formula is now RESOLVED (2026-08-31, `DECISIONS.md` D020, documentation-only): linear, `f(x)=x`, output domain [0,1]** — remains a REQUIRED, never-defaulted injected argument in code; no default was added.
- P3: P2→P3 cycle wiring — which channels reach `SelfHealOrchestrator` each cycle. **Adapter RESOLVED (2026-08-31, `edge/pipeline/cycle.py`, `fe4042e`/`0cc4d31`)**: `process_isolated_channels` takes `isolated_channels`/`raw_values` as REQUIRED, caller-supplied inputs, never derived from trust/band; validate-all-upfront so one bad channel can't side-effect a valid one. **Still UNDECIDED, and NOT what the adapter resolves:** what actually determines *which* channels are isolated for real — FR-RL2 makes this an RL-agent action ("Isolate Sensor"), and both the agent and its deterministic fallback (FR-RL4) remain unbuilt; the adapter is exercised only with test-fixture isolated sets.
- P3: substitution `uncertainty_cap` value and the time→uncertainty **scaling formula** — **RESOLVED (2026-08-31, `DECISIONS.md` D020, documentation-only, policy decision — not data-gated)**: `uncertainty_cap` = 0.8 (proxy's own output domain, ~48s of the 60s budget); scaling formula = linear, `f(x)=x`, output domain [0,1]. Both remain required, never-defaulted parameters in code — D020 chose the values, it did not add a default. **`divergence_threshold` is now the ONLY remaining open U05 numeric value** — still UNDECIDED, data-gated (needs real reconstruction-error and fault/attack-separation statistics).
- P3: RL reward shaping + acceptable false-isolation rate UNDECIDED (U06) — also the source of the still-missing isolation decision above.
None of these block P0.

## Hardware availability / dependencies
- Development environment currently has **no Raspberry Pi and no bench rig** attached.
- Hardware-free: P0 scaffolding, P2 (ML on recorded/dataset), P3 (models/logic), P4 (backend), P5 (dashboard), P7 (evaluation).
- Requires Pi + rig: P1 physical acquisition; P3 physical safe-stop / dry-run / <500ms edge timing; P6 live §18.4 run + physical chaos tests.
- Mitigation: telemetry simulator/replay source (D005) stands in for the rig for all non-physical work and is the demo fallback (PRD R1/R2).

## Architecture constraints (non-negotiable)
- Edge safety loop `sense→detect→attribute→decide→heal→actuate` runs entirely on the Pi; **never depends on backend/cloud/network** (D003).
- Backend = read/observe + advisory-control plane only (visualization, history, config, audit, advisory commands). Never in the safety path.
- One **frozen shared data contract** (telemetry/decision/ledger) identical across firmware, simulator, backend, DB, WebSocket, TS types (D006). No component invents field names.
- Ledger = SHA-256 hash chain; Hyperledger is future scope (D004).
- Offline-demo golden rule: whole stack runs on one machine via `docker-compose`, no internet, fonts self-hosted.
- Aurora aesthetic is subordinate to the 1 Hz live stream + <2s sensor→UI + <500ms self-heal budgets; effects auto-downgrade before the data path (TRD §02.9).
- Tech stack frozen by TRD §02.2 (changes require a version bump + a DECISIONS.md entry).

## P4 — Backend + Ledger (2026-09-05, M1–M6, hardware-free implementation + tests)
Full `backend/` build across six milestones, each run-tested against the
whole `pytest` suite before moving to the next (final: **841 passed, 0
failed, 13 skipped (MQTT-broker-gated), 4 xfailed (pre-existing P2
limitations)**). No Docker/Postgres available in this dev sandbox — see
testing-strategy note below. Not yet committed as of this writing (see
`git status`).
- **M1 — DB models + migration**: all 10 Doc05 §05.2 tables
  (`backend/app/models/`) using portable SQLAlchemy 2.0 types (`Uuid`,
  generic `Enum`, generic `JSON`) so the same models run against SQLite in
  unit tests and Postgres in prod; one hand-written Alembic migration
  (`0001_initial_schema`) using native `postgresql.ENUM`/`JSONB` and
  converting `sensor_readings`/`decisions` to TimescaleDB hypertables —
  **Postgres-only, not run against a real database here** (only
  config-load + `alembic history` verified). **Deliberately deferred**:
  `readings_1min`/`decisions_5min` continuous aggregates + retention
  policies (Doc05 §05.3 is prose-only, no consumer exists, exact column
  shape unspecified — building them now would be inventing an unverified
  shape).
- **M2 — Auth core**: `core/security.py` (bcrypt via passlib, JWT access
  tokens, opaque SHA-256-hashed refresh tokens), `services/auth_service.py`
  (login/issue/rotate/revoke — reuse of an already-rotated refresh token
  revokes every token belonging to that user, since Doc05's flat
  `refresh_tokens` schema has no lineage/family column to do a narrower
  revocation), `api/deps.py` (`get_current_user`, `require_role(...)` RBAC
  dependency that audits denials to `audit_log`), `api/auth.py`
  (login/refresh/logout), `core/seed.py` (idempotent admin-user seed,
  password from `SEED_ADMIN_PASSWORD` env, never hardcoded). **Real
  ecosystem bug found and fixed**: `passlib` 1.7.4 (last release,
  unmaintained since 2020) is incompatible with `bcrypt>=4.1` (dropped
  `__about__`; 4.1+ raises instead of silently truncating >72-byte inputs
  during passlib's own self-test) — pinned `bcrypt==4.0.1`.
- **M3 — Telemetry persistence**: `services/telemetry_persistence.py`
  registers as a second sink on the *existing*
  `TelemetryConsumer.add_sink()` seam (no consumer code changed) alongside
  the WS broadcaster, writing each validated `TelemetryMessage` to
  `sensor_readings` off the live-delivery hot path. Device
  auto-registration on first-seen `device_id`. `healthy_mask` is always
  `0b111111` — the frozen wire contract carries no per-channel health at
  all (`edge/acquisition/sampler.py` only ever emits a frame when all six
  channels are healthy), so anything else would be fabricated. **Real bug
  found and fixed**: querying the `Device` row *after* `add()`-ing a
  `SensorReading` triggered an early SQLAlchemy autoflush that raised
  `IntegrityError` on a duplicate sample outside the intended
  `try/except` — fixed by reordering (fetch/update `Device` before
  `add()`-ing the reading).
- **M4 — REST API**: `api/{devices,alerts,users,system}.py` — full Doc05
  §05.7 surface **except** `POST /api/devices/:id/inject` (U14 — payload
  unspecified in any doc, not invented). App-level device-ownership
  scoping (`api/deps.py`: `require_device_access`/`scope_devices_query`) —
  a device that exists but isn't owned by the caller returns 404, exactly
  like one that doesn't exist, never 403 (the RLS "empty, not error"
  behavior, done at the app layer since DB-level RLS is deferred — see
  below). `readings`/`decisions` are honest about gaps: `agg` only accepts
  `"raw"` (continuous aggregates deferred at M1) and any other value is a
  clear 400; `decisions` returns an empty list (no P2/P3 producer exists
  yet) rather than fabricating rows. `thresholds` lazily creates the
  Doc05-documented 1–1 row with its column defaults on first access;
  `divergence_threshold` stays `NULL` (U05, never silently defaulted,
  matching the edge-side convention in `edge/pipeline/divergence.py`).
  `app/main.py` now wires DB + auth + every router; `DATABASE_URL`/
  `JWT_SECRET_KEY` are required at boot (raise clearly if unset, per TRD
  §02.7's own "missing var → clear boot error" acceptance criterion) —
  the pre-existing app-boot tests (`test_app_health.py`, `test_ws_endpoint
  .py`, `test_integration_ws.py`) were updated to set both via
  `monkeypatch`, same pattern as the pre-existing `MQTT_HOST`/`MQTT_PORT`.
  **Real bug found and fixed**: `ThresholdOut.updated_by` was declared
  `str` but validated directly against the ORM's raw `uuid.UUID` attribute
  via `from_attributes=True`, which pydantic-core does not auto-coerce —
  fixed with an explicit `_to_threshold_out()` converter (matching the
  pattern already used for every other UUID-bearing response model).
- **M5 — Ledger service**: `services/ledger.py` implements D004's SHA-256
  hash chain literally (`this_hash = sha256(index+ts+payload_hash+
  prev_hash)`); `api/ledger.py` — list/verify/export (JSON+CSV), scoped
  like devices/alerts. Threshold `PATCH` now also appends a
  `config_update` ledger block (only when a field actually changed).
  **Scope note (a deviation from the original plan, found while
  implementing, not a shortcut)**: RBAC denials are NOT chained into the
  ledger — `ledger_blocks.device_id` is `NOT NULL` but most RBAC-checked
  endpoints (e.g. `/api/users`) have no device context at all, and Doc05's
  own `audit_log.action` example list already places `"rbac_denied"`
  there, not in `ledger_blocks`. RBAC denials stay in `audit_log` only
  (implemented at M2). **Real, potentially serious bug found and fixed
  before it shipped**: SQLite silently drops a `datetime`'s `tzinfo` on
  round-trip while preserving the wall-clock value (verified empirically);
  `verify()` recomputing a block's hash from a freshly DB-read timestamp
  would therefore have produced a different string than `append()`
  originally hashed, **falsely reporting tampering on untouched data**.
  Fixed by normalizing to UTC before hashing in both `append()` and
  `verify()`; covered by a regression test that forces a fresh session
  (fresh DB read) before verifying.
- **M6 — WS auth**: `/ws?token=<jwt>&device_id=<id>` now requires a valid
  JWT access token (same validation as REST) and applies the same
  ownership scoping as the REST API — an admin sees everything; anyone
  else is scoped to ALL of their owned devices when no `device_id` filter
  is given (not just literally everything, which was the pre-auth P0
  behavor) and rejected outright if they request a `device_id` they don't
  own. An invalid/missing token, or a disallowed `device_id`, closes the
  connection **before** `accept()` is ever called (ASGI permits
  `websocket.close` while still in the CONNECTING state to reject the
  handshake outright) — no frame can leak to an unauthorized client.
  `frontend/scripts/ws_smoke.mjs` updated to log in via
  `POST /api/auth/login` first (credentials from `SMOKE_EMAIL`/
  `SMOKE_PASSWORD` env vars, never hardcoded) and pass the resulting token.
- **Not built in this P4 slice** (flagged, not silently skipped):
  continuous aggregates + retention (M1, above); DB-level RLS (app-level
  scoping used instead); `devices.health_state` rollup-on-decision-insert
  (nothing writes `decisions` yet); Mosquitto broker auth/topic config
  (infra, not backend code); decision/ledger/status MQTT ingestion (no
  producer exists for those topics yet — building consumers for them now
  would be untestable dead code); the Doc05 §05.8 `system_health` **WS
  push frame** (only the REST `GET /api/system/health` poll endpoint was
  built — its `e2e_latency_ms` is honestly `null`, since no continuous
  latency measurement exists in the running backend to report a real
  number from); the `…/command` scenario-inject payload (still U14-
  blocked, not invented).
- **Testing strategy** (agreed before implementation, held throughout):
  SQLAlchemy models use portable types so unit tests run against an
  in-memory SQLite engine; a new `db_integration` pytest marker exists
  (mirroring the pre-existing MQTT `integration` marker) for future
  real-Postgres-only tests, self-skipping here since neither Docker nor
  Postgres is available in this sandbox.
- New/changed dependencies: `sqlalchemy==2.0.*`, `alembic==1.13.*`,
  `psycopg[binary]==3.*`, `python-jose[cryptography]==3.3.*`,
  `passlib[bcrypt]==1.7.*`, `bcrypt==4.0.1` (pinned, see M2), `email-
  validator` (transitively via `pydantic[email]`, needed for `EmailStr` in
  the users API) — all added to `backend/requirements.txt` and the root
  `pyproject.toml` dev extras.
