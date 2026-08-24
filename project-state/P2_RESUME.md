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

---

## 1. Current project status

- **P0 hardware-free:** VERIFIED/COMPLETE — offline four-service stack
  (simulator→Mosquitto→backend→WebSocket→frontend) + E2E latency probe
  (p95 3–5 ms). Hardware spikes (Pi/rig) still blocked.
- **P1 hardware-free:** COMPLETE — C1 driver abstraction, C2 sampler/ring buffer,
  C3 MQTT buffered-resume/LWT, C2→C3 runtime, C4 relay/watchdog. Physical gates
  blocked (need Pi/rig).
- **P2 FOUNDATION (plumbing):** COMPLETE — preprocessing/windowing, injection
  framework, Beta trust core + per-channel engine, attribution shell, pipeline
  orchestrator, real multivariate Isolation Forest, **and now all three trust
  signal providers (`c`/`k`/`h`) and `ChannelFlagPolicy` are implemented and wired
  end-to-end into `P2Pipeline`** (previously seams/undefined — see §2, §5). **Still
  unit/interface tests only** — none of this is dataset-validated.
- **P2 VALIDATION (acceptance):** **NOT complete.** All seams are now filled with
  real (but provisional/untuned) implementations, but no detection/trust/attribution
  **accuracy** has been validated; IF is untuned; `k`'s physics is an unvalidated
  heuristic; no dataset eval has run; no P2 acceptance test is satisfied. Diagnostics
  run (see §3) are probes, not acceptance.
- **U07 dataset feasibility (SWaT vs. WADI):** Research **COMPLETE** (2026-08-24,
  `U07_DATASET_FEASIBILITY_REPORT.md`); validation methodology **FROZEN**
  (`DECISIONS.md` D011). Conclusion: **SWaT primary, WADI fallback**, usable only
  to validate P2 *architecture/methodology* — **neither dataset contains our six
  bench channels**, neither has a motor-current+vibration pair, neither can
  satisfy O3. **SWaT/iTrust access was REQUESTED** (Decision A approved
  2026-08-24; a SWaT-only request was submitted externally by the user via the
  iTrust request form) — **awaiting iTrust's response.** WADI was NOT requested
  (held as the pre-approved fallback per D011); no dataset has been downloaded.
- **Hardware availability:** NO Raspberry Pi, NO bench rig attached. All P2 work
  is hardware-free; physical gates (P0/P1/P3/P6) remain blocked.
- **Safe to resume from this checkpoint?** **Yes.** Working tree clean; `main` and
  `origin/main` are identical at `4d8a281` (everything pushed, GitHub Actions
  GREEN on both jobs — see §9); deferrals explicit; no half-finished edit.
  **Do NOT treat P2 as complete** — resume at the first unresolved item (§7):
  waiting on iTrust's response to the submitted SWaT access request.

**Foundation/plumbing complete ≠ validation/acceptance complete.** Every seam
in the P2 pipeline is now filled with a real, working, provisional implementation;
none of it has been validated for accuracy against real data. Tuning, physics
validation, and dataset evaluation are all still pending on a data-access decision.

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
| `ChannelFlagPolicy` — variance-threshold window→per-channel flagging | `edge/anomaly/policy.py` | `57d434d` |
| P2Pipeline wiring: `record_window`/`record_outcome` calls to c/k/h before trust update | `edge/anomaly/pipeline.py` | `b0f0272` |

**Test totals (as of `b0f0272`, per that session's own checkpoint reports — not
independently re-run by this documentation update):** full edge suite **288
passed, 2 skipped** (broker-gated integration). **Passing unit/interface tests
do NOT equal P2 acceptance** — they exercise plumbing/math and prove the wiring
calls happen, not detection/trust/attribution accuracy.

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

## 4. Current P2 architecture

```
TelemetryMessage (frozen contract)
  → preprocessing            (edge/anomaly/preprocess.py: median→low-pass→
                              30-sample window→per-window min-max)   [REAL]
  → 30-sample Window
  → Isolation Forest         (edge/anomaly/iforest.py: multivariate, 180-dim,
                              empirical-CDF severity, required flag_threshold) [REAL, UNTUNED]
  → window anomaly result    (AnomalyResult: flag + severity∈[0,1])  [REAL]
  → ChannelFlagPolicy         (edge/anomaly/policy.py: variance-threshold
                              window-level → per-channel flags)      [REAL, provisional/untuned]
  → c/k providers record_window(); h provider record_outcome()       [REAL, wired in pipeline.py]
  → TrustEngine              (edge/trust/engine.py: per-channel Beta) [REAL engine,
                              fed by REAL c/k/h SignalProviders — all provisional/untuned]
  → AttributionEngine        (edge/anomaly/attribution.py: none/fault/
                              attack branch logic) [REAL logic, but PhysicsRule SEAM — no real rule]
  → WindowOutcome            (internal struct; NOT a wire contract)   [REAL]
```

