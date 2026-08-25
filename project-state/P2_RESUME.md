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
> matrix. **All of this is implemented and tested but UNCOMMITTED** — see §9.
> (Consolidated into `DECISIONS.md` D013 and this file on 2026-08-26, the day
> after the work itself; no additional code/tests changed during consolidation.)

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
- **P2 VALIDATION (acceptance):** **PARTIALLY done, for the first time.** The
  formal Doc06 P2-ANOM-\*/P2-TRUST-\* acceptance suite has now actually been
  written and run (`edge/tests/test_p2_acceptance.py`, D013) — 10/14 scenarios
  attempted, 6 PASS, 4 FAIL. See §1a for the full status matrix and which
  failures are mandatory implementation blockers vs. documented, honestly-
  disclosed validation limitations. IF remains untuned (U07-gated); the
  `PhysicsRule`/`k` physics are explicitly unvalidated heuristics; no real
  dataset eval contributes to any acceptance claim (SWaT is proxy/methodology
  evidence only, D011, and is now diagnostically complete — no further SWaT
  tuning planned).
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
- **Safe to resume from this checkpoint?** **Partially.** D013's code (Candidate
  B `ChannelFlagPolicy`, minimal `TrendSignPhysicsRule`, the full
  `test_p2_acceptance.py` suite) is implemented, tested, lint/format clean,
  and documented here — but **UNCOMMITTED** (see §9). Do NOT assume it is on
  `origin/main`; check `git status` before any further work.
  **Do NOT treat P2 as complete** — resume at the first unresolved item (§7).

**Foundation/plumbing complete ≠ validation/acceptance complete.** Every seam
in the P2 pipeline is now filled with a real, working, provisional implementation,
and — as of D013 — a real formal acceptance suite exists and has actually been
run against it. 6 of 10 attempted scenarios pass; the other 4 have precisely
diagnosed root causes (§1a). None of this constitutes a real-data accuracy
validation — that remains gated on hardware (bench rig) or further dataset work.

## 1a. Final P2 status matrix (as of D013, 2026-08-25)

