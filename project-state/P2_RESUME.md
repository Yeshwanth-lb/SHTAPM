# P2 Resume Checkpoint

> Durable "when I come back" guide. Read this FIRST, then `CURRENT_STATE.md`,
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/`. Written 2026-08-10; **updated 2026-08-24**
> (documentation-only update — c/k/h signal providers, `ChannelFlagPolicy`, and full
> pipeline wiring landed since the original write-up, and U07 dataset-feasibility
> research completed; see §9 for the commit list). No production code, architecture,
> or tests were changed by this update.
>
> **Further updated 2026-08-24 (same day, third pass):** all local commits pushed
> to `origin/main` (now identical at `9e7e6e7`), and Decision A was approved —
> a SWaT-only iTrust access request was submitted externally by the user. Still
> documentation-only; no code/architecture/tests changed.
>
> **Further updated 2026-08-24 (same day, fourth pass):** `main` and `origin/main`
> are now identical at `4d8a281`, which also fixed the CI dependency gap (see §9)
> — GitHub Actions is GREEN on this commit. Still no code/architecture/tests
> changed by this documentation pass; D010/D011 untouched.
>
> **Further updated 2026-08-25 (fifth pass — real code/test changes, D013):**
> SWaT track declared diagnostically complete (see §3a) — a full experimental
> campaign (normalization study, fine threshold sweep, root-cause hypothesis
> screen, targeted step=1/D012-signal diagnostics, IF hyperparameter grid)
> converged on D012 signal-coverage as the dominant demonstrated limitation of
> the SWaT proxy validation; no further SWaT tuning is planned unless
> explicitly requested. Work then pivoted to hardware-free P2 formal
> acceptance: the first-ever `edge/tests/test_p2_acceptance.py` suite was
> written (10/14 Doc06 scenarios attempted; P2-ANOM-S1 excluded, no adaptive
> injection type exists), which surfaced concrete, root-caused failures in
> `ChannelFlagPolicy` and the total absence of any `PhysicsRule`. Both were
> then addressed under **D013**: `ChannelFlagPolicy` was redesigned
> ("Candidate B" — per-channel own-baseline two-sided test, replacing the
> same-window cross-channel rule) and a minimal, provisional `PhysicsRule`
> (`TrendSignPhysicsRule`) was implemented, reusing D010's `k` heuristic
> verbatim. **D009 (`h`/GAMMA), D010's `k` formula, D011, D012, and IF/`c`'s
> own behavior are all explicitly UNCHANGED.** See §1a for the full P2 status
> matrix.
> (Consolidated into `DECISIONS.md` D013 and this file on 2026-08-26, the day
> after the work itself; no additional code/tests changed during consolidation.)
>
> **CORRECTION (2026-08-29):** the note above and every "UNCOMMITTED" claim
> in this file through the 2026-08-26 pass were **stale**. D013's code was in
> fact committed and pushed as `1c784e5` ("feat(p2): finalize channel policy
> and provisional attribution") — verified this pass: `git log -1 HEAD` and
> `git log -1 origin/main` both resolve to `1c784e50ba8d1fb074076eed3cdf0b350d77bd22`.
> This file simply was not updated to say so at the time. No code changed as
> part of this correction, only this document.
>
> **Further updated 2026-08-29 (sixth pass — real code/test changes,
> P2-ANOM-S1):** implemented the one remaining hardware-free P2 implementation
> gap identified in an audit of this checkpoint: a new `AdaptiveStealthFDI`
> injection type (`edge/injection/injections.py` — an 8th §12.4 injection,
> bias ramps then holds at a caller-chosen `residual_cap`, unlike the
> unbounded `Drift`/`RampFDI` or instant `BiasFDI`/`ConstantSpoof`) plus its
> P2-ANOM-S1 acceptance scenario (`edge/tests/test_p2_acceptance.py`). The
> scenario verifies the injection provably stays under a test-local "naive
> residual" bound throughout, then asserts the real, UNMODIFIED pipeline's
> trust for that channel still degrades below `TRUSTED_MIN` — which it does,
> via the existing `ConsistencyProvider` (`c`) reacting to a sustained
> per-sample bias that a window-variance-based check (IF/`ChannelFlagPolicy`)
> does not. Verified at the committed fixture seed/parameters only (not
> multi-seed stress-tested, unlike H3/E2's explicit 8-seed/5-seed checks) —
> treat as verified-once, not robustly validated. **D009, D010, D011, D012,
> D013, and every existing IF/preprocessing/c/k/h/ChannelFlagPolicy/
> PhysicsRule behavior are explicitly UNCHANGED** — only a new injection type
> and its test were added. Full `pytest edge/`: 332 passed, 4 failed (the
> same 4 pre-existing, documented failures — H1/E1/TRUST-H1/TRUST-H2), 2
> skipped — zero regressions. **Implemented and tested but UNCOMMITTED as of
> this update** — see §9.
> **CORRECTION (2026-08-30): this P2-ANOM-S1 work is now committed and
> pushed** — `docs: correct D013 project state documentation` (`ea437c6`)
> and `feat: add AdaptiveStealthFDI injection` (`b82f935`); `main` and
> `origin/main` both resolve to `b82f935`. The "UNCOMMITTED" line above was
> accurate when written and is kept for the historical record, not edited.
>
> **Further updated 2026-08-30 (seventh pass — documentation-only, D014):**
> the broader-`PhysicsRule` scoping decision flagged as open in §7 step 2 and
> §7a is now resolved and recorded as **`DECISIONS.md` D014**. Conclusion:
> no new `PhysicsRule` channel coverage is added — `pressure` and `humidity`
> are REJECTED (the former reopens D010's already-rejected finding that
> BMP180 is atmospheric-only; the latter directly contradicts the PRD's own
> "Design integrity note" requiring temperature/humidity to stay
> uncorrelated), `gas` is REJECTED (no documented physical linkage exists to
> invent a rule from), and `current`↔`temperature` is DEFERRED as the sole
> future candidate, gated on real bench data that does not exist yet. No
> code was changed by D014; `TrendSignPhysicsRule` (D013) is untouched.
> **O3 remains explicitly NOT ACHIEVABLE** — unchanged by this decision. See
> §5/§7/§7a for the updated references.
>
> **Further updated 2026-08-30 (eighth pass — documentation-only, D015):**
> P2-TRUST-H2's root cause was re-analyzed via read-only diagnostic replay
> (not committed) and is now recorded as **`DECISIONS.md` D015**. Finding:
> the gap is NOT primarily `h`'s GAMMA speed — `ConstantSpoof`'s flat trend
> leaves `k=1.0` (D010's non-paired-channel default, compounded by a
> documented flat-trend blind spot in the trend-sign rule) the whole time,
> structurally flooring `g` at 0.3 independent of `h`. Diagnostic replay
> confirmed a hypothetically-instant `h` collapse (GAMMA removed entirely)
> still misses the 3-window budget (crosses 0.4 at window 5, not 3) — GAMMA
> alone cannot close this gap. **D009 and D010 both remain unchanged
> (Option A)**: H2 is formally documented as a structural limitation, not
> fixed. P2-TRUST-S1's collusion resistance (the reason D009's GAMMA is
> slow) is fully preserved. **P2-TRUST-H2 remains FAIL; O4/AC2 is NOT
> claimed satisfied.** See §1a/§6/§7/§7a for the updated references.
>
> **Further updated 2026-08-30 (ninth pass — documentation-only,
> end-of-day handoff):** P2-TRUST-H1 and P2-ANOM-H1/E1 were analyzed
> together via read-only diagnostic replay (not committed): both share the
> identical empirical-CDF/rank-against-fit-distribution scoring
> architecture. `c` (TRUST-H1) behaves approximately as that architecture
> predicts on clean data and has **no fit-corpus-size fix**. IF's severity
> (ANOM-H1/E1) has a measurable fit-corpus-size calibration component, but
> the rank-based design still retains a nonzero false-positive floor at any
> threshold below 1.0 — the literal zero-false-positive wording stays
> unachievable regardless. No code, tests, or numeric parameters were
> changed; no new decision was created. Committed as `d28de0b` and pushed.
> **`main`/`origin/main` are identical at `d28de0b` — this is today's clean
> baseline.** See §1a/§7a for the updated table/bullets.
>
> A **P3 implementation-readiness analysis** was then performed
> (conversation-only, nothing committed): P3 is the PRD's next phase but is
> **not implementation-ready** — LSTM scope/data source (U03/U04), RL
> reward shaping (U06), and divergence/uncertainty values (U05) are all
> open; a synthetic dry-run signature would need its own new specification;
> the deterministic RL fallback (FR-RL4) is only partially independent,
> since the PRD's own state vector includes `health`/`failure_eta`, which
> only the (undecided) LSTM produces. Reusable infrastructure already
> exists: the frozen `DecisionMessage`/`RLAction` wire contract
> (`backend/app/schemas/contracts.py`) and `RelayController.safe_off()`
> (`edge/actuation/relay.py`, P1). **No P3 file was touched and no P3 work
> was started.** See §10 for the full handoff and recommended order.

---

## 1. Current project status

- **P0 hardware-free:** VERIFIED/COMPLETE — offline four-service stack
  (simulator→Mosquitto→backend→WebSocket→frontend) + E2E latency probe
  (p95 3–5 ms). Hardware spikes (Pi/rig) still blocked.
- **P1 hardware-free:** COMPLETE — C1 driver abstraction, C2 sampler/ring buffer,
  C3 MQTT buffered-resume/LWT, C2→C3 runtime, C4 relay/watchdog. Physical gates
  blocked (need Pi/rig).
- **P2 FOUNDATION (plumbing):** COMPLETE — preprocessing/windowing, injection
  framework, Beta trust core + per-channel engine, attribution shell (now with
  a real, minimal, provisional `PhysicsRule` — D013), pipeline orchestrator,
  real multivariate Isolation Forest, all three trust signal providers
  (`c`/`k`/`h`), and `ChannelFlagPolicy` (redesigned as "Candidate B" — D013)
  — all implemented and wired end-to-end into `P2Pipeline`.
- **P2 VALIDATION (acceptance):** **PARTIALLY done.** The formal Doc06
  P2-ANOM-\*/P2-TRUST-\* acceptance suite (`edge/tests/test_p2_acceptance.py`,
  D013 + the 2026-08-29 P2-ANOM-S1 addition) now attempts 11/14 scenarios —
  7 PASS, 4 FAIL. See §1a for the full status matrix and which failures are
  mandatory implementation blockers vs. documented, honestly-disclosed
  validation limitations. IF remains untuned (U07-gated); the `PhysicsRule`/
  `k` physics are explicitly unvalidated heuristics; no real dataset eval
  contributes to any acceptance claim (SWaT is proxy/methodology evidence
  only, D011, and is now diagnostically complete — no further SWaT tuning
  planned).
- **U07 dataset feasibility (SWaT vs. WADI):** Research **COMPLETE**
  (`U07_DATASET_FEASIBILITY_REPORT.md`); validation methodology **FROZEN**
  (`DECISIONS.md` D011); six-tag mapping **SELECTED** (`DECISIONS.md` D012:
  `LIT101→temperature, AIT203→vibration, DPIT301→pressure, LIT401→humidity,
  AIT402→gas, PIT501→current`) — plumbing/proxy substitution only, no
  physical-equivalence claim; `AIT402` is aqueous ORP, never to be described
  as an ambient-gas reading. **The harness (`edge/eval/swat_eval.py`) IS
  built, committed, and has been run extensively** — a full diagnostic
  campaign (normalization study, fine threshold sweep, root-cause hypothesis
  screen, targeted step=1/D012-signal diagnostics, IF hyperparameter grid)
  converged on a decisive finding: **D012 signal coverage — not
  normalization, threshold, `ChannelFlagPolicy`, or IF hyperparameters — is
  the dominant demonstrated limitation** (57% of real SWaT.A1 attacks show
  zero early signal in any of the six mapped channels). **The SWaT track is
  now declared diagnostically complete; no further SWaT tuning/experiments
  are planned unless explicitly requested.** Neither SWaT nor WADI can ever
  satisfy O3 or the literal six-channel semantics (D011) regardless of
  further tuning.
- **Hardware availability:** NO Raspberry Pi, NO bench rig attached. All P2 work
  is hardware-free; physical gates (P0/P1/P3/P6) remain blocked.
- **Safe to resume from this checkpoint?** **Partially.** D013's code
  (Candidate B `ChannelFlagPolicy`, minimal `TrendSignPhysicsRule`, the
  original `test_p2_acceptance.py` suite), the 2026-08-29 P2-ANOM-S1
  addition (`AdaptiveStealthFDI` + its acceptance test), and D014 (the
  broader-`PhysicsRule` scoping decision, documentation-only) **are all
  committed and pushed** — `main` and `origin/main` are identical at
  `5612a2a` (verified 2026-08-30). D015 (the P2-TRUST-H2 scoping decision,
  §1a/§6/§7/§7a) is documentation-only and carries no code. Check
  `git status` before any further work — expect it dirty with this pass.
  **Do NOT treat P2 as complete** — resume at the first unresolved item (§7).

**Foundation/plumbing complete ≠ validation/acceptance complete.** Every seam
in the P2 pipeline is now filled with a real, working, provisional implementation,
and — as of D013 — a real formal acceptance suite exists and has actually been
run against it. 6 of 10 attempted scenarios pass; the other 4 have precisely
diagnosed root causes (§1a). None of this constitutes a real-data accuracy
validation — that remains gated on hardware (bench rig) or further dataset work.

## 1a. Final P2 status matrix (as of the 2026-08-29 P2-ANOM-S1 addition)

All 11 attempted scenarios use real (non-stub) components end-to-end on
hardware-free simulator streams (`edge/tests/test_p2_acceptance.py`). 4
scenarios (P2-PRE-\*) are out of this table's scope — see notes.

| ID | Result | Root cause / mechanism | Category |
|----|--------|------------------------|----------|
| P2-ANOM-H1 | **FAIL** | IF+threshold+per-window-min-max clean-FP rate (~8% on this stream; ~22% on the original simulator diagnostic). Shares its rank-based scoring architecture with P2-TRUST-H1 (§7a); has a fit-corpus-size-fixable excess component but a nonzero floor regardless — see §7a | Documented validation limitation (U07-gated tuning) |
| P2-ANOM-H2 | **PASS** | Fixed by D013 Candidate B (spike now correctly localized) | — |
| P2-ANOM-H3 | **PASS** (fixture-sensitive) | Attribution=attack via the minimal `PhysicsRule`; verified ~50% (4/8 seeds) reliability — an approximately coin-flip side effect of the onset transition window's shape, not a validated capability | Documented validation limitation |
| P2-ANOM-E1 | **FAIL** | Window-level IF flag oscillates once triggered (upstream of ChannelFlagPolicy; same root cause as H1) | Documented validation limitation (U07-gated tuning) |
| P2-ANOM-E2 | **PASS** (fixture-sensitive) | Fault side deterministic (temperature, no physics rule applies); attack side ~60% (3/5 seeds) reliable | Documented validation limitation |
| P2-ANOM-S1 | **PASS** (verified once) | New `AdaptiveStealthFDI` injection (2026-08-29): bias ramps then holds at a capped bound, provably staying under a test-local "naive residual" check throughout; the real, unmodified `ConsistencyProvider` (`c`) still degrades trust for the channel below `TRUSTED_MIN` because it reacts to a sustained per-sample bias present in every window sample, which a window-*variance*-based check (IF/`ChannelFlagPolicy`) does not — `channel_flags` never fires in this scenario. Verified at the committed fixture seed/parameters only, not multi-seed stress-tested | Newly implemented (not a validation limitation) |
| P2-TRUST-H1 | **FAIL** | `c`'s empirical-CDF rank against its own training distribution produces near-uniform (not near-1.0) values for genuinely clean data, occasionally dragging trust <0.7. Shares its rank-based scoring architecture with P2-ANOM-H1/E1, but unlike them has NO fit-corpus-size-fixable component — confirmed already at its Uniform(0,1) theoretical floor — see §7a | Documented validation limitation |
| P2-TRUST-H2 | **FAIL** | **D015 (2026-08-30):** not primarily a GAMMA/D009 gap. `ConstantSpoof`'s flat trend leaves `k=1.0` (D010's non-paired-channel default, plus a documented flat-trend blind spot in the trend-sign rule itself) the entire time, structurally flooring `g` at 0.3 regardless of `h`. Diagnostic replay confirmed even an instantly-collapsed `h` (GAMMA removed) still misses the 3-window budget (crosses 0.4 at window 5, not 3) — GAMMA is a secondary, compounding factor, not the binding constraint | Documented structural limitation (D015; joint D009+D010 interaction, not missing code) |
| P2-TRUST-E1 | **PASS** | — | — |
| P2-TRUST-E2 | **PASS** | — | — |
| P2-TRUST-S1 | **PASS** | — | — |
| O3 (≥85% attribution accuracy) | **NOT ACHIEVABLE with current implementation** | `PhysicsRule` only ever names current/vibration (4 of 6 channels have no rule at all) and is only ~50–60% reliable even there | **Mandatory implementation blocker** (broader rule) + data-gated (no real physics data beyond the bench current/vibration pair exists anywhere, incl. SWaT/WADI, D010/U07) |

**Score: 7 PASS / 4 FAIL / 0 not attempted / O3 not achievable as implemented.**
See §7a for the mandatory-blocker vs. validation-limitation breakdown and what
each would require.

## 2. What is already implemented

Real, committed P2 components (all hardware-free; tests are math/shape/branch/
plumbing — NOT acceptance):

| Component | File(s) | Commit |
|-----------|---------|--------|
| Beta-reputation foundation (signal-agnostic core) | `edge/trust/beta.py` | `26de8c2` |
| Synthetic §12.4 injection framework (7 injections) | `edge/injection/` | `ee730fe` |
| Anomaly preprocessing + `AnomalyDetector` seam + `NullDetector` | `edge/anomaly/{preprocess,detector}.py` | `f75b9dc` |
| TrustEngine shell (per-channel; `SignalProvider` seam) | `edge/trust/engine.py` | `9479968` |
| AttributionEngine shell (`PhysicsRule` seam) | `edge/anomaly/attribution.py` | `cbd7527` |
| P2 pipeline orchestrator (`ChannelFlagPolicy` seam) | `edge/anomaly/pipeline.py` | `d1ec0da` |
| Real multivariate Isolation Forest | `edge/anomaly/iforest.py` | `5a1af31` |
| Diagnostic harness (IF probe + normalization experiment) | `edge/eval/`, `edge/tests/test_{if_eval,preproc_experiment}.py` | `d17942f` |
| Foundation bookkeeping (project-state) | `project-state/*` | `5b49010` |
| Diagnostic findings bookkeeping (project-state) | `project-state/*` | `72f25d1` |
| `h` historical-reliability provider — per-channel slow EMA (GAMMA=0.95) | `edge/trust/h_reliability.py` | `c56cb4d` |
| `c` consistency provider — z-score residual + empirical CDF | `edge/trust/c_consistency.py` | `d1e6d48` |
| `k` cross-sensor correlation provider — provisional current↔vibration trend-sign heuristic (D010) | `edge/trust/k_correlation.py` | `691847f` |
| `ChannelFlagPolicy` — variance-threshold window→per-channel flagging (original design) | `edge/anomaly/policy.py` | `57d434d` |
| P2Pipeline wiring: `record_window`/`record_outcome` calls to c/k/h before trust update | `edge/anomaly/pipeline.py` | `b0f0272` |
| SWaT.A1 evaluation harness (D011/D012) | `edge/eval/swat_eval.py`, `edge/tests/test_swat_eval.py` | `60a4dbe` (+ later latency commit) |
| `ChannelFlagPolicy` redesign ("Candidate B" — per-channel own-baseline two-sided test, D013) | `edge/anomaly/policy.py` | `1c784e5` |
| Minimal provisional `PhysicsRule` (`TrendSignPhysicsRule`, D013) | `edge/anomaly/physics_rule.py` | `1c784e5` |
| First formal P2 acceptance suite (D013, 10/14 scenarios) | `edge/tests/test_p2_acceptance.py` | `1c784e5` |
| Unit tests for the above | `edge/tests/{test_policy,test_physics_rule}.py` | `1c784e5` |
| `AdaptiveStealthFDI` injection (8th §12.4 injection) + P2-ANOM-S1 acceptance scenario (2026-08-29) | `edge/injection/injections.py`, `edge/injection/__init__.py`, `edge/tests/{test_injection,test_p2_acceptance}.py` | `b82f935` (+ doc commit `ea437c6`) |

**Test totals:** full `pytest edge/` (2026-08-29, post-P2-ANOM-S1): **332
passed, 4 failed, 2 skipped** (broker-gated integration). The 4 failures are
exactly the 4 documented validation limitations in §1a — no unexpected
regressions (up from 327/4/2 pre-D013; the +5 passing tests are the new
`AdaptiveStealthFDI` shape tests and its one acceptance test).
**Passing unit/interface tests still do NOT equal P2 acceptance** in general —
but a REAL acceptance suite now exists and 7/11 attempted scenarios genuinely
pass it; see §1a for the honest, complete picture.

Key invariants held throughout: frozen contract (`backend/app/schemas/
contracts.py`) untouched; λ=0.7 recorded as PENDING U01 approval (not a spec);
all injection magnitudes + eval thresholds are FIXTURES, not specs; no physics /
c/k/h / dataset logic invented.

## 3. What the real Isolation Forest diagnostic showed

Simulator-only observations (commit `d17942f`; reproduce with
`PYTHONPATH=backend:. python -m edge.eval.if_eval` and `… -m
edge.eval.preproc_experiment`). **Diagnostic threshold (0.95) and all injection
magnitudes are EVALUATION FIXTURES, NOT project specifications.**

- Current **per-window min-max ≈ 21.6% clean-vs-clean false positives** at the
  diagnostic fixture threshold.
- **Train-fit global min-max ≈ 3.5%**; **train-fit z-score ≈ 4.1%** (≈ ideal ~5%
  for a 0.95 threshold).
- **Per-window min-max washes out a constant additive bias** within a fully-
  injected window (bias FDI becomes indistinguishable from clean).
- The apparent **constant-spoof "detection" under per-window min-max is a
  normalization flatness artifact** (a pinned channel → all-zeros after per-
  window min-max), NOT real cross-sensor spoof detection.
- **Global/z-score expose the honest limitation:** a plausible constant spoof
  near the mean is correctly NOT detected — it carries no marginal signal and
  requires **cross-sensor physics**.
- **Replay was the hardest injection to flag** (valid recorded data — correct).
- These are **simulator observations only** (independent Gaussian channels, no
  cross-sensor physics, stationary) — they do NOT predict SWaT/WADI/TEP
  behaviour, and global/z-score's apparent advantage may not hold on real,
  non-stationary signals.
- **Normalization choice is intentionally DEFERRED until real SWaT/WADI/TEP
  evaluation (U07).** No production preprocessing change approved or made.

## 3a. SWaT.A1 diagnostic campaign — DIAGNOSTICALLY COMPLETE (2026-08-25)

The SWaT.A1 harness (`edge/eval/swat_eval.py`, D011/D012) was built, run in
full (untuned, ~945K rows), and then subjected to a full experimental
campaign, entirely on real data, entirely read-only/scratchpad except the
harness itself:

1. **Untuned full evaluation:** FP=0.065, detection=0.332 at threshold=0.95,
   median latency=4 windows (step=30 fixture), 3/35 episodes never flagged.
2. **3-variant normalization study** (A: per-window min-max/production, B:
   train-fit global min-max, C: train-fit z-score): B≡C mathematically for
   IF (per-feature affine invariance); B/C win on aggregate FP/detection
   rate, but A wins on per-episode latency/coverage — and the PRD's own
   acceptance criteria (O2/O4/P2-ANOM-H2/H3/P2-TRUST-H2/AC2, all phrased as
   "≤3 windows", not aggregate rates) favor A. **Variant A (current
   production default) confirmed as better-aligned; not changed.**
3. **17-point fine threshold sweep on Variant A:** no threshold in
   [0.50, 0.999] satisfies both the latency and FP requirements
   simultaneously — a smooth, continuous, unresolvable tradeoff, not a
   tuning problem.
4. **Root-cause hypothesis screen** (4 hypotheses: IF config, D012 mapping,
   `ChannelFlagPolicy`, windowing): `contamination` ruled out (zero effect,
   confirmed by code trace); `ChannelFlagPolicy` ruled out for LATENCY
   (gated entirely by IF's own window flag); windowing flagged a real
   step=30-vs-step=1 unit mismatch; D012 mapping flagged weak signal.
5. **Targeted step=1 + D012 raw-tag diagnostics** (small-slice, no full
   pipeline run): step=1 does NOT materially improve the ≤3-window hit rate
   (34.3% vs. step=30's 42.9% — slightly worse, refuting the windowing
   hypothesis); **57.1% (20/35) of real attack episodes show ZERO measurable
   deviation in ANY of the six D012 proxy channels within 30s of onset.**
6. **IF hyperparameter grid on signal-bearing episodes** (n/estimators,
   max_samples; contamination excluded, already ruled out) + zero-signal
   control: IF configuration changes do NOT materially improve detection on
   the episodes that DO carry signal (46.7–53.3% within-3-window across all
   6 configs tested); the zero-signal control group performs far worse
   under the IDENTICAL configuration (20.0% within-3-window vs. 46.7–53.3%),
   isolating signal availability — not IF configuration — as the dominant
   variable.

**Conclusion (decisive, evidence-based): D012 signal coverage is the
dominant demonstrated limitation of the SWaT proxy validation** — not
normalization, threshold, `ChannelFlagPolicy`, or IF hyperparameters.
Consistent with D011's own framing (SWaT can only ever validate P2
architecture/methodology, never claim bench-equivalent accuracy).
**The SWaT track is declared diagnostically complete. No further SWaT
experiments, tuning, or threshold sweeps are planned unless explicitly
requested.** All experiment scripts remain uncommitted scratchpad, per
D011's proxy-only framing; only the harness itself (`edge/eval/swat_eval.py`)
is committed production-adjacent code.

## 4. Current P2 architecture

```
TelemetryMessage (frozen contract)
  → preprocessing            (edge/anomaly/preprocess.py: median→low-pass→
                              30-sample window→per-window min-max)   [REAL]
  → 30-sample Window
  → Isolation Forest         (edge/anomaly/iforest.py: multivariate, 180-dim,
                              empirical-CDF severity, required flag_threshold) [REAL, UNTUNED]
  → window anomaly result    (AnomalyResult: flag + severity∈[0,1])  [REAL]
  → ChannelFlagPolicy         (edge/anomaly/policy.py: "Candidate B" -- per-
                              channel, own-baseline, two-sided empirical-CDF
                              test; D013)                      [REAL, provisional/untuned]
  → c/k providers record_window(); h provider record_outcome()       [REAL, wired in pipeline.py]
  → TrustEngine              (edge/trust/engine.py: per-channel Beta) [REAL engine,
                              fed by REAL c/k/h SignalProviders — all provisional/untuned]
  → AttributionEngine        (edge/anomaly/attribution.py: none/fault/
                              attack branch logic) [REAL logic, now fed a REAL
                              (minimal, provisional) TrendSignPhysicsRule -- D013]
  → WindowOutcome            (internal struct; NOT a wire contract)   [REAL]
```

**Real:** preprocessing, IF detector (untuned), anomaly result, `ChannelFlagPolicy`
(Candidate B, per-channel own-baseline heuristic — D013), all three `c`/`k`/`h`
SignalProviders (provisional/unvalidated), Beta math + per-channel engine,
attribution branch logic fed by a real minimal `PhysicsRule` (`TrendSignPhysicsRule`,
D013), orchestrator (fully wired), WindowOutcome. `NullDetector` remains as a
placeholder detector; the real IF drops in behind the same `AnomalyDetector`
protocol.

**"Real" here means implemented and wired, not validated.** `ChannelFlagPolicy`'s
own-baseline test and the `PhysicsRule`'s trend-sign heuristic are both working
code with no accuracy claim — the `PhysicsRule` in particular is verified (§1a)
to be only ~50–60% reliable even within its narrow current/vibration scope, and
names no other channel at all — see §5.

## 5. Explicitly unresolved decisions

**Do NOT invent physics or undocumented numeric values merely to make acceptance
tests pass.** Each below stays open until the stated input exists.

| Decision | Current status | Why unresolved | What is needed |
|----------|---------------|----------------|----------------|
| U01: `c` consistency definition | **RESOLVED (provisional)** — `ConsistencyProvider`: z-score residual vs. a fitted clean-baseline mean/std, mapped through an empirical CDF (`edge/trust/c_consistency.py`, `d1e6d48`) | Implemented and wired; NOT validated on real data | Real-data validation of the residual/CDF approach and its false-positive rate (U07) |
| U01: `h` historical reliability definition/memory | **RESOLVED** — per-channel slow EMA, GAMMA=0.95, H_INIT=1.0 (`edge/trust/h_reliability.py`, `c56cb4d`; decision record `DECISIONS.md` D009) | Implemented and wired | Real-data validation of the ~13-window half-life against actual attack cadence (U07) |
| U01: λ forgetting factor | λ=0.7 implemented as PENDING default | Analyzed (T₃=λ³<0.4), not a doc spec | Explicit approval to confirm 0.7 (or change) — **still open**, unchanged |
| U02: `k` / cross-sensor physics definition | **RESOLVED (provisional)** — current↔vibration trend-sign heuristic, no tunable threshold (`edge/trust/k_correlation.py`, `691847f`; decision record `DECISIONS.md` D010) | Implemented and wired; explicitly documented as unvalidated physics | Real-data validation: does the correlation actually hold, and is sign comparison alone sufficient (U07 / domain review) |
| U02: current↔pressure problem / dataset channel mapping | OPEN (unchanged) — current↔pressure rejected for `k` (D010: bench pressure is atmospheric-only; confirmed absent from SWaT/WADI too, U07 report §5) | Bench pressure is an atmospheric PROXY; SWaT/WADI have real pressure but NO continuous motor current → literal pair exists nowhere | No action planned — `k` now uses current↔vibration instead (D010); row kept to track that the PRD's literal current↔pressure pair remains unrealizable anywhere |
| U02: `PhysicsRule` for `AttributionEngine` | **RESOLVED (minimal, provisional)** — `TrendSignPhysicsRule` reuses D010's `k` heuristic verbatim, narrow scope (`edge/anomaly/physics_rule.py`; decision record `DECISIONS.md` D013) | Implemented and wired; verified ~50–60% attribution reliability even within scope; no rule for 4 of 6 channels | Broadening was formally scoped and closed by `DECISIONS.md` **D014** (2026-08-30): `pressure`/`humidity`/`gas` REJECTED (D010 conflict, PRD design-integrity note, no documented basis respectively); `current`↔`temperature` DEFERRED as the sole future candidate, gated on real bench data that does not exist yet. No code changed; O3 remains unachievable. |
| ChannelFlagPolicy (window→per-channel) | **RESOLVED (provisional, redesigned — "Candidate B", D013)** — per-channel, own-baseline, two-sided empirical-CDF test: `fit()` on clean-baseline windows, flag if current variance is an outlier (high or low) vs. THAT channel's own history (`edge/anomaly/policy.py`; design notes in `project-state/CHANNELFLAGPOLICY_DESIGN_ANALYSIS.md`) | Implemented and wired; fixes the P2-ANOM-H2 spike-misdirection bug and improves P2-TRUST-H2's flag rate 5x; NOT validated on real data; does not help drift/ramp or replay shapes | `tail_fraction` (default 0.1) tuning on real labeled attacks (U07) |
| IF hyperparameters + flag threshold | UNTUNED (sklearn defaults; threshold required, unset). SWaT diagnostic campaign (§3a) found IF config changes do NOT materially improve detection even where real signal exists | No documented values; simulator/SWaT both show IF config is not the binding constraint | Tuning would need real bench clean-baseline data; SWaT evidence suggests limited further upside |
| Normalization choice | per-window min-max (current); confirmed **not changing** (§3a: PRD's own ≤3-window criteria favor per-window over aggregate-rate-favoring alternatives) | SWaT-based comparison complete (normalization study, §3a) — decision made, not deferred | None — resolved in favor of keeping the current default |
| U07: SWaT/WADI access + TEP fallback | **COMPLETE.** Feasibility research, methodology (D011), six-tag mapping (D012), harness (`edge/eval/swat_eval.py`), and a full diagnostic campaign (§3a) are all done. **Diagnostically complete** — no further SWaT work planned | D012 signal coverage identified as the dominant, decisive limitation | None planned unless explicitly requested |
| Realistic injection magnitudes/durations | FIXTURES only | §12.4 specifies none; couples to the (undecided) detector threshold | Set against real data / detector calibration; never as project specs invented here |
| P2 acceptance validation | **PARTIALLY done** — formal suite (D013 + 2026-08-29 P2-ANOM-S1 addition), 7/11 attempted scenarios PASS (§1a). Broader-`PhysicsRule` scope formally decided, not expanded (D014) | Real-data accuracy validation still requires hardware (bench rig) — SWaT/WADI structurally cannot provide it (D011); D014's deferred current↔temperature candidate needs the same hardware | Real bench hardware (§7a's sole remaining mandatory blocker); accept the rest as hardware/decision-gated |

## 6. What is explicitly NOT complete

Do NOT let any of these be described as finished:

- reliable anomaly detection accuracy on clean data (P2-ANOM-H1/E1 — U07-gated)
- consistent healthy-sensor trust ≥0.7 (P2-TRUST-H1 — `c`'s rank-noise, U07-gated)
- P2-TRUST-H2 within-3-window collapse (root cause established by D015: `ConstantSpoof`'s flat trend + D010's `k=1.0` non-paired default jointly floor `g`; D009's `h` EMA speed is a secondary factor, not the binding one)
- reliable attack attribution — P2-ANOM-H3/E2 pass at committed seeds but are
  verified only ~50–60% reliable, not validated (D013)
- P2-ANOM-S1 — implemented and PASSES (2026-08-29, `AdaptiveStealthFDI`), but
  verified only at the committed fixture seed/parameters, not multi-seed
  stress-tested the way H3/E2 explicitly were — treat as verified-once
- attribution accuracy for any channel other than current/vibration (no rule exists)
- O3 ≥85% attribution accuracy (structurally unreachable with the current minimal rule)
- O10 confusion matrix / ablation results
- real dataset (SWaT/WADI/TEP) evaluation contributing to any acceptance claim
  (SWaT is proxy/methodology evidence only, D011 — and is diagnostically complete)
- physical sensor validation (real sensor reads / INA219 pump current)
- physical relay / safe-stop validation
- on-Pi LSTM + Isolation Forest timing (<500 ms budget)
- any hardware-dependent gate (P0 spikes, P1 physical acquisition, P3 safety, P6 chaos/soak)

## 7. Exact recommended next sequence

`h`/`c`/`k`/`ChannelFlagPolicy`/pipeline wiring, U07 feasibility+access+mapping,
the SWaT harness + full diagnostic campaign, the first formal P2 acceptance
suite, the `ChannelFlagPolicy` redesign, a minimal `PhysicsRule` (D013), the
P2-ANOM-S1 `AdaptiveStealthFDI` injection (2026-08-29), and the broader-
`PhysicsRule` scoping decision (D014, 2026-08-30) are all **DONE** — see
§1a/§2/§3a/§5. What remains, in order of what's actually achievable without
hardware:

1. ~~Commit the 2026-08-29 P2-ANOM-S1 work~~ — **DONE.** Committed as
   `docs: correct D013 project state documentation` (`ea437c6`) and
   `feat: add AdaptiveStealthFDI injection` (`b82f935`), and pushed; `main`
   and `origin/main` are identical at `b82f935` (verified 2026-08-30).
2. ~~Decide on the one remaining mandatory implementation blocker (§7a) — a
   broader `PhysicsRule`~~ — **DONE, resolved by `DECISIONS.md` D014
   (2026-08-30).** No new channel coverage: `pressure`/`humidity`/`gas`
   REJECTED (D010 conflict / PRD design-integrity note / no documented
   basis, respectively); `current`↔`temperature` DEFERRED as the sole future
   candidate, gated on real bench data collection (needs the Pi/rig, not
   available here). No code changed by D014; O3 remains unachievable — see
   §7a.
3. ~~Decide whether to address P2-TRUST-H2~~ — **DONE, resolved by
   `DECISIONS.md` D015 (2026-08-30, Option A):** D009 and D010 both left
   unchanged; H2 formally documented as a structural limitation (root cause:
   `ConstantSpoof`'s flat trend + D010's `k=1.0` non-paired default jointly
   floor `g` at 0.3, independent of `h`'s speed — GAMMA/D009 alone was
   confirmed, by diagnostic replay, insufficient to close the gap even if
   removed entirely). P2-TRUST-S1's collusion resistance is fully preserved.
   Still open: **decide whether to address the remaining documented
   validation limitations (§7a)** — `c`'s rank-CDF noise (P2-TRUST-H1), IF's
   threshold/oscillation behavior (P2-ANOM-H1/E1). These touch
   already-approved decisions (U01's `c`) or U07-gated data and are
   validation/tuning questions, not missing capability — see §7a for what
   each would need before touching.
4. **Real bench-hardware validation** — the only way to close O2/O3/O4 and
   the full P2-ANOM-\*/P2-TRUST-\* acceptance table for real, since SWaT/WADI
   were always architecture/methodology-only (D011) and are now
   diagnostically exhausted for that purpose; also the only way the D014
   current↔temperature candidate could ever move forward. Blocked on Pi/rig
   availability, unrelated to anything in this session.
