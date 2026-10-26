# Evaluation results — 2026-10-26

Three measurements run on 2026-10-26 with the committed tooling, unmodified.
They are diagnostic evidence for the paper (O3, O10, NFR false-alarm
behaviour), not acceptance results. Every number below is reproducible with
the command shown; nothing was tuned to improve it.

---

## 1. Fault-vs-attack attribution (O3, target >= 85%)

`PYTHONPATH="backend;." python -m edge.eval.attribution_confusion synthetic`

All 8 `edge.injection` types on every channel over the module's default seeds
(240 labelled episodes plus 30 clean controls). Unit of scoring: the
attribution of the injected channel at the first window in which it is
flagged. **Simulated streams** (independent Gaussian channels): this measures
the attribution logic, not real-hardware accuracy.

| Truth \ predicted | fault | attack | none |
|---|---|---|---|
| fault (90) | 79 | 11 | 0 |
| attack (150) | 132 | 17 | 1 |
| clean control (30) | 26 | 4 | 0 |

**Episode accuracy: 96/240 = 40.0%** (current + vibration only: 45.0%; the
other four channels 37.5%, where D014 makes `attack` unreachable by
construction).

| Injection | Correct |
|---|---|
| drift / spike / stuck_at (faults) | 87% / 87% / 90% |
| bias / ramp / replay / constant spoof / stealth (attacks) | 10% / 13% / 17% / 10% / 7% |

**Reading:** the deployed `TrendSignPhysicsRule` labels nearly everything
`fault`, so attacks are rarely attributed as attacks even on the two channels
it covers. Combined with D030 (real physical events labelled `attack`), the
rule is not a working attribution method. This is the main open research
problem for the paper's central claim.

Bench capture (`python -m edge.eval.attribution_confusion bench
fault_injection_session.jsonl edge/eval/labels/fault_injection_2026-09-20.json`):
2/2 labelled fault episodes attributed `fault`, but 16 of the 73 windows
overlapping the ADXL335 tap said `attack`. n = 2 — a scored example, not an
accuracy estimate.

---

## 2. SWaT.A1 detection-stage ablation (O10)

`PYTHONPATH="backend;." python -m edge.eval.swat_ablation` (full dataset,
D011 split: fit on Normal_v1 only, evaluate on Attack_v0; 14,997 windows,
35 attack events; k neutralised, attribution not evaluated, per D011-C/D).

Best F1 per variant (threshold chosen post hoc on the same data — optimistic
for every row alike):

| Variant | thr | Precision | Recall | F1 | FPR | Events flagged (of 35) | within 3 windows |
|---|---|---|---|---|---|---|---|
| z-score baseline (no ML) | 0.95 | 0.799 | 0.687 | **0.739** | **0.024** | 13 | 8 |
| IF, identity filters (deployed) | 0.90 | 0.362 | 0.494 | 0.418 | 0.123 | 34 | 16 |
| IF + median | 0.90 | 0.359 | 0.481 | 0.411 | 0.121 | 35 | 17 |
| IF + low-pass | 0.95 | 0.548 | 0.562 | 0.555 | 0.065 | 33 | 12 |
| IF + median + low-pass | 0.95 | 0.554 | 0.544 | 0.549 | 0.062 | 34 | 13 |

At the deployed threshold 0.90: trust-only recall 0.817 / FPR 0.391 (35/35
events, 27 within 3 windows); IF-or-trust recall 0.842 / FPR 0.433 (35/35, 29
within 3 windows).

**Reading:**
- A per-channel z-score beats the deployed Isolation Forest at the window
  level by a wide margin — reviewers will ask why the IF is used.
- The IF's advantage is event coverage: it flags 34/35 distinct attacks
  against the z-score's 13/35. Window-level F1 rewards long, easy attacks;
  event coverage is closer to the operational goal. Report both.
- Low-pass filtering improves the IF (F1 0.418 -> 0.555, FPR halved) but the
  live system runs with identity filters.
- Trust adds coverage and speed (29/35 within 3 windows when OR-ed with the
  IF) at a large false-alarm cost.

