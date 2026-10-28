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

**Deployed configuration (D034 + D035 + D036)**, same episodes: crossing-state
attacks 120/120 idle, 12/12 cycling, 63/70 running; faults kept 39/79 idle
(drift), 5/5, 36/42; false attack on clean channel-windows 0/4,742,
1/928 (0.1%, was 7/928 with the D010/D033 k), 2/1,594 (0.1%).

---

## 5. Detection on SWaT with thresholds fixed from clean data (O10)

`PYTHONPATH="backend;." python -m edge.eval.swat_ablation` — adds a level-aware
IF (windows of globally standardised values) and the per-window max of the
z-score and low-pass IF severities. Thresholds 0.95 / 0.99 are each variant's
nominal 5% / 1% clean-flag rate from its own Normal_v1 fit: no attack labels
are used to choose them.

| Detector @ 0.95 | Precision | Recall | F1 | FPR | Events flagged / 35 | within 3 windows |
|---|---|---|---|---|---|---|
| IF, identity filters (deployed) | 0.418 | 0.332 | 0.370 | 0.065 | 32 | 15 |
| IF + low-pass | 0.548 | 0.562 | 0.555 | 0.065 | 33 | 12 |
| z-score baseline | 0.799 | 0.687 | **0.739** | **0.024** | 13 | 8 |
| IF on globally standardised windows | 0.766 | 0.651 | 0.704 | 0.028 | 23 | 6 |
| max(z-score, IF + low-pass) | 0.543 | **0.746** | 0.629 | 0.089 | **33** | **16** |

At 0.99: z-score F1 0.731 (6/35 events), global-z IF F1 0.729 with precision
0.997 but 2/35 events, max(z, IF+low-pass) F1 0.717 / FPR 0.025 / 24/35 events,
deployed IF F1 0.204.

**Reading:** window-level F1 and event coverage pull apart. The deployed
detector is the weakest IF option; the combined detector nearly doubles its
F1 at the same nominal threshold and flags the most attack events fastest; the
z-score is the most precise but misses 22 of 35 attacks. The live detector is
NOT changed yet: candidates must also be checked on bench data (next step).

---

## 6. Self-healing on real bench streams (O6, FR-H)

`PYTHONPATH="backend;." python -m edge.eval.self_heal_eval` — live composition
with the trained twin; crossing-state spoof and bias on `current`, truth known
because injections are synthetic on real data. (Run on D034 code, before D035
and D036; to be re-run.)

| | idle 7.2 h (16 attacks) | running 25 min (14 attacks) |
|---|---|---|
| isolated | 16/16 | 14/14 |
| time to isolate (median) | ~12 samples (~14 s) | 4-5 samples (~5 s) |
| share of attack served by the twin | ~80% | ~93% |
| error without healing | 0.6-0.8 A | 0.8 A |
| twin error vs truth (median) | 0.017 A | 0.44 A |
| released after the attack | not within 14 min (see D036 open item) | ~45 samples (~54 s) |

The running-state twin error reflects distribution shift: the twin was
trained on 2026-09-18 data.

---

## 7. Real physical events (guided session, 2026-10-26 23:07-23:21)

Plan with timestamps: `edge/eval/labels/real_events_2026-10-26_plan.txt`.
Capture via `edge/scripts/load_capture.py` (gitignored). The DHT22 was locked
up throughout, so temperature/humidity were filled from the same evening's
baseline capture; attribution reads only current and vibration. Deployed
configuration, persisted same-evening baseline:

| Real event | Attribution | Isolation |
|---|---|---|
| quiet idle | none / fault | none |
| motor run, untouched | 2 attack windows at switch-on, rest fault/none | none |
| tap ADXL, motor off | fault only | none |
| tap ADXL, motor running | fault only | none |
| ADXL power pulled, motor off (reads 8.18 g) | fault only | none |
| ADXL power pulled, motor running | fault only | vibration isolated (broken sensor) |

Before D036 the dead ADXL with the motor off was attributed attack in 22
windows and the normal run produced a false isolation; before D034 taps were
attributed attack (D030).

## 8. Where attribution stops: in-state attacks (research finding, 2026-10-27)

**Question.** The deployed attribution (D034-D038) labels attacks that push a
channel across a motor state correctly 75-99% of the time, but attacks that
keep the channel in its true state only 9-16%. Can a second witness close that
gap? The retrained current twin (D039) predicts current from vibration alone,
so a spoofed current that stays "plausibly running" should still disagree with
what vibration implies.

**Method.** Twin trained WITHOUT the 2026-10-27 cycling capture, run on it;
residual = twin prediction - measured current on steady running windows
(n = 236); in-state bias injected on running current.

| | value |
|---|---|
| clean residual, median / p99 / p99.9 | 0.059 / 0.469 / 0.479 A |
| windows over the clean p99.9, bias +0.1 / +0.2 / +0.3 / +0.4 A | 0.0 / 0.0 / 0.4 / 1.7 % |
| windows over the clean p99.9, bias +0.6 A | 72.0 % |

