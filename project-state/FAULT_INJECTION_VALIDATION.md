# Real-hardware fault injection: first P2 detection-rate evidence (2026-09-20)

**Status:** Real-hardware measurement on the SHTAPM bench. This is the fault-
injection session `BENCH_LOAD_VALIDATION.md` §9 and `TODO.md`/`CURRENT_STATE.md`
both named as "the last major evidence gap" for AC2 and O2/O3/O10. It
partially discharges that gap and produces the first confusion-matrix-style
evidence the project has for detection on real (not synthetic, not SWaT)
hardware.

**It is NOT** a claim that AC2 or O2/O3/O10 now pass. Detection rate is
measured for the first time; attribution accuracy is measured and found
wanting, in a specific and now-explained way (§5). See `DECISIONS.md` D030.

---

## 1. What was run

One capture via `edge/scripts/load_capture.py` (bench diagnostic tooling —
not production, reads the same production drivers `edge/main.py` uses,
`shtapm.service` stopped during capture): `fault_injection_session.jsonl`,
619 samples, 728.5 s (12.14 min), all five real sensors (DHT22, ADXL335,
BMP280, INA219) plus a small brushed DC motor as load, switched **by hand** —
no relay, no actuation code involved.

Protocol: idle lead-in, then in sequence — unplug the DHT22, reconnect it,
tap the ADXL335, cover the BMP280 intake and breathe on it, switch the motor
on, let it run, then abruptly disconnect its power.

Fault timeline extracted purely from the data (no assumed timing) by the
newly-committed `edge/eval/bench_fault_timeline.py`:

| Event | Time | Result |
|---|---|---|
| DHT22 disconnect | t=113–190s (77s) | Clean fault: temp/humidity unhealthy, recovers |
| ADXL335 tap | t=268–327s, peak t=299s | Huge signal: activity 399 vs. baseline 0.82 (~490×) |
| BMP280 disturbance | — | Did not register (max deviation 0.4 hPa, noise-level) |
| Motor ON | t=562–658s | Current 0.9–1.7A; DHT22 corrupted again by motor EMI (same mechanism as `BENCH_LOAD_VALIDATION.md` §4, confirmed a second time on a different rig session) |
| Abrupt current disconnect | t=657.8s | Clean fault: 0.829A → 0.0A in one sample |

The DHT22 reconnect at t≈190s also produced a small incidental vibration
blip (t=184–191s) from handling the sensor while reseating it — a real event,
not part of the deliberate protocol, and a confound for §3 below.

## 2. Methodology for running P2 against this capture

Committed as `edge/eval/bench_fault_injection_eval.py` (mirrors
`bench_if_tuning.py`'s structure and discipline). Uses the real, unmodified
production components (`Preprocessor`, `IsolationForestDetector` at the live
`0.90` threshold, `SeverityThresholdFlagPolicy`, `TrendSignPhysicsRule`,
`ConsistencyProvider`, `CorrelationProvider`, `HReliabilityProvider`,
`TrustEngine`, `AttributionEngine`, `P2Pipeline`). Fit on the clean lead-in
segment only (temporal separation, D011-F discipline); the whole stream
evaluated forward.

Two methodology points worth recording, both caught and fixed before any
number below was trusted:

- **`gas` has no real sensor in this capture** (no MQ135 driver exists). It
  is filled with `edge.drivers.fake.realistic_raw`, using the registry's own
  documented fixture parameters — the *same* fake-signal generator
  `edge/main.py`'s live service already runs for this channel in production.
  A constant placeholder was tried first and rejected: it flagged nearly
  every window, because a fully-flat channel is exactly the variance=0.0
  pathology `DECISIONS.md` D013 already documents as "the most extreme
  possible low value" under ChannelFlagPolicy's own-baseline test. No claim
  is made about `gas` in the results below.
- **Segment/gap discipline.** Dropping unhealthy rows (the Sampler-equivalent
  step) leaves samples that were minutes apart sitting next to each other in
  the filtered list. `Preprocessor.process()` has no notion of a time gap and
  will build a 30-sample window spanning one — the same bug class
  `bench_twin_training.py` found and fixed for digital-twin training,
  independently rediscovered here. It matters doubly: in production,
  `LiveP2Monitor`'s rolling buffer can't span a real outage either, so
  segmenting at gaps reproduces real deployed behaviour, not just analytical
  hygiene. `bench_fault_injection_eval.py` splits the stream into
  contiguous segments at any gap over 5s and evaluates each independently.

## 3. Result: baseline false-positive rate on real, genuinely-clean data

On the clean lead-in (t=0–112s, 67 windows, before any deliberate fault): **7
of 67 windows flagged (~10.4%)**, almost entirely `current` during power-on
settling. This is a real transient (the INA219/motor circuit stabilizing),
not a bug, and a useful complement to `BENCH_LOAD_VALIDATION.md` §9's 0.1%
figure — that measurement came from a 7.18 h *idle* capture with no power-on
transient in it; this session's 10.4% during the first ~2 minutes after
power-up suggests the deployed 0.90 threshold is closer to its noise floor
right after startup than the idle-capture number alone implies.

## 4. Result: DHT22 dropout is architecturally invisible to P2 — confirmed

As expected from the frozen all-six-healthy contract: the Sampler withholds
the whole frame when any channel is unhealthy, so the 142 dropped rows during
this fault produce **silence**, not a bad value fed to the detector. P2
cannot flag what it never receives. This is a real, honest limitation, not a
bug in this analysis, and it is not something a future capture can fix —
detecting it would require a schema change (a per-channel health field),
which is out of scope here.

## 5. Result: ADXL335 tap — detected, but confounded; attribution mislabelled it

The moment telemetry resumes after the DHT22 recovers (t=191s), the pipeline
enters an almost continuously-flagged state (`temperature`/`pressure`/
`vibration`/`humidity` read anomalous for 150+ seconds) — plausibly
post-outage resettling plus the incidental reconnect jostle noted in §1, not
a clean detection of the tap in isolation. **A single time-to-detect figure
for the tap alone cannot be honestly reported**: it lands inside an
already-saturated window, and separating the two would require either a
cleaner capture (isolated fault episodes with quiet gaps between them, not
attempted here) or a causal model this analysis doesn't have.

What can be reported: `vibration` is flagged with high severity (0.91–1.00)
across many windows overlapping the tap, and in several of them —
windows overlapping t=235–360s — is attributed **`attack`**, not `fault`, by
`TrendSignPhysicsRule`. §6 explains why.

## 6. Result: motor ON + abrupt current drop — detected, with the same attribution issue

The motor's EMI knocks out DHT22 frames from ~t=563s to ~t=648s (two segments
of only 4 and 2 messages — too short to form even one 30-sample window), so
the steady motor-running state and the instant of the drop are mostly
unobserved, for the same architectural reason as §4.

