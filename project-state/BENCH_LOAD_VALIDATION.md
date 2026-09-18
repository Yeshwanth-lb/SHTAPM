# Bench validation under motor load (2026-09-18)

**Status:** Real-hardware measurement on the SHTAPM bench. This is evidence for
`DECISIONS.md` D010's previously-unvalidated current↔vibration assumption, and a
characterisation of an EMI-induced DHT22 failure observed on this rig.

**It is NOT** a pump validation, a trained-model result, or an acceptance claim.
The load is a small brushed DC motor, not the project's pump under process
conditions.

---

## 1. What was run

Two captures via `edge/scripts/load_capture.py` (bench tooling — not production,
publishes nothing, reads the same production drivers `edge/main.py` uses):

| Capture | Samples | Channels | Purpose |
|---|---|---|---|
| `motor_load.jsonl` | 1,176 | current + vibration | first coupling test |
| `motor_load_full.jsonl` | 986 | + pressure, temperature, humidity | full five-sensor |

Hardware: 130-size brushed DC motor, powered from a 5 V USB supply, wired in
series through the INA219 shunt (VIN+ / VIN−). The ADXL335 was taped to the
motor body. `shtapm.service` was stopped during capture (see §5).

Motor was switched **by hand** — no relay, no actuation code involved.

Protocol: ~2 min OFF / ~3 min ON, repeated four times.

---

## 2. Result: current↔vibration coupling is real

`vibration activity` = rolling standard deviation (window 5) of the raw MCP3008
X/Y/Z counts, combined as a 3-axis magnitude. Raw counts are used rather than
`ADXL335Driver`'s g-value because that driver reports deviation from a baseline
captured at process start, which is not comparable across runs (§5).

| Capture | r | R² | ON/OFF activity ratio |
|---|---|---|---|
| `motor_load` (1,176) | 0.729 | 0.531 | 8.5× |
| `motor_load_full` (986) | 0.762 | **0.580** | 14.1× |

Current draw was consistent across all four ON episodes of the second capture:
0.872 / 0.791 / 0.774 / 0.789 A. OFF episodes read −0.0000 A.

**Contrast with the idle baseline.** A 7.18 h capture of the same rig with no
load (`telemetry_capture_5sensor_nominal.jsonl`, 21,799 frames) produced
R² = 0.019 for the same pair — no learnable relationship at all, because
`current` sat at ±1 LSB of ADC dither around zero for the entire capture.

### What this does and does not establish

- **Does:** on this bench, a load that draws current also produces mechanical
  vibration the ADXL335 detects, and the two co-vary strongly enough to be
  learnable. D010 chose the current↔vibration pair because it was "realizable on
  the bench today" but explicitly deferred validation ("requires real pump data
  … explicitly deferred"). That deferral is now discharged **for a DC motor load**.
- **Does not:** establish the relationship holds for the project's pump, under
  process load, across operating points, or over time. D010's trend-sign rule
  itself is still untuned; this measures that the underlying physical coupling
  exists, not that the rule reading it is correct.

---

## 3. Result: no other channel couples to load

Measured on the same capture, using only samples where each channel was healthy:

| pair | r | R² | n |
|---|---|---|---|
| current ↔ vibration | 0.7616 | **0.5800** | 986 |
| current ↔ pressure | 0.0754 | 0.0057 | 986 |
| current ↔ temperature | 0.0208 | 0.0004 | 686 |
| current ↔ humidity | −0.0694 | 0.0048 | 686 |

This is a useful negative result: it is measured evidence that
pressure/temperature/humidity carry essentially no information about load on
this rig, which constrains what any digital twin can legitimately reconstruct
`current` from. It is consistent with the physical setup — the BMP280 reads
atmospheric pressure (D010/D014) and the DHT22 reads ambient air, neither of
which the motor meaningfully influences.

---

## 4. Result: EMI-induced DHT22 failure, quantified

The brushed motor's commutator arcing corrupts the DHT22's bit-banged
single-wire protocol. Per-episode health from `motor_load_full.jsonl`:

| episode | motor | DHT22 healthy |
|---|---|---|
| 1 | OFF | 100.0% (103/103) |
| 2 | **ON** | 68.0% (83/122) |
| 3 | OFF | 99.1% (112/113) |
| 4 | **ON** | 45.3% (53/117) |
| 5 | OFF | 100.0% (114/114) |
| 6 | **ON** | 21.9% (23/105) |
| 7 | OFF | 100.0% (139/139) |
| 8 | **ON** | 18.1% (25/138) |
| 9 | OFF | 97.1% (34/35) |

Recovery is immediate and complete whenever the motor stops. Degradation
worsens across successive ON episodes (68% → 18%), not yet explained —
plausibly motor warm-up or brush seating, but not investigated.

`current`, `vibration` and `pressure` stayed 100% healthy throughout: I²C and
SPI arbitrate, the DHT22's GPIO protocol has no such protection.