5. **Only then** update P2 status toward completion.

Do NOT add new/random architecture before an explicit decision on step 3. Do
NOT re-open the SWaT track (step 3a is closed) unless explicitly requested.
Do NOT reopen D010 or the humidity/gas rejections in D014 without new
evidence.

## 7a. Mandatory implementation blockers vs. documented validation limitations

**Mandatory implementation blockers** — genuinely missing capability; no
amount of tuning or data closes these without new code:

- **Real bench hardware (Pi + rig).** Pre-existing, unrelated to D013/D014 —
  blocks literal O2/O3/O4 and the full acceptance table regardless of
  anything achievable in software. Also the only path that could ever
  unblock D014's deferred current↔temperature candidate.

**Resolved since the table above was first written:**

- ~~P2-ANOM-S1's adaptive/stealth injection type~~ — **implemented
  2026-08-29** (`AdaptiveStealthFDI`, `edge/injection/injections.py`) and its
  acceptance scenario now PASSES (§1a). Verified at the committed fixture
  seed/parameters only.
- ~~A broader `PhysicsRule`~~ — **scoping decision made, no expansion
  implemented (`DECISIONS.md` D014, 2026-08-30).** The current
  `TrendSignPhysicsRule` (D013) still only ever names `current`/`vibration`,
  still empirically ~50–60% reliable even there — that has NOT changed.
  What's resolved is the *decision*, not the capability: `pressure` and
  `humidity` are formally REJECTED as candidates (not merely unaddressed —
  `pressure` would reopen D010's atmospheric-only finding; `humidity` would
  contradict the PRD's own design-integrity note requiring it stay
  uncorrelated from temperature), `gas` is REJECTED for lack of any
  documented physical basis, and `current`↔`temperature` is DEFERRED as the
  one remaining candidate, explicitly gated on real bench data that doesn't
  exist. **O3 (≥85% attribution accuracy) remains structurally unreachable**
  — D014 does not change this, and was never intended to.
