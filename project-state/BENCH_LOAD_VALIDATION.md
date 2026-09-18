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