### The dangerous failure mode this exposed

Before the fix committed at `db0b288`, EMI-corrupted DHT22 reads did **not**
always raise. The sensor sometimes returned exactly `0.0` on both channels,
which passed every check and published as healthy telemetry — observed live as
`{"temperature":0.0, "humidity":0.0, ...}` frames while the room was 29.2 °C /
59 %RH. All-zero bits carry a self-consistent checksum, so the library accepted
them.

Nothing downstream could distinguish those from measurements: they entered
trust scoring, anomaly detection, persistence and the dashboard as truth. A
sensor emitting plausible-shaped but wrong values instead of failing honestly is
the exact condition this project exists to detect, so the driver rejecting it is
a correctness fix, not a convenience.

**Operational consequence, unresolved:** because the frozen telemetry contract
carries no per-channel health field, the sampler can only publish a frame when
all six channels are healthy. With the motor running, the DHT22 drops out and
therefore *no telemetry publishes at all*. A live dashboard and a running motor
are currently mutually exclusive on this bench. Suppressing the motor's noise at
source (a 0.1 µF ceramic across its terminals is the standard fix) has not yet
been tried.

---

## 5. Measurement caveats that affect reuse

- **Vibration is baseline-relative.** `ADXL335Driver` captures an at-rest
  baseline on its first read after process start and reports deviation from it.
  Values are therefore only comparable *within* one process run, never across
  restarts. Analysis here uses raw ADC counts to avoid this entirely.
- **`shtapm.service` must be stopped during capture.** Two processes reading the
  DHT22 concurrently corrupt each other — the GPIO protocol has no arbitration.
  Observed as 100% DHT22 failure with the motor off, purely from contention.
- **The venv interpreter is required** (`.venv/bin/python`): the Adafruit
  libraries are not installed in system Python, where the driver silently
  degrades to "library missing" and reports a working sensor as failed.
- **Sampling rate is ~1 Hz**, far below the motor's vibration frequency. The
  activity metric therefore measures aliased sample-to-sample variation, not a
  spectrum. This is adequate for detecting *whether* the rig is vibrating, and
  inadequate for any frequency-domain claim.
- **A correction to an earlier claim:** contiguous `sample_seq` does **not**
  prove zero dropped frames. `sample_seq` increments only on *published* frames,
  so unhealthy ticks consume no number and leave no gap. The idle capture's
  reliability evidence is properly stated as: no inter-frame gap exceeded 5 s
  across 7.18 h.

---

## 6. Data

Captures are gitignored (`*capture*.jsonl`, and the motor files) — they are
evidence inputs, not source. Held on the bench Pi at `~/SHTAPM/` and on the dev
machine. Regenerate with `edge/scripts/load_capture.py`; see §5 for the
preconditions that make a capture valid.

---

## 7. Digital-twin training on this capture (2026-09-18)

Ran `edge/eval/bench_twin_training.py` against `motor_load_full.jsonl` using the
existing unmodified `LSTMTwinReconstructor` (D016 architecture) and D029's fixed
clean-baseline scale. 686 of 986 rows were complete (300 dropped where the DHT22
was unhealthy); enforcing genuine sample contiguity left 251 training and 120
held-out windows. Holdout is the chronological tail, never a random split.

Settings are fixtures, not project specifications: `hidden_size=32`, 40 epochs,
Adam at lr=0.01, seed 0.

### Result: `current` is reconstructable, `vibration` is not

| target | model RMSE | predict-the-mean RMSE | skill |
|---|---|---|---|
| `current` | 0.0985 A | 0.1818 A | **45.8%** |
| `vibration` | 0.4703 g | 0.4981 g | 5.6% |

Skill = fraction of the mean-predictor's error removed. `current` is genuinely
learnable from the other channels; `vibration` is not. The asymmetry is
plausible and worth stating: vibration is high-frequency mechanical noise
sampled at 1 Hz, so predicting it from a clean step-shaped current signal is a
much harder problem than the reverse.

**This makes `current` the substitutable channel on this rig.** No twin should
be deployed to substitute `vibration` on this evidence.

### A methodological warning worth recording

Before sample contiguity was enforced, `current` scored **61.0%** skill. With it,
**21.9%** at identical settings. The difference was entirely windows stitched
across DHT22 dropout gaps, presenting samples minutes apart as a continuous 30 s
history. The inflated number looked like the better result and was an artifact.
Any future harness consuming a capture with unhealthy rows must check contiguity
against original capture indices, not positions in the filtered list.

## 8. U05 (`divergence_threshold`) — measured, and NOT resolved

The threshold has been open since August as "data-gated: needs real
reconstruction-error statistics". Those statistics now exist, and they do not
support choosing a value.