All 10 attempted scenarios use real (non-stub) components end-to-end on
hardware-free simulator streams (`edge/tests/test_p2_acceptance.py`). 4 scenarios
(P2-PRE-\*, out of this table's scope) and P2-ANOM-S1 are not included — see notes.

| ID | Result | Root cause / mechanism | Category |
|----|--------|------------------------|----------|
| P2-ANOM-H1 | **FAIL** | IF+threshold+per-window-min-max clean-FP rate (~8% on this stream; ~22% on the original simulator diagnostic) | Documented validation limitation (U07-gated tuning) |
| P2-ANOM-H2 | **PASS** | Fixed by D013 Candidate B (spike now correctly localized) | — |
| P2-ANOM-H3 | **PASS** (fixture-sensitive) | Attribution=attack via the minimal `PhysicsRule`; verified ~50% (4/8 seeds) reliability — an approximately coin-flip side effect of the onset transition window's shape, not a validated capability | Documented validation limitation |
| P2-ANOM-E1 | **FAIL** | Window-level IF flag oscillates once triggered (upstream of ChannelFlagPolicy; same root cause as H1) | Documented validation limitation (U07-gated tuning) |
| P2-ANOM-E2 | **PASS** (fixture-sensitive) | Fault side deterministic (temperature, no physics rule applies); attack side ~60% (3/5 seeds) reliable | Documented validation limitation |
| P2-ANOM-S1 | **NOT ATTEMPTED** | No adaptive/stealth injection type exists in `edge/injection/` | **Mandatory implementation blocker** |
| P2-TRUST-H1 | **FAIL** | `c`'s empirical-CDF rank against its own training distribution produces near-uniform (not near-1.0) values for genuinely clean data, occasionally dragging trust <0.7 | Documented validation limitation |
| P2-TRUST-H2 | **FAIL** | Flagging mechanism fixed by D013 (68% vs. 13% post-onset flag rate) but `h`'s own EMA (D009, GAMMA=0.95, ~13-window half-life) cannot fall far enough in 3 windows regardless — a tension between two separately-approved decisions | Documented validation limitation (design tension, not missing code) |
| P2-TRUST-E1 | **PASS** | — | — |
| P2-TRUST-E2 | **PASS** | — | — |
| P2-TRUST-S1 | **PASS** | — | — |
| O3 (≥85% attribution accuracy) | **NOT ACHIEVABLE with current implementation** | `PhysicsRule` only ever names current/vibration (4 of 6 channels have no rule at all) and is only ~50–60% reliable even there | **Mandatory implementation blocker** (broader rule) + data-gated (no real physics data beyond the bench current/vibration pair exists anywhere, incl. SWaT/WADI, D010/U07) |

**Score: 6 PASS / 4 FAIL / 1 not attempted (S1) / O3 not achievable as implemented.**
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
| **`ChannelFlagPolicy` redesign ("Candidate B" — per-channel own-baseline two-sided test, D013)** | `edge/anomaly/policy.py` | **UNCOMMITTED** |
| **Minimal provisional `PhysicsRule` (`TrendSignPhysicsRule`, D013)** | `edge/anomaly/physics_rule.py` (new) | **UNCOMMITTED** |
| **First formal P2 acceptance suite (D013)** | `edge/tests/test_p2_acceptance.py` (new) | **UNCOMMITTED** |
| Unit tests for the above | `edge/tests/{test_policy,test_physics_rule}.py` | **UNCOMMITTED** |

**Test totals:** full `pytest edge/` (2026-08-25, post-D013): **327 passed, 4
failed, 2 skipped** (broker-gated integration). The 4 failures are exactly the
4 documented validation limitations in §1a — no unexpected regressions.
**Passing unit/interface tests still do NOT equal P2 acceptance** in general —
but as of D013, a REAL acceptance suite now exists and 6/10 attempted
scenarios genuinely pass it; see §1a for the honest, complete picture.

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
| U02: `PhysicsRule` for `AttributionEngine` | **RESOLVED (minimal, provisional)** — `TrendSignPhysicsRule` reuses D010's `k` heuristic verbatim, narrow scope (`edge/anomaly/physics_rule.py`; decision record `DECISIONS.md` D013) | Implemented and wired; verified ~50–60% attribution reliability even within scope; no rule for 4 of 6 channels | A broader rule (mandatory implementation blocker for real O3) + real physics data beyond current/vibration (data-gated, unavailable anywhere incl. SWaT/WADI) |
| ChannelFlagPolicy (window→per-channel) | **RESOLVED (provisional, redesigned — "Candidate B", D013)** — per-channel, own-baseline, two-sided empirical-CDF test: `fit()` on clean-baseline windows, flag if current variance is an outlier (high or low) vs. THAT channel's own history (`edge/anomaly/policy.py`; design notes in `project-state/CHANNELFLAGPOLICY_DESIGN_ANALYSIS.md`) | Implemented and wired; fixes the P2-ANOM-H2 spike-misdirection bug and improves P2-TRUST-H2's flag rate 5x; NOT validated on real data; does not help drift/ramp or replay shapes | `tail_fraction` (default 0.1) tuning on real labeled attacks (U07) |
| IF hyperparameters + flag threshold | UNTUNED (sklearn defaults; threshold required, unset). SWaT diagnostic campaign (§3a) found IF config changes do NOT materially improve detection even where real signal exists | No documented values; simulator/SWaT both show IF config is not the binding constraint | Tuning would need real bench clean-baseline data; SWaT evidence suggests limited further upside |
| Normalization choice | per-window min-max (current); confirmed **not changing** (§3a: PRD's own ≤3-window criteria favor per-window over aggregate-rate-favoring alternatives) | SWaT-based comparison complete (normalization study, §3a) — decision made, not deferred | None — resolved in favor of keeping the current default |
| U07: SWaT/WADI access + TEP fallback | **COMPLETE.** Feasibility research, methodology (D011), six-tag mapping (D012), harness (`edge/eval/swat_eval.py`), and a full diagnostic campaign (§3a) are all done. **Diagnostically complete** — no further SWaT work planned | D012 signal coverage identified as the dominant, decisive limitation | None planned unless explicitly requested |
| Realistic injection magnitudes/durations | FIXTURES only | §12.4 specifies none; couples to the (undecided) detector threshold | Set against real data / detector calibration; never as project specs invented here |
| P2 acceptance validation | **PARTIALLY started (D013)** — first formal suite written and run, 6/10 attempted scenarios PASS (§1a) | Real-data accuracy validation still requires hardware (bench rig) — SWaT/WADI structurally cannot provide it (D011) | Resolve mandatory blockers (§7a) that don't need hardware; accept the rest as hardware-gated |

## 6. What is explicitly NOT complete

Do NOT let any of these be described as finished:

- reliable anomaly detection accuracy on clean data (P2-ANOM-H1/E1 — U07-gated)
- consistent healthy-sensor trust ≥0.7 (P2-TRUST-H1 — `c`'s rank-noise, U07-gated)
- P2-TRUST-H2 within-3-window collapse (mechanism understood: D009 `h` EMA speed)
- reliable attack attribution — P2-ANOM-H3/E2 pass at committed seeds but are
  verified only ~50–60% reliable, not validated (D013)
- P2-ANOM-S1 (adaptive/stealth injection type does not exist — mandatory blocker)
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
suite, the `ChannelFlagPolicy` redesign, and a minimal `PhysicsRule` are all
**DONE** — see §1a/§2/§3a/§5. What remains, in order of what's actually
achievable without hardware:

1. **Commit D013's code** (`edge/anomaly/policy.py`, `edge/anomaly/physics_rule.py`,
   the four touched/new test files) — currently uncommitted; needs explicit
   approval per the established per-step discipline (see §9).
2. **Decide on the mandatory implementation blockers (§7a)** — a broader
   `PhysicsRule` (if O3 progress is wanted at all) and/or the P2-ANOM-S1
   adaptive injection type. Both are genuinely new code, not tuning; each
   needs its own explicit scoping/approval before implementation, consistent
   with "ask before changing approved architecture."
3. **Decide whether to address the documented validation limitations
   (§7a)** — `h`'s GAMMA/window-budget tension (P2-TRUST-H2), `c`'s rank-CDF
   noise (P2-TRUST-H1/H1-adjacent), IF's threshold/oscillation behavior
   (P2-ANOM-H1/E1). These touch already-approved decisions (D009, U01's `c`)
   and are validation/tuning questions, not missing capability — see §7a for
   what each would need before touching.
4. **Real bench-hardware validation** — the only way to close O2/O3/O4 and
   the full P2-ANOM-\*/P2-TRUST-\* acceptance table for real, since SWaT/WADI
   were always architecture/methodology-only (D011) and are now
   diagnostically exhausted for that purpose. Blocked on Pi/rig availability,
   unrelated to anything in this session.
5. **Only then** update P2 status toward completion.

Do NOT add new/random architecture before an explicit decision on step 2. Do
NOT re-open the SWaT track (step 3a is closed) unless explicitly requested.

## 7a. Mandatory implementation blockers vs. documented validation limitations

**Mandatory implementation blockers** — genuinely missing capability; no
amount of tuning or data closes these without new code:

- **A broader `PhysicsRule`.** The current `TrendSignPhysicsRule` (D013) can
  only ever name `current`/`vibration`, and is empirically ~50–60% reliable
  even there. O3 (≥85% attribution accuracy) is **structurally unreachable**
  with this rule, on any data, by construction — not a validation gap.
  Closing it needs a new rule design (bigger scope than "minimal"), which is
  itself only meaningfully validatable with real bench data (current/
  vibration is the only pair with any real-hardware plan at all).
- **P2-ANOM-S1's adaptive/stealth injection type.** No code for it exists
  anywhere in `edge/injection/`. Cannot be attempted at all until it's built.
- **Real bench hardware (Pi + rig).** Pre-existing, unrelated to D013 —
  blocks literal O2/O3/O4 and the full acceptance table regardless of
  anything achievable in software.

**Documented validation limitations** — the implementation exists, is wired,
and has been tested; the open question is accuracy/reliability against real
data or a parameter choice, not missing code:

- **P2-ANOM-H1/E1** (clean false-positive rate; oscillation once flagged) —
  IF + threshold + per-window-min-max normalization all exist and work;
  their accuracy on this specific combination is U07-gated (needs real
  clean-baseline data to retune against, not new code).
- **P2-TRUST-H1** (`c`'s rank-based noise) — `ConsistencyProvider` is fully
  implemented (U01 resolved, provisional); its empirical-CDF-against-own-
  training-distribution design is inherently noisy for genuinely clean data.
  A fix would mean reconsidering the definition, not writing a new component.
- **P2-TRUST-H2** (doesn't reach <0.4 in 3 windows) — both `ChannelFlagPolicy`
  (fixed, D013) and `h` (D009, fully implemented) work correctly; the gap is
  a genuine, now-precisely-identified tension between two separately-approved
  parameters (`h`'s deliberately-slow GAMMA=0.95 vs. this scenario's 3-window
  budget) — a parameter/design-tension question, explicitly not touched by
  D013 per instruction.
- **P2-ANOM-H3/E2's ~50–60% reliability** — the rule exists, is wired, and
  is empirically measured; its accuracy is honestly disclosed as
  chance-influenced, not a missing capability (the missing-capability version
  of this problem is the "broader PhysicsRule" mandatory blocker above).

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
  first: D013's code is likely still uncommitted (see §9).
- **Preserve all deferred decisions** (λ pending, `c`'s rank-noise, `h`'s
  GAMMA/window-budget tension, U02 real-physics validation beyond
  current/vibration) — do not silently resolve them.
- **Ask for approval before making a genuinely new specification decision**
  (any physics relation, numeric threshold, c/k/h/PhysicsRule redefinition,
  dataset choice) — this is exactly why D013 stopped short of touching D009's
  GAMMA even though it's the now-identified blocker for P2-TRUST-H2.
- Keep the per-step discipline: implement → run pytest/ruff/black/`git diff
  --check` → STOP and report → commit only on approval → do not push unless told.

## 9. Git checkpoint

- **Branch:** `main`.
- **Working tree (as of this update): DIRTY — D013 is uncommitted.**
  `git status --short`:
  ```
   M edge/anomaly/policy.py
   M edge/eval/swat_eval.py
   M edge/tests/test_policy.py
   M project-state/DECISIONS.md
   M project-state/P2_RESUME.md
  ?? edge/anomaly/physics_rule.py
  ?? edge/tests/test_p2_acceptance.py
  ?? edge/tests/test_physics_rule.py
  ```
  (`project-state/TODO.md` and `project-state/CURRENT_STATE.md` are also
  updated as part of this same consolidation pass — check `git status` for
  the current full list.)
- `main` and `origin/main` are identical at `60a4dbe` (the SWaT harness
  commit) — everything above is layered on top, uncommitted.
- **CI status:** last known green at `4d8a281` (pre-SWaT-harness); not
  re-verified since, since nothing has been pushed.
- **Latest commits on `main` (newest first):**
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
- **Push status:** **All commits pushed.** `main` and `origin/main` both point
  to `4d8a281` (verified 2026-08-24).
- **External state (not tracked by git):** a SWaT-only iTrust dataset-access
  request was submitted externally by the user on 2026-08-24, directly via the
  iTrust request form (outside this repo/session — no request/reference ID was
  captured here). Status: **awaiting iTrust's response.** No dataset has been
  downloaded. WADI has NOT been requested (remains the pre-approved fallback).
  TEP remains a separate, undecided alternative — it must NOT be silently
  substituted for SWaT if the response is slow or unfavorable; that would need
  its own explicit decision.