**Finding.** Analytic redundancy from vibration only exposes in-state
deviations of roughly 0.6 A and more (about +80% of running current). The
harness's in-state scenarios are far smaller by construction -- bias 0.02 A,
stealth capped at 0.02 A, a constant spoof pinned AT the true median -- below
the sensor's own noise, so no physical evidence on this bench separates them
from clean data. Likewise most misattributed faults are drift crossing a state
boundary, which is the same waveform as a ramp attack. On these scenario
definitions attribution is at the physical limit of the available sensors;
going further needs evidence that is not a sensor reading (sensor
attestation/signing, timing watermarks, a redundant sensor on the same
quantity).

**Consequence for O3 (>= 85% on labelled bench scenarios).** Report accuracy
separately for physically distinguishable scenarios (cross-state attacks and
faults) and for in-state ones, and state the limit, rather than a single
blended number. No in-state rule was added: a 0.6 A threshold rule would
catch only gross spoofs while adding a new false-alarm source.

---

## 9. Final baseline with the real DHT22 (2026-10-28)

All six channels as they will be demonstrated: DHT22, BMP280, INA219, ADXL335
real; gas simulated (labelled placeholder, D044). Motor switched at random by
hand (each ON/OFF >= 30 s, ON <= ~3.5 min). Capture `final_baseline.jsonl`
(gitignored; a copy is the Pi's replay fallback) + `final_decisions.jsonl`.
`python scripts/final_eval.py final_baseline.jsonl`, reports in
`results/final_baseline/`. Nothing tuned.

**A first 70-min recording was discarded.** The ADXL shifted on the first motor
run (idle read ~2.7 g instead of ~0.05 g, running the same 2.7 g), so the
motor-state rule could not tell on from off: 21% of clean channel-windows were
attributed `attack` and the learned bands were nonsense (idle <= 4.1 g).
`scripts/capture_check.py` now checks a recording at minute 5. The DHT22 lasted
that whole session with the motor cycling: two dropouts (~8 s, ~3 s), held at
the last good value (D045), no frame gaps.

**Capture.** 51.4 min, 2609 frames, no gaps over 2 s, 21 motor runs (on 47% of
the time); idle vibration 0.02-0.10 g, running 0.54-0.69 g per 5-min block;
one DHT22 dropout of 3 s. Running current ripples: 10-20% of samples in every
run read ~0.27 A against a 0.69 A median.

**Baseline hold-out** (fit on the first 80%, scored the last 493 clean
windows; installed on the Pi from this file):

| | value |
|---|---|
| windows anomaly-flagged (IF, threshold 0.90) | 98/493 (19.9%) |
| channel-windows attributed Malicious | 0 on every channel |
| channels isolated at the end | none |
| median clean trust | 0.75-0.83 (all >= 0.7, so every channel can be released, D037) |
| learned vibration bands | idle <= 0.142 g, running >= 0.487 g |
| band coverage, whole capture | idle 100% of 1055 steady windows, running 90% of 93 |

(The hold-out tail had no fully steady running window, because of the current
ripple above, so its running coverage is reported over the whole capture.)

**Attribution on this capture** (deployed D034-36 rule, 10 injections per
scenario on real data):

| | result |
|---|---|
| clean control: false `attack` | **0 / 2552 channel-windows (0.0%)**; false `fault` 170 (6.7%) |
| faults (spike, stuck-at, drift), settled | 24/27 (89%) |
| cross-state attacks (constant spoof, bias, replay), settled / episode | 27/44 (61%) / 31/44 (70%) |
| in-state attacks (spoof, bias, stealth) | 0/23 (physical limit, section 8) |
| ramp FDI | 3/9 (same waveform as a drift fault) |

**Self-heal on this capture** (current twin of D039, NOT trained on this
capture, so out of sample; 12 onsets each):

| | bias (cross state) | constant spoof (cross state) |
|---|---|---|
| isolated | 10/12 | 10/12 |
| time to isolate, median | 17.5 samples (~21 s) | 15 samples (~18 s) |
| share of attack served VIRTUAL, median | 52% | 74% |
| error without healing, median | 0.60 A | 0.57 A |
| twin error (healed), median | **0.079 A** | **0.12 A** |
| time to release, median | 38.5 samples | 38.5 samples |
| clean control | 0 false isolations | |

The twin removes 80-87% of the substitution error out of sample, so it was
not retrained (retraining on this capture would only make these numbers in
sample).

**Detector on this capture** (`detector_bench_eval`, running stream): the
deployed `if_identity` detects every injected fault (60/60) and attack
(120/120) at its 0.95 threshold, median delay 6 samples, at a 21.8%
window-level clean flag rate. Window flags alone are not alarms: attribution
and trust turn them into the 0% false-attack rate above.

Compared with section 8's figures on the 2026-10-27 capture (simulated DHT):
false attacks on clean data stay at zero and faults improve, while
cross-state attack attribution is lower (61-70% vs 75-99%) on this shorter
capture with longer motor runs.
