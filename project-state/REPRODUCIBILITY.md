# REPRODUCIBILITY — how to regenerate every evidence artifact in this repo

> Companion to `CURRENT_STATE.md`/`DECISIONS.md`/`IMPLEMENTATION_LOG.md`. Those
> files narrate *what was found*; this file is the single place that lists
> the *exact command* to reproduce each hardware-free result yourself. Every
> command below is safe (hardware-free unless explicitly marked "Pi only"),
> non-destructive, and produces no actuation. Windows note: pytest resolves
> `PYTHONPATH=backend:.` fine via its own rootdir handling; direct
> `python -m module` invocation on native Windows Python needs the
> semicolon form, `PYTHONPATH="backend;."` — both are shown where relevant.

## 1. Full test suites (regression baseline)

```
# edge/ (hardware-free; ~1600+ tests, ~7 min)
PYTHONPATH=backend:. python -m pytest edge/ -q

# backend/ (needs fastapi/sqlalchemy/jose/passlib installed; ~160 tests, <1 min)
PYTHONPATH=backend:. python -m pytest backend/ -q
```
Expected shape (as of commit `12f38e5`): edge — all tests pass, a small fixed
set of MQTT-broker-gated skips, 4 pre-existing documented P2 xfails, 0
failures. backend — all tests pass, 2 broker-gated skips, 0 failures. Any
new failure is a real regression, not expected noise.

## 2. U06 diagnostic reports (simulation-only — see each report's own
`model_status`/`execution_mode` self-labeling; none of this is a threshold,
verdict, or real-world claim)

```
PYTHONPATH="backend;." python -m edge.eval.u06_diagnostic_report
PYTHONPATH="backend;." python -m edge.eval.u06_seed_repetition_report
PYTHONPATH="backend;." python -m edge.eval.u06_dqn_evaluation_report          # requires torch
PYTHONPATH="backend;." python -m edge.eval.u06_dqn_augmented_diagnostic_report # requires torch; degrades gracefully without it
```
Each of the 8 remaining `_injected_*` seed-repetition report siblings follows
the same `python -m edge.eval.u06_seed_repetition_report_<injection>` pattern
— see `edge/eval/` for the exact module names.

**Already-verified finding worth knowing before re-running:** `baseline_policy`
(rule-based) shows `false_isolation_rate=1.0` on every evaluated scenario;
the diagnostic DQN policy shows `false_isolation_rate=0.0` but
`missed_fault_rate=1.0` on the one scenario with a real missed-fault
opportunity (`injected_current_constant_spoof`) — a degenerate pair at
opposite extremes, recorded as the evidentiary basis for `DECISIONS.md`'s
"U06 — Threshold/Weight/World-Inert Non-Resolution Record". This is
internal diagnostic bookkeeping evidence only, not a real-world claim (see
that record for the full caveat).

## 3. Driver registry + realistic fake-sensor behavior (hardware-free)

```
PYTHONPATH=backend:. python -m pytest edge/tests/test_driver_registry.py edge/tests/test_fake_realistic.py -v
```
To see realistic (non-flat) fake signals directly: construct
`edge.drivers.registry.resolve_channel_specs_from_env(defaults, env={"SHTAPM_FAKE_SIGNAL_MODE": "realistic"})`
then `build_drivers(...)` and call `.read()` repeatedly — see
`edge/tests/test_driver_registry.py`'s own tests for a worked example.

## 4. decision_diagnostic publisher + backend ingestion (hardware-free)

```
PYTHONPATH=backend:. python -m pytest edge/tests/test_decision_diagnostic.py edge/tests/test_edge_main_p2_wiring.py -v
PYTHONPATH=backend:. python -m pytest backend/tests/test_decision_diagnostic_consumer.py backend/tests/test_decision_diagnostic_persistence.py backend/tests/test_decision_diagnostic_sink_wiring.py -v
```
These prove the publish→ingest→persist→REST path end-to-end without any
broker or hardware — `FakeMsg`/`FakeClient` fixtures stand in for paho/MQTT.

## 5. Real-hardware bench validation (Pi only — cannot be reproduced off-Pi;
listed here as the exact reference, not a claim it can be re-run from a
dev machine)

```
# On the Raspberry Pi, with ADXL335 wired to MCP3008/SPI0 CE0:
export DEVICE_ID=pump-01
export SAMPLE_RATE_HZ=1
export EDGE_MQTT_HOST=localhost
export EDGE_MQTT_PORT=1883
export P2_FIT_WINDOW_COUNT=5
PYTHONPATH=backend:. python edge/main.py
```
Last confirmed: commit `054caa6`, 2026-09-07 — see `IMPLEMENTATION_LOG.md`'s
2026-09-07 entry for the full observed-fields record and its explicit
"Not claimed" section. **No accuracy, calibration, or validation claim is
implied by re-running this** — it demonstrates the pipeline runs and
publishes, nothing about the correctness of its outputs.

## 6. U05 bench-capture offline analysis (infrastructure ready; no real
capture exists yet — see `DECISIONS.md`'s U05 entries)

```
PYTHONPATH=backend:. python -m pytest edge/tests/test_u05_capture_loader.py edge/tests/test_u05_divergence_analysis.py -v
```
These are hardware-free, fixture-only tests of the loading/windowing/
residual/scoring *infrastructure* — they prove the pipeline mechanics, not
any real-world result. Once a real bench capture file exists (per §5), the
actual analysis is:

```python
from edge.eval.u05_capture_loader import load_telemetry_capture, windows_from_capture, ordered_messages
from edge.eval.u05_divergence_analysis import compute_residuals, score_residuals
from edge.pipeline.divergence import DivergenceScorer
from edge.anomaly.preprocess import Preprocessor

preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0)  # matches edge/main.py's own identity config
with open("telemetry_capture_nominal.jsonl") as f:
    nominal = load_telemetry_capture(f)
windows = windows_from_capture(nominal, preprocessor)
messages = ordered_messages(nominal)

twin = ...  # a real, caller-supplied TwinReconstructor -- e.g. LSTMTwinReconstructor;
            # NOT trained on real data anywhere in this repo yet -- see module docstring
residuals = compute_residuals(windows, messages, twin)

scorer = DivergenceScorer()
scorer.fit(residuals)  # fit ONLY on a capture segment you consider clean/nominal

# Score a second (e.g. fault) capture the same way, then:
summary = score_residuals(other_capture_residuals, scorer)  # descriptive stats only -- no threshold
```
`score_residuals` reports mean/min/max z-score per channel — **never a
threshold, verdict, or fault/nominal label**. Choosing `divergence_threshold`
from this evidence remains a separate, explicit human decision (U05).
`compute_residuals`/`score_residuals` invent no reconstruction algorithm,
divergence formula, or numeric value — they only wire together the
already-approved `TwinReconstructor` seam and `DivergenceScorer` (D018 pt.1)
over real captured data.

## What this file is NOT

Not a claim that any number produced by section 2 is validated, accurate,
or production-ready (see each report's own `model_status`/`execution_mode`
fields and `DECISIONS.md`'s U06 records). Not a substitute for U05's real
bench/hardware requirement (`divergence_threshold` remains data-gated — no
command here can produce that evidence; it needs a real fault/nominal
telemetry capture, not a simulation run). Not a P5/P6/P7 reproduction guide
— those phases have no implementation yet to reproduce.