Method mirrors production exactly: `DivergenceScorer` fits the residual's
mean/std on clean training windows, then z-scores held-out windows. Every
held-out window is clean, so any window at or above a candidate threshold is a
**false escalation** — a healthy sensor pushed toward Safe Pump-Stop.

| threshold | false escalations (n=120) | rate |
|---|---|---|
| 2.0σ | 10 | 8.3% |
| 3.0σ | 7 | 5.8% |
| 4.0σ | 6 | 5.0% |
| 6.0σ | 5 | 4.2% |

**Maximum clean-data divergence observed: 68.4σ.**

At 1 Hz, a 4.2% false-escalation rate is roughly one spurious Safe Pump-Stop
every 24 windows. No threshold in this range is deployable, and raising it
further only trades away the sensitivity the check exists for.

### Why, as far as the evidence shows

The residual distribution is heavy-tailed: the twin occasionally produces a
wildly wrong reconstruction. Motor ON/OFF transitions account for some of it
(windows ≥6σ span a mean current range of 0.557 A versus 0.030 A for the rest),
but **not all** — the single worst window (47σ) is steady-state, with a current
range of 0.0006 A. There is no single identified mechanism.

### Conclusion

**U05 remains OPEN.** The gate has changed rather than lifted: it was "no real
data exists", and is now "the reconstruction is not yet accurate enough for any
threshold to be responsible". Choosing 3.0σ here because it is a conventional
number would mean adopting a measured 5.8% false-escalation rate, which is not
a defensible basis for a safety escalation path.

Plausible next steps, none yet attempted: substantially more training data
(251 windows is very small); a capture with more ON/OFF cycles so transitions
are better represented; suppressing the DHT22 EMI at source so ~30% of load
samples stop being discarded; or revisiting whether divergence should be
evaluated per-window at all rather than over a longer horizon.

**Consequence for the self-healing loop:** substitution itself (twin replaces an
isolated channel) is supported by the 45.8% skill result for `current`. The
divergence *backstop* that escalates to Safe Pump-Stop is not. Wiring the loop
with escalation enabled on this evidence would produce frequent spurious stops.

---

## 9. U07: Isolation Forest false positives on real bench data (2026-09-18)

`edge/main.py`'s `_P2_DETECTOR_FLAG_THRESHOLD = 0.90` came from a full SWaT.A1
sweep (`P2_IF_SWAT_TUNING.md`). SWaT is a water treatment plant; that module's
own docstring says the value travels as a "flag the most unusual ~10%" policy
choice and "must be revisited once real bench clean/faulty/spoofed data exists
to validate this value directly (U07)".

Ran `edge/eval/bench_if_tuning.py` against the 7.18 h idle capture. Fit on the
first half, evaluated on the second — strict temporal separation, never
shuffled, matching D011-F's requirement for the SWaT harness. Every evaluation
window is clean, so every flag is a false positive by construction.

| threshold | false flags (n=10,871) | FP rate |
|---|---|---|
| 0.80 | 786 | 7.2% |
| 0.85 | 273 | 2.5% |
| **0.90 (deployed)** | **9** | **0.1%** |
| 0.95 | 0 | 0.0% |

**The deployed threshold is conservative on this bench: 0.1% false positives.**
False positives are spread thinly across channels (≤2 windows each), not
concentrated in one.

### The finding that matters more: the simulator is ~127× harsher than reality

Identical detector, threshold, preprocessing and fit/eval discipline, applied to
two clean data sources:

| source (all genuinely clean) | flagged | FP rate |
|---|---|---|
| `test_p2_acceptance.py`'s synthetic stream | 250 / 1,971 | **12.7%** |
| real bench idle capture | 9 / 10,871 | **0.1%** |

The synthetic stream is independent uniform noise per channel. Per-window
min-max then rescales each window to its own range, so structureless noise makes
every window look distinct. Real sensor data is temporally smooth and drifts
slowly, so consecutive windows resemble one another and the detector's
clean-baseline distribution is tight.

**Consequence for P2-ANOM-H1 and P2-ANOM-E1.** Both were recorded as "IF/
threshold/normalization not yet tuned against real clean-baseline data
(U07-gated)". That gate is now **discharged for false positives**, and the
answer re-characterises the failures: they are a property of the fixture's
synthetic stream, not of the detector on the hardware it actually runs on. Both
tests still fail, because both evaluate the synthetic stream — this is a
correction to the *diagnosis*, not to the result. Their xfail reasons now carry
these numbers.

### What is still NOT established

**Detection rate.** This measures only how often a healthy rig is wrongly
flagged. It says nothing about whether a real fault or attack would be caught,
because no capture contains labelled faults on real hardware. A threshold chosen
on false positives alone trades away sensitivity invisibly, so 0.90 is reported
here as *validated-not-to-over-flag*, never as *validated*.

Producing a detection-rate figure needs deliberate fault injection on the
physical rig — the natural next bench session, and the one that would let AC2
and O2/O3/O10 be attempted honestly.