---

## 3. Live false-alarm behaviour on real clean bench data (D031)

Replay of the real 7.18 h idle capture through the exact live composition
(`edge.main._build_p2_monitor`), varying only how much clean data the
detector is fit on:

| Fit | current Malicious | vibration Malicious | Channels falsely isolated |
|---|---|---|---|
| 5 windows (deployed until D031) | 25% of windows | 22% | 4 of 6 in 30 min |
| 20 windows | 84% | 21% | 6 of 6 |
| 60 windows | 52% | 18% | 6 of 6 |
| 10 min | reduced | 3% | several |
| 30 min | 0% | 0% | 1 (pressure, twice) |
| persisted baseline, hold-out | 0% | 0% | none (4.6% anomaly-flagged) |

**Correction:** `BENCH_LOAD_VALIDATION.md` §9's 0.1% false-positive rate was
measured after a 3.6 h fit and never described the deployed live system.
Report the hold-out numbers of whichever baseline is actually deployed.

---

## 4. Attribution on real bench streams: TrendSign vs operating-state (D034)

`PYTHONPATH="backend;." python -m edge.eval.attribution_bench_eval --idle-onsets 20 --cycling-onsets 4 --running-onsets 10`

Same live P2 composition, only the physics rule (and the physics-flags option)
swapped. Injections into three real bench captures: the 7.2 h idle capture
(20 onsets x 2 channels), the 19-min ON/OFF cycling capture, and the
2026-10-26 motor-running capture (64% of rows with the motor on; DHT22
dropouts carried forward, attribution reads only current and vibration).

Attacks are grouped by MEASUREMENT, per episode: does the injected reading
ever put the channel in the opposite motor state (a full window whose median
lands in the other determinate band)? That is the physically impossible case.
"Episode" verdict = attack if any flagged window in the episode was
attributed attack (scored on faults too, so false accusations count).

| Stream | Rule | Attacks crossing state -> attack | Attacks staying in state -> attack | Faults -> fault | False attack, clean channel-windows |
|---|---|---|---|---|---|
| idle 7.2 h | trend_sign (D013) | 55/119 (46%) | 38/96 (40%) | 63/78 (81%) | 0/4,742 (0.0%) |
| idle 7.2 h | **op_state + physics flags** | **120/120 (100%)** | 0/96 (0%) | 39/79 (49%)* | **0/4,742 (0.0%)** |
| cycling 19 min | trend_sign (D013) | 7/10 (70%) | 4/4 | 1/5 (20%) | 6/928 (0.6%) |
| cycling 19 min | **op_state + physics flags** | **12/12 (100%)** | 2/6 | **5/5 (100%)** | 7/928 (0.8%) |
| running 25 min | trend_sign (D013) | 57/68 (84%) | 35/59 (59%) | 16/41 (39%) | 35/1,594 (2.2%) |
| running 25 min | **op_state + physics flags** | **64/70 (91%)** | 2/59 (3%) | **36/42 (86%)** | **1/1,594 (0.1%)** |

\* All idle fault errors are drift, which is the same waveform as a ramp
attack; spike and stuck-at are 39/39 correct.

**Reading:**
- Operating-state attribution with physics flags identifies 91-100% of
  physically impossible falsifications, keeps genuine faults as faults
  (86-100% outside drift), and almost never accuses a clean sensor
  (0-0.8% of clean channel-windows).
- The trend-sign rule's apparent recall while running is false alarm: it
  labels 59% of in-state attacks and 61% of faults as attacks and raises
  2.2% false attacks on clean running data (D030 at scale). At idle it misses
  most attacks.
- Stated limits: drift == ramp; attacks that keep a reading in its true
  physical state (in-state spoof, small bias, stealth FDI, same-state replay)
  are physically consistent and not attributable by this rule; only the
  current/vibration pair can be attributed attack on this bench.
- Majority-vote ("settled") attribution is lower on noisy running data
  (48/70) because every attack's onset windows are labelled fault while
  half-injected; the episode verdict is the operational quantity.
