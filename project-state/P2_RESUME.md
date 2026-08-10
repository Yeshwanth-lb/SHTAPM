# P2 Resume Checkpoint

> Durable "when I come back" guide. Read this FIRST, then `CURRENT_STATE.md`,
> `DECISIONS.md`, `TODO.md`, `IMPLEMENTATION_LOG.md`. Authoritative product spec
> lives in `../CLAUDE.md` and `../docs/`. Written 2026-08-10. Documentation only —
> no code/state changed by this checkpoint beyond adding this file.

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
  orchestrator, real multivariate Isolation Forest. **Unit/interface tests only.**
- **P2 VALIDATION (acceptance):** **NOT complete.** No detection/trust/attribution
  accuracy validated; c/k/h undefined; physics rule undefined; no dataset eval;
  no P2 acceptance test satisfied. Diagnostics run (see §3) are probes, not
  acceptance.
- **Hardware availability:** NO Raspberry Pi, NO bench rig attached. All P2 work
  is hardware-free; physical gates (P0/P1/P3/P6) remain blocked.
- **Safe to resume from this checkpoint?** **Yes.** Working tree clean; foundations
  committed; deferrals explicit; no half-finished edit. **Do NOT treat P2 as
  complete** — resume at the first unresolved decision (§7).

**Foundation/plumbing complete ≠ validation/acceptance complete.** Everything
under P2 so far is signal-agnostic scaffolding behind seams; the real signals,
physics, tuning, and dataset evaluation are all still pending.

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

**Test totals (checkpoint):** full suite **265 passed, 5 skipped** (5 skips =
broker-gated integration; scikit-learn-gated diagnostic tests run only when
sklearn is present). Unit-only (excluding the two heavy diagnostic modules):
**257 passed, 5 skipped**. **Passing unit/interface tests do NOT equal P2
acceptance** — they exercise plumbing/math, not detection/trust/attribution
accuracy.

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
  → ChannelFlagPolicy seam    (window-level → per-channel flags)      [SEAM/STUB — not implemented]
  → TrustEngine              (edge/trust/engine.py: per-channel Beta) [REAL engine,
                              but fed by c/k/h SignalProvider SEAMS — signals UNDEFINED]
  → AttributionEngine        (edge/anomaly/attribution.py: none/fault/
                              attack branch logic) [REAL logic, but PhysicsRule SEAM — no real rule]
  → WindowOutcome            (internal struct; NOT a wire contract)   [REAL]