**Real:** preprocessing, IF detector (untuned), anomaly result, `ChannelFlagPolicy`
(variance-threshold heuristic), all three `c`/`k`/`h` SignalProviders (provisional/
unvalidated), Beta math + per-channel engine, attribution branch logic, orchestrator
(fully wired), WindowOutcome. **Still a seam:** the `PhysicsRule` used by
`AttributionEngine` (real cross-sensor physics beyond `k`'s heuristic) — not
implemented. `NullDetector` remains as a placeholder detector; the real IF drops in
behind the same `AnomalyDetector` protocol.

**"Real" here means implemented and wired, not validated.** `ChannelFlagPolicy`'s
variance threshold and `k`'s trend-sign rule are both working code with no accuracy
claim — see §5.

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
| ChannelFlagPolicy (window→per-channel) | **RESOLVED (provisional)** — variance-threshold heuristic: flag channels whose in-window variance exceeds a `variance_factor`-scaled range (`edge/anomaly/policy.py`, `57d434d`; design notes in `project-state/CHANNELFLAGPOLICY_DESIGN_ANALYSIS.md`) | Implemented and wired; NOT derived from IF internals, NOT validated on real data | `variance_factor` (default 0.5) tuning on real labeled attacks (U07) |
| IF hyperparameters + flag threshold | UNTUNED (sklearn defaults; threshold required, unset) | No documented values; simulator can't calibrate cross-sensor behaviour | Tune on real clean baseline to a real FP/detection target |
| Normalization choice | per-window min-max (current); DEFERRED | Diagnostic favours train-fit on the simulator, but simulator is stationary/physics-free and structurally favours global | Decide on real SWaT/WADI/TEP (stationarity + operating-point drift) |
| U07: SWaT/WADI access + TEP fallback | **Feasibility research COMPLETE**, methodology **FROZEN** (`DECISIONS.md` D011: proxy channel mapping; `k` excluded from evidence; `AttributionEngine`/O3 deferred/BLOCKED; WADI localization check rejected; strict temporal split required). **Access REQUESTED** (Decision A approved 2026-08-24; SWaT-only request submitted externally by the user; WADI NOT requested, held as fallback) — **awaiting iTrust's response.** No dataset downloaded | Methodology frozen and request submitted; iTrust's response timing/outcome is unknown | Wait for iTrust. On grant: obtain the tag dictionary, proceed per §7. On denial/excessive delay: WADI (pre-approved fallback) or TEP (separate, undecided) |
| Realistic injection magnitudes/durations | FIXTURES only | §12.4 specifies none; couples to the (undecided) detector threshold | Set against real data / detector calibration; never as project specs invented here |
| P2 acceptance validation | NOT started | Depends on all of the above + a dataset | Run P2-ANOM-*/P2-TRUST-* + O3/O10 on real data and report honestly |

## 6. What is explicitly NOT complete

Do NOT let any of these be described as finished:

- reliable anomaly detection accuracy
- P2-ANOM-H2 (spike→fault) / P2-ANOM-H3 (constant-spoof→attack) acceptance
- P2-TRUST-H2 (spoofed sensor trust <0.4 within ≤3 windows) acceptance
- attribution accuracy (fault vs attack)
- O3 ≥85% attribution accuracy
- O10 confusion matrix / ablation results
- real dataset (SWaT/WADI/TEP) evaluation
- physical sensor validation (real sensor reads / INA219 pump current)
- physical relay / safe-stop validation
- on-Pi LSTM + Isolation Forest timing (<500 ms budget)
- any hardware-dependent gate (P0 spikes, P1 physical acquisition, P3 safety, P6 chaos/soak)

## 7. Exact recommended next sequence

Steps 2–6 of the original sequence (`h`, `c`, `k`, `ChannelFlagPolicy`, pipeline
wiring) are **DONE** — see §2/§5 and commits `c56cb4d`, `d1e6d48`, `691847f`,
`57d434d`, `b0f0272`. U07 feasibility research (step 7's prerequisite) is also
**DONE** (`U07_DATASET_FEASIBILITY_REPORT.md`), and **Decision A is also DONE**
— approved 2026-08-24; a SWaT-only iTrust access request was submitted
externally by the user the same day. What remains:

1. **Wait for iTrust's response** to the submitted SWaT access request. No
   further action is possible on this item until a response (grant, denial, or
   delay) arrives. Do NOT request WADI or TEP preemptively — WADI is the
   pre-approved fallback (D011) for if SWaT is denied/delayed; TEP remains a
   separate, undecided path. Do NOT choose the six SWaT tags (D011 B) until
   access is actually granted and the tag dictionary is in hand.
2. Once a dataset (or TEP substitute) is in hand: **tune IF** hyperparameters +
   flag threshold on **real clean** data.
3. **Revisit normalization** (per-window vs. train-fit/global vs. z-score) using
   real, non-stationary data — see the diagnostic findings in §3.
4. **Validate/re-tune** the `k` provider's trend-sign rule and the
   `ChannelFlagPolicy` `variance_factor` against real/labeled data (D010,
   `CHANNELFLAGPOLICY_DESIGN_ANALYSIS.md`).
5. Run **P2 acceptance tests** (P2-ANOM-*/P2-TRUST-*, O3/O10) and report
   honestly — noting per the U07 report that **O3 and the literal six-channel
   semantics remain bench-only** regardless of which dataset is chosen (U07
   report §11).
6. **Only then** update P2 status toward completion.

Do NOT add new/random architecture before these steps. Do NOT request WADI or
TEP access while the SWaT request is pending — that would need its own separate
approval, not an assumption from a delay.

## 8. Resume instructions for Claude Code

### IF I RETURN TO THIS PROJECT AFTER A FEW DAYS
- Read **this file first**, then `CURRENT_STATE.md` and `TODO.md` (then
  `DECISIONS.md`, `IMPLEMENTATION_LOG.md` as needed).
- Inspect `git status` and recent `git log` before touching anything.
- **Do NOT assume P2 is complete** — foundations/plumbing only; validation is not
  done.
- **Do NOT recreate** already-implemented components (§2) — c/k/h and
  `ChannelFlagPolicy` are real, working, provisional implementations now, not
  seams.
- **Do NOT redo** the corpus/U01/U02/U07 investigations unless the underlying
  `docs/` changed.
- **Continue from the first unresolved item** in §7 (start by checking whether
  iTrust has responded to the already-submitted SWaT access request — do NOT
  re-request SWaT, do NOT request WADI/TEP preemptively, and do NOT choose the
  six-tag SWaT mapping until access is actually granted).
- **Preserve all deferred decisions** (normalization deferral, λ pending,
  U02 real-physics validation, U07 access-request approval) — do not silently
  resolve them.
- **Ask for approval before making a genuinely new specification decision**
  (any physics relation, numeric threshold, c/k/h definition, dataset choice).
- Keep the per-step discipline: implement → run pytest/ruff/black/`git diff
  --check` → STOP and report → commit only on approval → do not push unless told.

## 9. Git checkpoint

- **Branch:** `main`.
- **Working tree (as of this update):** clean. `main` and `origin/main` are
  identical at `4d8a281` — nothing uncommitted, nothing unpushed.
- **CI status:** GitHub Actions is **GREEN** on `4d8a281` — both `Python lint +
  test` and `Frontend typecheck + test + build` jobs passed. `4d8a281` fixed a
  pre-existing CI dependency gap: `edge/requirements.txt` now declares
  `scikit-learn==1.4.*` (the already-documented TRD §02.2 pin, now activated),
  and `.github/workflows/ci.yml` now installs `-r edge/requirements.txt` in the
  Python job. This resolved a `ModuleNotFoundError: No module named 'numpy'`
  that had been silently breaking `pytest -q` in CI (masked earlier by an
  unrelated Black-formatting failure that stopped the job before pytest ran).
  **This was a dependency-declaration/CI-install-path fix only — no
  application logic changed.**
- **Latest relevant commits (newest first):**
  - `4d8a281` fix: install edge dependencies in CI
  - `c40221c` docs: update P2 resume checkpoint after SWaT request
  - `8ca3570` style: apply black formatting to P2 provider tests (NOT YET PUSHED)
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
