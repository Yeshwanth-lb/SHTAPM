"""SHTAPM edge acquisition runtime — mixed hardware/fake drivers.

Runs the C1→C2→C3 pipeline with:
  - Real DS18B20 temperature probe via the kernel 1-Wire interface (GPIO4)
  - Fake drivers for the remaining channels (vibration, pressure, humidity,
    gas, current)

    DS18B20 + fake drivers → Sampler → TelemetryMessage → ResilientTelemetryPublisher → Mosquitto
                                                        ↘ LiveP2Monitor (observe-only, see below)

DS18B20 is real because it's the only sensor currently wired to the Pi —
ADXL335, BMP280, INA219, and DHT22 are implemented (edge/drivers/adxl335.py,
bmp280.py, ina219.py, dht22.py, each independently hardware-validated
earlier) but temporarily physically disconnected from this bench, so they'd
be permanently unhealthy here and block every frame (Sampler.sample_once()
requires all six channels healthy). When they're reconnected, re-add their
imports and `drivers[channel] = XDriver()` lines exactly as before (see git
history: commits d419d6b, 85bbe42, 43f2a54/e35ca5b, and the INA219 wiring
predating this file's docstring) — no other change needed.

The frozen six-channel telemetry contract is preserved. Thin by design
(env + wiring + signals) — the logic lives in the tested runtime/sampler/publisher.

P2 MONITORING (P0 gap-closure item 1 — observe-only, added on top of the
above, changes nothing about it): every healthy frame is also fed to a
``LiveP2Monitor`` (edge/pipeline/monitor.py) via ``AcquisitionRuntime``'s
optional ``on_healthy_frame`` hook. This runs the real, unmodified
``P2Pipeline`` (preprocess → anomaly → trust → attribution) and logs each
``WindowOutcome`` — it does NOT isolate a channel, does NOT actuate, does NOT
publish a decision/ledger message, and cannot affect telemetry: the hook is
wrapped in try/except inside the runtime, so a monitoring bug can never stop
or crash publishing. See edge/pipeline/monitor.py's docstring for exactly
which P2 components are used and why (NullDetector — no calibrated threshold
exists yet; ConsistencyProvider bootstrapped on ``P2_FIT_WINDOW_COUNT`` clean
live windows — required, no default; a single-window bootstrap was found to
collapse the consistency signal to a binary 0.0/1.0 output even on clean
data, see the module docstring for the fix).

FR-RL4 ISOLATION DECISION (decision-only slice, also observe-only): each
logged ``WindowOutcome`` is additionally passed through
``edge/pipeline/isolation_fallback.decide_isolation`` — a STATELESS,
deterministic classification of each channel's current ``TrustBand``
(MALICIOUS -> isolation candidate; Suspicious/Trusted -> not). This is
logged alongside the P2 outcome and nothing else: it does NOT call
``process_isolated_channels``, ``SelfHealOrchestrator``, actuation, ledger,
or MQTT/decision publishing.

FR-RL4 FOLLOW-UP — PERSISTENT TRACKING (still decision-only, still
observe-only): a single ``IsolationFallbackTracker`` (edge/pipeline/
isolation_tracker.py) wraps the stateless decision above with cross-cycle
memory — a channel seen Malicious once stays reported as a persistent
isolation candidate in later cycles even if its trust recovers, since no
real ``SelfHealOutcome`` recovery confirmation is wired into the live path
(no digital-twin reconstruction or divergence threshold exists yet — see
the tracker module's own docstring). This NEVER claims recovery occurred,
adds no threshold/cooldown/cap, and — like everything else in this
section — never calls process_isolated_channels/SelfHealOrchestrator/
actuation/ledger/MQTT/dashboard code.

RAW-VALUE PLUMBING (integration-readiness prep, still observe-only): each
outcome is also paired with the exact raw per-channel values for that same
window (edge/pipeline/monitor.py's ``RawChannelValues``, sourced from the
buffered ``TelemetryMessage`` — never reconstructed/normalized) and logged
concisely. This is preparatory only: nothing here calls
process_isolated_channels or SelfHealOrchestrator, and no twin, divergence
threshold, uncertainty policy, cooldown, hysteresis, isolation cap,
actuation, GPIO, relay, ledger, MQTT, or dashboard logic is added by it.

    PYTHONPATH=backend:. python -m edge
"""

