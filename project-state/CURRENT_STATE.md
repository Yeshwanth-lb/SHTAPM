# CURRENT_STATE

> Implementation memory for SHTAPM. A fresh session reads this first, then
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/` — not duplicated here.

**Last updated:** 2026-08-31, end of session — **`66f790e` is the local
`main` HEAD** (2 commits ahead of `origin/main` — `43e114d`/`66f790e` not
yet pushed; working tree clean). This session: P3 scoping closed U03/U04
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
new P3 sections below for full detail. `divergence_threshold`,
`uncertainty_cap`, and the elapsed-time→uncertainty scaling formula remain
required parameters/injectable seams — **no values chosen, U05
unchanged**; **no meaningful reconstruction accuracy or real-world
validation is claimed anywhere in this slice**. **Hardware-free P2 still
has no remaining mandatory software implementation** (unchanged from the
prior session — see `P2_RESUME.md` §10 for that handoff). See
`DECISIONS.md` D013–D019 and `P2_RESUME.md` §1a/§3a/§7a/§9/§10/§14 for
full detail; this file gives the short version. P0/P1 sections below are
unchanged and still accurate as of 2026-08-10.)

---

## Snapshot
- **Current phase:** P2 — Anomaly / Trust / Attribution (hardware-free FOUNDATIONS complete, incl. c/k/h + `ChannelFlagPolicy` + a minimal `PhysicsRule`; formal P2 acceptance suite now exists and has partially passed — see below). P0 + P1 hardware-free paths complete + verified. P3 — hardware-free self-healing plumbing **plus a concrete LSTM digital twin, both integration-tested** (D016–D019 implementation, the P2→P3 cycle adapter, and `LSTMTwinReconstructor`; numeric values, scaling formula, real reconstruction validation, prognosis, and RL all still open — see below).
- **Current milestone:** `66f790e` (LSTM digital-twin implementation + its `SelfHealOrchestrator`/`process_isolated_channels` integration tests, 2026-08-31 — **local `main` only, 2 commits ahead of `origin/main`**; see the new P3 sections below for full detail). Previous P2 milestone, still accurate: D013 (`DECISIONS.md`, committed at `1c784e5`) — `ChannelFlagPolicy` redesigned ("Candidate B": per-channel own-baseline two-sided test) and a minimal provisional `PhysicsRule` (`TrendSignPhysicsRule`, reusing D010's `k` heuristic) implemented to unblock `AttributionEngine`. Since then (2026-08-29), the one remaining hardware-free P2 acceptance gap was closed: a new `AdaptiveStealthFDI` injection type + its P2-ANOM-S1 scenario, **committed and pushed as `b82f935`** (verified 2026-08-30 — `main`/`origin/main` identical at `b82f935`). The formal P2 acceptance suite (`edge/tests/test_p2_acceptance.py`) now attempts 11/14 Doc06 scenarios: **7/11 PASS** (full matrix: `P2_RESUME.md` §1a). The broader-`PhysicsRule` scoping decision was closed and recorded as **D014** (2026-08-30, documentation-only — no new code): no new channel coverage added; `current`↔`temperature` deferred as the sole future candidate, gated on real bench data. The P2-TRUST-H2 root cause was re-analyzed and recorded as **D015** (2026-08-30, documentation-only): the gap is a joint D009/D010 structural limitation, not primarily GAMMA — both decisions left unchanged, H2 remains FAIL.
- **Overall completion:**
  - **P0 hardware-free: VERIFIED** — offline four-service stack (simulator→Mosquitto→backend→WebSocket→frontend) + E2E latency probe (p95 3–5 ms).
  - **P1 hardware-free: COMPLETE** — C1 driver abstraction, C2 sampler/ring buffer, C3 MQTT buffered-resume/LWT, C2→C3 runtime, C4 relay/watchdog. All unit + real-broker-integration verified.
  - **P2 hardware-free FOUNDATIONS: COMPLETE** — preprocess/windowing, injection framework (now 8 injections incl. `AdaptiveStealthFDI`), Beta trust core + engine, c/k/h signal providers, `ChannelFlagPolicy` (Candidate B, D013), a minimal provisional `PhysicsRule` (D013), attribution engine, pipeline orchestrator, multivariate IF detector.
  - **P2 SWaT DIAGNOSTICS: DIAGNOSTICALLY COMPLETE** (probes, not acceptance) — full campaign (normalization study, threshold sweep, root-cause screen, targeted diagnostics, IF hyperparameter grid) converged on **D012 signal coverage as the dominant demonstrated limitation** of the SWaT proxy validation. Normalization decision RESOLVED (per-window min-max confirmed, not changed). No further SWaT work planned unless explicitly requested — see `P2_RESUME.md` §3a.
  - **P2 FORMAL ACCEPTANCE: PARTIALLY done.** 7/11 attempted Doc06 scenarios PASS (D013 + the 2026-08-29 P2-ANOM-S1 addition); 4 FAIL with precisely diagnosed root causes; O3 structurally unreachable with the current minimal `PhysicsRule`. Full matrix + mandatory-blocker-vs-validation-limitation breakdown: `P2_RESUME.md` §1a/§7a.
  - **P3 hardware-free: PLUMBING + CONCRETE LSTM TWIN COMPLETE, integration-tested** (2026-08-31, local `main` `66f790e`, 2 commits ahead of pushed `origin/main`) — `DivergenceScorer` (D018 pt.1), `ElapsedTimeUncertaintyProxy` (D019), `SelfHealOrchestrator` wired to the existing `RelayController.safe_off()`, the P2→P3 adapter `process_isolated_channels` (`edge/pipeline/cycle.py`, takes `isolated_channels`/`raw_values` as REQUIRED caller-supplied inputs, never derives isolation from trust/band), and a concrete `LSTMTwinReconstructor` (`edge/models/lstm_twin.py` — single-layer unidirectional LSTM → final hidden state → Linear → scalar, `hidden_size` required no default) satisfying the unmodified `TwinReconstructor` Protocol, now integration-tested end-to-end with the orchestrator/adapter. `divergence_threshold`, `uncertainty_cap`, and the scaling formula remain required parameters/injectable seams — no values chosen (U05 unchanged). **No meaningful reconstruction accuracy or real-world validation is claimed** — the simulator's clean baseline has no cross-channel/temporal structure beyond each channel's own fitted mean. Prognosis/LSTM-health (blocked, D017), RL/DQN + its deterministic fallback (U06, FR-RL2/RL4 — also the still-missing source of *which* channels get isolated for real) are all NOT started.
  - **BLOCKED / PENDING (need Pi/rig — not faked):** physical sensor/interface reads, **INA219 pump-current**, **on-Pi LSTM+IF <500 ms** timing, **physical relay safe-stop**, and **physical sensor→DOM / under-load latency**. Neither P0 nor P1 is *fully* done until these are addressed. Real P2 accuracy validation (O2/O3/O4 on real sensors) is also gated here.

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
**Immediate housekeeping: `43e114d` and `66f790e` are committed but NOT
pushed** — `origin/main` still ends at `0cc4d31`; pushing them (once
approved) is the smallest pending action, not new work. Beyond that,
**U05 is still narrowed to just its two numeric values**
(`divergence_threshold` data-gated; `uncertainty_cap` noted as
policy-decidable but still unchosen); the time→uncertainty scaling formula
and U06 remain open; **no meaningful reconstruction accuracy has been
validated** — the simulator's clean baseline structurally cannot supply
the cross-channel/temporal signal needed, so no amount of further
hardware-free training changes that. Nothing in this repo yet decides
*which* channels are isolated for real — FR-RL2 makes that an RL-agent
action, and both the agent and its deterministic fallback (FR-RL4) remain
unbuilt; `process_isolated_channels` is exercised only with test-fixture
isolated sets. Prognosis training is still blocked on an unspecified
degradation-data source. The next session should explicitly ask the user
whether to: (a) push `43e114d`/`66f790e`, (b) choose the `uncertainty_cap`
value (flagged as policy-decidable, not data-gated) or the scaling
formula, (c) scope the deterministic rule-based RL fallback (FR-RL4) —
noting it itself needs `health`/`failure_eta` from the still-blocked
prognosis, so scoping it will likely surface that dependency again, (d)
resolve one of the standing P2 decision-required items (λ=0.7
sign-off/U01, `c`'s redefinition, FR-A4's payload/U14), or (e) something
else entirely. Do not default to further P3 implementation, and do not
create a new decision (D020+) without the same propose-then-approve
sequence used for D014–D019. P2 work otherwise remains blocked on real
bench hardware (also the only path that could unblock D014's deferred
current↔temperature candidate).

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
- P3: uncertainty-estimation method (FR-H2). **RESOLVED provisionally (2026-08-31, `DECISIONS.md` D019)**: deterministic elapsed-substitution-time proxy — starts at minimum when substitution begins, non-decreasing during that episode, bounded relative to the existing `substitution_max_seconds=60` (D018, not a new time constant), resets per episode. An explicit safety/confidence proxy, NOT a statistically calibrated estimate of reconstruction error. Single-signal only — divergence and reconstruction-stability explicitly NOT added as inputs. Edge-internal, no `DecisionMessage` change. Also approved: P3-HEAL-E1 wording clarified to "Uncertainty flagged high (nearing cap); alert raised." **Hardware-free plumbing implementing this method exists** (`edge/pipeline/uncertainty.py`, committed/pushed `8cc5564`, 2026-08-31) — the scaling formula remains a REQUIRED, never-defaulted injected argument, no formula chosen.
- P3: P2→P3 cycle wiring — which channels reach `SelfHealOrchestrator` each cycle. **Adapter RESOLVED (2026-08-31, `edge/pipeline/cycle.py`, `fe4042e`/`0cc4d31`)**: `process_isolated_channels` takes `isolated_channels`/`raw_values` as REQUIRED, caller-supplied inputs, never derived from trust/band; validate-all-upfront so one bad channel can't side-effect a valid one. **Still UNDECIDED, and NOT what the adapter resolves:** what actually determines *which* channels are isolated for real — FR-RL2 makes this an RL-agent action ("Isolate Sensor"), and both the agent and its deterministic fallback (FR-RL4) remain unbuilt; the adapter is exercised only with test-fixture isolated sets.
- P3: `divergence_threshold` + substitution uncertainty-cap **numeric values**, and the time→uncertainty **scaling formula** — still UNDECIDED (data-gated/policy choices; U05 narrowed by D018/D019 to just the two numeric values, unaffected by D019's method choice). All three remain required parameters/injectable seams in the now-implemented and integration-tested plumbing — implementation does not require or imply any of them.
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