- ~~P2-TRUST-H2's within-3-window gap~~ — **root-caused and formally
  documented, not fixed (`DECISIONS.md` D015, 2026-08-30).** Diagnostic
  replay established the gap is NOT primarily `h`'s GAMMA speed: `D010`'s
  `k=1.0` non-paired-channel default (compounded by a documented flat-trend
  blind spot in the trend-sign rule, which treats `ConstantSpoof`'s
  zero-trend shape as always "agreeing") structurally floors `g` at 0.3
  regardless of `h`. Even a hypothetically-instant `h` collapse (GAMMA
  removed entirely) still misses the 3-window budget (crosses 0.4 at
  window 5, not 3). **D009 and D010 both remain unchanged** — GAMMA alone
  cannot close this gap, and fixing it for real would require touching both
  decisions together plus real attack-cadence data, which does not exist.
  P2-TRUST-S1's collusion resistance (the reason D009's GAMMA is slow) is
  fully preserved. **H2 remains FAIL; O4/AC2 is NOT claimed satisfied.**

**Documented validation limitations** — the implementation exists, is wired,
and has been tested; the open question is accuracy/reliability against real
data or a parameter choice, not missing code:

- **P2-ANOM-H1/E1 and P2-TRUST-H1 share one underlying mechanism (analyzed
  2026-08-30, documentation-only, no code/tests changed):** both
  `IsolationForestDetector.score()` and `ConsistencyProvider`'s `c` compute
  an **empirical-CDF rank of a per-window statistic against a stored
  fit-time distribution of that same statistic** — the identical scoring
  architecture applied to two different upstream statistics. This
  architecture is, by construction, diffuse on genuinely clean held-out
  data rather than concentrated near an "obviously healthy" value —
  confirmed by a read-only diagnostic replay (not committed) over ~2000
  genuinely clean held-out windows against the committed, unmodified fit.
  - **P2-ANOM-H1/E1** (clean false-positive rate; oscillation once
    flagged) — IF + threshold + per-window-min-max normalization all exist
    and work. The diagnostic found the observed excess false-positive rate
    (above the theoretical rank-based floor) has a measurable **fit-corpus-
    size** component: enlarging the (purely simulator-generated, no new
    invented values) fit corpus from 600 to 6,000+ frames reduced the
    observed false-positive rate from ~9% toward the ~5–6% theoretical
    floor. **This is NOT being implemented now** — it is simulator-only
    optimization, and even at the floor a rank-based score at any threshold
    below 1.0 retains a nonzero false-positive rate by construction, so the
    literal zero-false-positive acceptance wording remains unachievable
    regardless. E1's oscillation is the same score/threshold-boundary
    behavior manifesting as intermittent flag/unflag flips near 0.95.
    Per-window normalization remains the evidence-reviewed default (§3a)
    and is not being reconsidered here. Real retuning of `flag_threshold`
    or normalization still needs real clean-baseline data (U07-gated), not
    new code.
  - **P2-TRUST-H1** (`c`'s rank-based noise) — `ConsistencyProvider` is
    fully implemented (U01 resolved, provisional) and is **not an
    implementation bug**: the same diagnostic found `c`'s distribution on
    clean data is *already* at its Uniform(0,1) theoretical prediction even
    at the committed fit size, and **enlarging the fit corpus does not
    change this** (unlike ANOM-H1/E1, there is no data-volume component to
    recover). No evidence-backed fix exists without redefining `c`'s
    formula itself, which would be a new specification decision, not a
    tuning step.
- **P2-ANOM-H3/E2's ~50–60% reliability** — the rule exists, is wired, and
  is empirically measured; its accuracy is honestly disclosed as
  chance-influenced, not a missing capability. Widening this rule's scope was
  the "broader `PhysicsRule`" item — now formally scoped-closed by D014
  (no expansion; see "Resolved since the table above was first written"
  above), not an open mandatory blocker any more.

## 8. Resume instructions for Claude Code

### IF I RETURN TO THIS PROJECT AFTER A FEW DAYS
- Read **this file first**, then `CURRENT_STATE.md` and `TODO.md` (then
  `DECISIONS.md`, `IMPLEMENTATION_LOG.md` as needed).
- Inspect `git status` and recent `git log` before touching anything.
- **Do NOT assume P2 is complete** — foundations/plumbing done, and a real
  acceptance suite now exists and partially passes (§1a), but real-data
  validation is not done.
- **Do NOT recreate** already-implemented components (§2) — c/k/h,
  `ChannelFlagPolicy` (Candidate B), and a minimal `PhysicsRule` are all real,
  working, provisional implementations, not seams.
- **Do NOT redo** the corpus/U01/U02/U07 investigations, or the SWaT
  diagnostic campaign (§3a — diagnostically complete), unless the underlying
  `docs/` changed or explicitly asked to.
- **Continue from the first unresolved item in §7** — check `git status`
  first: D013, P2-ANOM-S1, and D014 are all committed and pushed
  (`main`/`origin/main` at `5612a2a` as of the D014 commit, verified
  2026-08-30); the D015 documentation pass is likely still uncommitted
  (see §9).
- **Preserve all deferred decisions** (λ pending, `c`'s rank-noise, U02
  real-physics validation beyond current/vibration) — do not silently
  resolve them. P2-TRUST-H2 itself is no longer "deferred" — it is formally
  documented as a structural limitation by D015; do not reopen D009/D010
  to chase it without new bench/attack-cadence data.
- **Ask for approval before making a genuinely new specification decision**
  (any physics relation, numeric threshold, c/k/h/PhysicsRule redefinition,
  dataset choice) — this is exactly why D013 stopped short of touching
  D009's GAMMA, and why D015 formally declined to touch D009 or D010 even
  after identifying D010's `k=1.0` floor as the actual binding constraint
  for P2-TRUST-H2.
- Keep the per-step discipline: implement → run pytest/ruff/black/`git diff
  --check` → STOP and report → commit only on approval → do not push unless told.

## 9. Git checkpoint

- **Branch:** `main`.
- **`main` and `origin/main` were identical at `d28de0b`** ("docs: clarify
  H1 E1 rank-based validation limits") **as of the end of the 2026-08-30
  session — this is the clean baseline for the next session to resume
  from.** D013 (`1c784e5`), the D013-uncommitted documentation correction
  (`ea437c6`), the P2-ANOM-S1 feature (`b82f935`), the D014 documentation
  commit (`5612a2a`), the D015 documentation commit (`3a1be08`), and the
  H1/E1 documentation commit (`d28de0b`) are all committed and pushed.
  **This end-of-day handoff pass (§10) is documentation-only and, once
  written, will itself be the next thing pending commit/push approval** —
  check `git status`/`git log -1 origin/main` before assuming which of the
  two is current.
- **CI status:** last known green at `4d8a281` (pre-SWaT-harness); not
  independently re-verified against `d28de0b` or this handoff diff.
- **Latest commits on `main` (newest first, before this handoff pass):**
  - `d28de0b` docs: clarify H1 E1 rank-based validation limits
  - `3a1be08` docs: record D015 trust H2 structural limitation
  - `5612a2a` docs: record D014 physics rule scoping decision
  - `b82f935` feat: add AdaptiveStealthFDI injection (P2-ANOM-S1)
  - `ea437c6` docs: correct D013 project state documentation
  - `1c784e5` feat(p2): finalize channel policy and provisional attribution (D013)
  - `60a4dbe` feat: add SWaT.A1 evaluation harness
  - `4bc0c3a` docs: record SWaT A1 six-tag mapping
  - `b47a960` docs: update P2 resume checkpoint after CI fix
  - `4d8a281` fix: install edge dependencies in CI
  - `c40221c` docs: update P2 resume checkpoint after SWaT request
  - `8ca3570` style: apply black formatting to P2 provider tests
  - `9e7e6e7` docs: freeze SWaT P2 validation methodology
  - `642c47b` docs: refresh P2 checkpoint and U02/U07 decisions
  - `b0f0272` P2: wire c/k/h providers into pipeline
  - `57d434d` P2: implement ChannelFlagPolicy with variance-threshold heuristic
  - `691847f` P2: implement cross-sensor correlation signal provider (k)
  - `06031d7` P2: add c/h provider integration tests
  - `76ff900` P2: fix consistency provider lint issues
  - `d1e6d48` P2: implement consistency signal provider (c)
  - `eb93f1a` P2: format historical reliability provider
  - `a50d599` P2: fix h reliability test import order
  - `c56cb4d` P2: implement historical reliability signal
  - `b3aaca6` P2: add durable resume checkpoint (project-state/P2_RESUME.md)
  - `72f25d1` P2: record IF + preprocessing diagnostic findings (normalization deferred)
  - `d17942f` P2: add hardware-free IF + preprocessing diagnostic harness (not acceptance)
  - `5b49010` P2: record hardware-free anomaly/trust/attribution foundations
  - `5a1af31` P2: multivariate Isolation Forest detector
  - `d1ec0da` P2: pipeline orchestrator
  - `cbd7527` P2: attribution-engine shell
  - `9479968` P2: trust-engine shell
  - `f75b9dc` P2: anomaly-detection foundation
  - `ee730fe` P2: synthetic injection framework
  - `26de8c2` P2: Beta trust foundation
- **Push status:** **All commits through `d28de0b` are pushed** — `main` and
  `origin/main` both point to `d28de0b` (verified 2026-08-30, end of
  session). This end-of-day handoff pass (§10) is local-only and
  uncommitted as of writing it; do not commit or push it without explicit
  approval.
- **External state (not tracked by git):** a SWaT-only iTrust dataset-access
  request was submitted externally by the user on 2026-08-24, directly via the
  iTrust request form (outside this repo/session — no request/reference ID was
  captured here). Status: **awaiting iTrust's response.** No dataset has been
  downloaded. WADI has NOT been requested (remains the pre-approved fallback).
  TEP remains a separate, undecided alternative — it must NOT be silently
  substituted for SWaT if the response is slow or unfavorable; that would need
  its own explicit decision.

## 10. End-of-day handoff (2026-08-30) — P2 hardware-free complete; P3 analyzed, NOT started

**Read this section first if resuming after today.**

**P2 status:** Hardware-free P2 has **no remaining mandatory software
implementation** — confirmed against `P2_RESUME.md` §7a's own "Mandatory
implementation blockers" list, which now contains exactly one entry: real
bench hardware. This is **not** a claim that P2 is fully hardware-validated
or that every PRD acceptance criterion is met. Remaining P2 gaps are each
one of: hardware/data-blocked (O2/O3/O4/O10, real bench validation),
decision-required (λ=0.7 sign-off, `c`'s redefinition, FR-A4's payload),
optional (the unimplemented ANOM-H1/E1 fit-corpus-size improvement), or a
documented limitation (P2-TRUST-H1/H2, P2-ANOM-H1/E1/H3/E2) — never an
ordinary bug awaiting more coding. Full detail: §1a, §6, §7, §7a.

**Baseline:** `d28de0b` — `main` and `origin/main` identical, working tree
clean, as of the end of this session (see §9).

**P3:** A read-only implementation-readiness analysis was performed this
session (conversation-only; nothing committed, no files touched). Findings:
- P3 (Prognosis/RL/Self-Healing/Safety) is the PRD's next phase (§23 build
  order) but is **not implementation-ready as a whole**.
- Open decisions block most of it: **U03/U04** (LSTM: one model or two;
  bench vs. synthetic training data), **U06** (RL reward shaping), **U05**
  (`divergence_threshold` + substitution uncertainty-cap — a real Doc05
  schema column with no default). A synthetic dry-run signature (for
  FR-R2) would need an entirely new specification, not yet scoped.
- The deterministic RL fallback (FR-RL4) is **only partially independent**:
  its decision logic could be drafted hardware-free now, but the PRD's own
  FR-RL1 state vector includes `health`/`failure_eta`, which only the
  (undecided) LSTM produces — so a PRD-faithful, fully-tested fallback
  still depends on the LSTM task.
- Reusable infrastructure already exists and needs no new work: the frozen
  `DecisionMessage`/`RLAction` wire contract
  (`backend/app/schemas/contracts.py`) already defines P3's exact output
  shape (`health`, `failure_eta`, `rl_action`, `isolated`, `substituted`),
  and `RelayController.safe_off()` (`edge/actuation/relay.py`, P1) is a
  working, hardware-free-testable Safe-Stop action any P3 decision layer
  can call.
- Recommended eventual order, **not authorization to start**: (1) resolve
  U03/U04, (2) scope the rule-fallback decision logic if authorized, (3)
  implement LSTM, (4) wire self-heal/isolation, (5) resolve U06 and
  implement DQN + integrate the fallback, (6) resolve U05 and implement
  substitution/divergence, (7) scope the synthetic dry-run signature, (8)
  hardware-gated validation last.
- **No P3 file was created or modified. No P3 code exists in this repo.**

**Next session's first action should NOT be assumed to be coding.** Read
`P2_RESUME.md`, `CURRENT_STATE.md`, `TODO.md`, `DECISIONS.md` first, then
ask the user explicitly whether to: formally enter P3 (starting with
U03/U04), resolve one of the standing P2 decision-required items (λ, `c`,
FR-A4), or do something else. Do not default to P3 implementation, and do
not create a new decision (D016+) without the same explicit
propose-then-approve sequence used for D014/D015.

## 11. P3 scoping update (2026-08-31) — D016/D017 recorded, P3 STILL not started

**U03 and U04 are now resolved as decisions** — `DECISIONS.md` **D016**
(prognosis and digital-twin are two separate models; the twin is a single
channel-agnostic model, not per-channel; no architecture/hyperparameter
detail specified) and **D017** (synthetic simulator data approved for
**initial, hardware-free P3 development/testing only** — the existing
D005/D008 simulator + P2's injection framework are the initial synthetic
data source for digital-twin development, but their adequacy for
real-world reconstruction accuracy is explicitly **unvalidated**, not
claimed sufficient; prognosis training remains blocked, since no
degradation-trajectory generator exists or is specified by D017).

**Still open, unchanged by D016/D017:** U05 (`divergence_threshold` +
uncertainty-cap values), U06 (RL reward shaping), and the digital-twin's
uncertainty-estimation method (FR-H2) — none of these were resolved, and
none should be assumed.

**No P3 code has been created or modified.** D016/D017 are
documentation-only decisions about *architecture shape* and *initial data
source*, not authorization to implement. The next actionable P3 step is
still a decision (U05, U06, the uncertainty method, or scoping the digital
twin's self-supervised training/testing approach against the existing
simulator) — not code — and should still go through the same
propose-then-approve sequence used for D014–D017.