from __future__ import annotations

import logging
import os
import signal
import time

from app.schemas.contracts import CHANNELS

from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.runtime import AcquisitionRuntime
from edge.acquisition.sampler import Sampler
from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.detector import NullDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.drivers.ds18b20 import DS18B20Driver
from edge.drivers.fake import fake_drivers
from edge.pipeline.isolation_fallback import decide_isolation
from edge.pipeline.isolation_tracker import IsolationFallbackTracker
from edge.pipeline.monitor import LiveP2Monitor, RawChannelValues
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

log = logging.getLogger("shtapm.edge.main")

# Plausible steady-state constants for fake sensors (dev only — not authoritative specs).
# The "temperature" value is a placeholder; replaced by the real driver below.
# vibration/pressure/humidity/gas/current are fake for now — see module docstring
# (ADXL335/BMP280/INA219/DHT22 are implemented but currently physically disconnected).
_DEV_VALUES = {
    "temperature": 26.0,  # Placeholder; replaced by DS18B20Driver
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.0,
}


def _required_env_int(name: str) -> int:
    """Read a required integer env var — raises with a clear message if
    unset, per TRD §02.7's "missing var → clear boot error naming it"
    acceptance criterion. No default is invented for values this project
    has not specified (see .env.example)."""
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"{name} is required (see .env.example) — no default is invented")
    return int(value)


def _build_p2_monitor(*, fit_window_count: int) -> LiveP2Monitor:
    """Compose the real (non-stub) P2 pipeline for observe-only live
    monitoring. See edge/pipeline/monitor.py's docstring for exactly why
    each component needs no invented threshold/calibration to run this way,
    and for the ``fit_window_count`` buffer-size derivation."""
    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0)  # identity filters;
    # median_kernel/low_pass_alpha have no documented spec value (see
    # edge/anomaly/preprocess.py) — 1/1.0 are the module's own documented
    # identity settings, not an invented smoothing amount.
    c_provider = ConsistencyProvider()
    pipeline = P2Pipeline(
        preprocessor=preprocessor,
        detector=NullDetector(),
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(TrendSignPhysicsRule()),
        c_provider=c_provider,
        k_provider=CorrelationProvider(),
        h_provider=HReliabilityProvider(),
        flag_policy=SeverityThresholdFlagPolicy(),
    )
    # One tracker per LiveP2Monitor instance (edge/pipeline/isolation_tracker.py)
    # -- persistent, cross-cycle isolation-candidate memory for THIS pipeline
    # only; a fresh _build_p2_monitor() call gets a fresh, independent tracker.
    isolation_tracker = IsolationFallbackTracker()

    def _on_outcome(outcome: WindowOutcome) -> None:
        _log_window_outcome(outcome, isolation_tracker)

    return LiveP2Monitor(
        preprocessor=preprocessor,
        pipeline=pipeline,
        c_provider=c_provider,
        fit_window_count=fit_window_count,
        on_outcome=_on_outcome,
        on_raw_values=_log_raw_values,
    )