The first window after telemetry resumes (t=648.4–685.1s, spanning the
t=657.8s drop) **is flagged**, with `current: fault` — correct attribution.
But the motor *turn-on* transition itself, at t=522–556s (before the
outage), got **`current: attack`** — a purely manual, physical action
mislabelled the same way as the tap.

## 7. The finding that matters more than any single detection: attribution mislabels real physical actions as attacks

Root cause, read directly from `edge/anomaly/physics_rule.py`
(`TrendSignPhysicsRule`, D013): it only ever compares `current` and
`vibration` trend direction across a window. If they disagree, whichever
deviates further from its own clean baseline is named the "suspect," and
`AttributionEngine` reports that channel as `attack`. There is no actual
physics model behind the label — the module's own header says so explicitly:
*"NOT a validated physics claim... provisional... unblocks AttributionEngine
wiring only"* (D013's own scope note).

This is not a bug: the rule is doing exactly what D010/D013 documented it
would do. What this session adds is the first **real-data confirmation**
that the documented risk is not theoretical: a tap on a sensor and a manual
motor switch — neither an attack — were labelled `attack` in multiple
windows, because "current and vibration trends disagree" cannot distinguish
a physical event from an injected spoof. See `DECISIONS.md` D030 for the
formal record and why no code is changed by this finding.

## 8. BMP280 — inconclusive

The cover/breathe disturbance did not produce a measurable pressure change
(max deviation 0.403 hPa, within noise). No real fault data exists yet for
this channel; a future session would need a stronger physical disturbance
(compressed air, a sealed chamber) to test it.

## 9. What this does and does not establish

- **Does:** produce the first detection-rate evidence on real hardware — two
  of three inducible real faults (tap, motor/current-drop) were detected
  with high severity by the deployed detector/threshold; confirms the DHT22
  dropout's architectural blind spot with real data; confirms, with real
  data for the first time, that `TrendSignPhysicsRule`'s attack/fault split
  is unreliable on genuine physical events, not just in theory.
- **Does not:** establish a clean quantitative detection-latency or
  attribution-accuracy percentage — the capture's fault episodes are close
  enough together, and confounded enough by the DHT22-recovery settling
  period, that isolating each event's own effect is not honestly possible
  from this one capture. Does not change AC2's status: AC2 remains **not
  satisfied** (see D030) — this session explains *why*, in more concrete
  terms than D015 could, but does not resolve it.
- **Suggests, not yet confirmed:** a future capture with longer quiet gaps
  between deliberate faults (e.g. 60s+ of idle between each) would let
  detection latency and attribution accuracy be measured per-event instead
  of only qualitatively — a candidate next bench session, not yet run.

## 10. Data and reproducibility

`fault_injection_session.jsonl` is gitignored (evidence input, not source) —
held on the bench Pi and the dev machine. Regenerate with
`edge/scripts/load_capture.py`; see `BENCH_LOAD_VALIDATION.md` §5 for the
preconditions that make a capture valid (service stopped, venv interpreter).

Analysis tooling committed this session, both runnable standalone:

- `edge/eval/bench_fault_timeline.py <capture>` — data-driven fault-episode
  extraction (§1's table).
- `edge/eval/bench_fault_injection_eval.py <capture>` — runs the real P2
  pipeline against the capture with correct segment/gap handling (§2–§6).