```

**Real:** preprocessing, IF detector (untuned), anomaly result, Beta math +
per-channel engine, attribution branch logic, orchestrator, WindowOutcome.
**Seams/stubs (NOT implemented):** `ChannelFlagPolicy` (window→per-channel
localization), the c/k/h `SignalProvider`s, the `PhysicsRule` (real cross-sensor
physics). `NullDetector` remains as a placeholder detector; the real IF drops in
behind the same `AnomalyDetector` protocol.

## 5. Explicitly unresolved decisions

**Do NOT invent physics or undocumented numeric values merely to make acceptance
tests pass.** Each below stays open until the stated input exists.

| Decision | Current status | Why unresolved | What is needed |
|----------|---------------|----------------|----------------|
| U01: `c` consistency definition | UNDEFINED (seam) | Docs name it + weight 0.4 only; a plausible constant spoof stays self-consistent, so a naive `c` floors trust at 0.4 (can't reach <0.4) | An operational `c` that detects the anomaly without double-counting `h`; likely couples to the anomaly/residual signal (FR-A1) |
| U01: `h` historical reliability definition/memory | UNDEFINED (seam) | Docs name it + weight 0.3 only; memory length unspecified | A slow long-run reliability signal (memory longer than the fast window) so colluders can't refill it instantly |
| U01: λ forgetting factor | λ=0.7 implemented as PENDING default | Analyzed (T₃=λ³<0.4), not a doc spec | Explicit approval to confirm 0.7 (or change) |
| U02: `k` / cross-sensor physics definition | UNDEFINED (seam) | Only current↔pressure named; no equation/direction/tolerance | A concrete relation + tolerance derived from real data, not invented |
| U02: current↔pressure problem / dataset channel mapping | OPEN | Bench pressure is an atmospheric PROXY; SWaT/WADI have real pressure but NO continuous motor current (pumps are on/off) → literal pair exists nowhere | Choose the real channel pair that instantiates FR-A2 (e.g. flow↔pressure / pump-state↔pressure) on the actual dataset; record as a deviation |
| ChannelFlagPolicy (window→per-channel) | SEAM, not implemented | IF is window-level; sklearn has no native per-feature attribution | A defensible localization method validated on real data — NOT derived from IF internals |
| IF hyperparameters + flag threshold | UNTUNED (sklearn defaults; threshold required, unset) | No documented values; simulator can't calibrate cross-sensor behaviour | Tune on real clean baseline to a real FP/detection target |
| Normalization choice | per-window min-max (current); DEFERRED | Diagnostic favours train-fit on the simulator, but simulator is stationary/physics-free and structurally favours global | Decide on real SWaT/WADI/TEP (stationarity + operating-point drift) |
| U07: SWaT/WADI access + TEP fallback | UNCONFIRMED | iTrust access is request-gated (lead time); not obtained | Request SWaT/WADI access, or commit to the documented TEP substitute (+ §12.4 injections) |
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

1. Review this checkpoint and the current `TODO.md`.
2. Implement/resolve **`h` (historical reliability)** carefully — slow long-run
   memory, distinct window from the fast trust update.
3. Resolve the **`c` consistency** signal **without double-counting `h`** (keep
   the historical term separate; `c` should reflect present-window consistency /
   residual, not history).
4. Resolve **`k` / cross-sensor physics** using the **real dataset/channel
   mapping** (§5 U02 row) — do NOT invent bench physics.
5. Implement the real **`ChannelFlagPolicy`** (window-level → per-channel),
   validated — not from IF internals.
6. Connect the real signals into the **existing** P2 pipeline (the seams already
   exist; do not rebuild architecture).
7. Obtain/use **SWaT/WADI** or the documented **TEP** substitute (U07).
8. **Tune IF** parameters + flag threshold on **real clean** data.
9. **Revisit normalization** (per-window vs train-fit) using real data.
10. Run **P2 acceptance tests** (P2-ANOM-*/P2-TRUST-*, O3/O10) and report
    honestly.
11. **Only then** update P2 status toward completion.

Do NOT add new/random architecture before these steps.

## 8. Resume instructions for Claude Code

### IF I RETURN TO THIS PROJECT AFTER A FEW DAYS
- Read **this file first**, then `CURRENT_STATE.md` and `TODO.md` (then
  `DECISIONS.md`, `IMPLEMENTATION_LOG.md` as needed).
- Inspect `git status` and recent `git log` before touching anything.
- **Do NOT assume P2 is complete** — foundations/plumbing only; validation is not
  done.
- **Do NOT recreate** already-implemented components (§2) — they exist behind
  seams.
- **Do NOT redo** the corpus/U01/U02/U07 investigations unless the underlying
  `docs/` changed.
- **Continue from the first unresolved item** in §7 (start with `h`).
- **Preserve all deferred decisions** (normalization deferral, λ pending,
  dataset-gating, U01/U02/U07) — do not silently resolve them.
- **Ask for approval before making a genuinely new specification decision**
  (any physics relation, numeric threshold, c/k/h definition, dataset choice).
- Keep the per-step discipline: implement → run pytest/ruff/black/`git diff
  --check` → STOP and report → commit only on approval → do not push unless told.

## 9. Git checkpoint

- **Branch:** `main`.
- **Working tree:** clean (this file is the only new/uncommitted change once
  added; nothing else modified).
- **Latest relevant commits (newest first):**
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
- **Push status:** the ten P2 commits above are on `origin/main` (pushed
  externally, not by this session). This checkpoint file is **not committed and
  not pushed** — commit only on approval; do NOT push.