def _log_window_outcome(
    outcome: WindowOutcome, isolation_tracker: IsolationFallbackTracker
) -> None:
    """Monitoring-only: log preprocessing/anomaly/trust/attribution, the
    stateless FR-RL4 isolation decision, and the persistent FR-RL4 tracking
    result. Never isolates a channel for real, actuates, or publishes
    anything — see edge/pipeline/{isolation_fallback,isolation_tracker}.py."""
    trust_summary = ", ".join(
        f"{ch}={outcome.trust[ch].trust:.3f}/{outcome.trust[ch].band.value}" for ch in CHANNELS
    )
    attribution_summary = ", ".join(
        f"{ch}={outcome.attribution[ch].attribution.value}" for ch in CHANNELS
    )
    log.info(
        "P2 window[%d:%d] anomaly=%s(sev=%.3f) trust={%s} attribution={%s}",
        outcome.window.start_index,
        outcome.window.end_index,
        outcome.anomaly.flag,
        outcome.anomaly.severity,
        trust_summary,
        attribution_summary,
    )

    decision = decide_isolation(outcome)
    log.info(
        "FR-RL4 isolation decision (stateless, log-only): candidates=%s reasons={%s}",
        sorted(decision.isolated_channels) or "none",
        ", ".join(f"{ch}: {reason}" for ch, reason in decision.reasons.items()),
    )

    tracked = isolation_tracker.update(outcome)
    log.info(
        "FR-RL4 isolation tracking (persistent, log-only): "
        "candidates_this_cycle=%s tracked_channels=%s reasons={%s}",
        sorted(tracked.candidates_this_cycle) or "none",
        sorted(tracked.tracked_channels) or "none",
        ", ".join(f"{ch}: {tracked.reasons[ch]}" for ch in CHANNELS if ch in tracked.reasons)
        or "none",
    )


def _log_raw_values(outcome: WindowOutcome, raw: RawChannelValues) -> None:
    """Monitoring-only: log the exact raw (pre-normalization) per-channel
    values for the same window that produced `outcome`, for traceability.
    Not consumed by anything -- no isolation, actuation, or publish. See
    edge/pipeline/monitor.py's RawChannelValues docstring."""
    values_summary = ", ".join(f"{ch}={raw.values[ch]:.3f}" for ch in CHANNELS)
    log.info(
        "P2 raw values[%d:%d] (ts=%s, seq=%d): {%s}",
        outcome.window.start_index,
        outcome.window.end_index,
        raw.ts,
        raw.sample_seq,
        values_summary,
    )


def main() -> None:
    device_id = os.environ.get("DEVICE_ID", "pump-01")
    rate_hz = float(os.environ.get("SAMPLE_RATE_HZ", "1"))
    host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    port = int(os.environ.get("EDGE_MQTT_PORT", "1883"))
    p2_fit_window_count = _required_env_int("P2_FIT_WINDOW_COUNT")

    # Create fake drivers for five channels (vibration, pressure, humidity, gas, current)
    drivers = fake_drivers(_DEV_VALUES)

    # Replace the fake temperature driver with real DS18B20 (kernel 1-Wire driver, GPIO4) —
    # the only sensor currently physically connected; see module docstring.
    drivers["temperature"] = DS18B20Driver()

    sampler = Sampler(device_id=device_id, drivers=drivers)
    publisher = ResilientTelemetryPublisher(device_id=device_id, rate_hz=rate_hz)
    publisher.start(host, port)
    p2_monitor = _build_p2_monitor(fit_window_count=p2_fit_window_count)
    runtime = AcquisitionRuntime(
        sampler=sampler,
        publisher=publisher,
        rate_hz=rate_hz,
        on_healthy_frame=p2_monitor.on_frame,
    )

    running = {"go": True}

    def _stop(*_a: object) -> None:
        running["go"] = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    print(
        f"[edge] MIXED HW/DEV: real DS18B20 (temperature) + fake drivers "
        f"(vibration, pressure, humidity, gas, current) → "
        f"{publisher.telemetry_topic} at {rate_hz} Hz (Ctrl-C to stop) "
        f"[P2 monitoring: observe-only, no isolation/actuation/publish]"
    )
    try:
        runtime.run(should_continue=lambda: running["go"], sleep=time.sleep)
    finally:
        runtime.stop()
        print("[edge] stopped (status offline)")


if __name__ == "__main__":
    main()
