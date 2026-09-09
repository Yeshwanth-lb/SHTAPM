"""SHTAPM edge acquisition runtime — configuration-driven hardware/fake drivers.

Runs the C1→C2→C3 pipeline with one ``SensorDriver`` per frozen channel,
selected via ``edge.drivers.registry`` from a declarative per-channel
``DriverSpec`` table (``_DEFAULT_CHANNEL_SPECS`` below) rather than
hand-written ``drivers[channel] = XDriver()`` lines:

    registry.build_drivers(...) → Sampler → TelemetryMessage → Publisher → Mosquitto
                                                              ↘ LiveP2Monitor (observe-only)

``_DEFAULT_CHANNEL_SPECS`` matches this bench's actual wiring — THREE real
channels across two physical sensors, three fake constants:

  channel      sensor / interface                       driver
  ----------   --------------------------------------   ----------------------
  temperature  DHT22 ambient air, GPIO17 (shared)       DHT22AdafruitTemperature
  humidity     DHT22 %RH, GPIO17 (shared)               DHT22Adafruit
  vibration    ADXL335, MCP3008 CH0-2 over SPI0 CE0     ADXL335
  pressure     — (BMP280 implemented, not connected)    fake constant 1013.0
  gas          — (no MQ-135 driver implemented)         fake constant 150.0
  current      — (INA219 implemented, not connected)    fake constant 0.0

TEMPERATURE + HUMIDITY BOTH COME FROM THE ONE DHT22 (GPIO17, Adafruit
CircuitPython backend, ``use_pulseio=False`` — edge/drivers/dht22_adafruit.py,
NOT the kernel-IIO edge/drivers/dht22.py, which remains in the repo unused;
see that module's docstring for why). This is the APPROVED project
configuration per the supervisor decision recorded as D028 in
project-state/DECISIONS.md — not a stopgap. Both channels read through one
shared device (``shared_reader``), so they cost one hardware measurement per
cycle, not two.

Two measurement characteristics follow from that and belong with any model
built on these channels (see dht22_adafruit.py's own note): ``temperature``
is ambient air at the sensor rather than a contact reading of a motor or
bearing surface, and ``temperature``/``humidity`` are physically coupled and
share a failure mode, so their agreement is not independent corroboration.

DS18B20 (edge/drivers/ds18b20.py) remains fully implemented and registered
as temperature's OPTIONAL ALTERNATE (registry._ALTERNATE_DRIVER_CLASSES) —
supported, NOT required. If that hardware is ever added, select it with
``DriverSpec(kind="alternate")`` here or ``SHTAPM_DRIVER_TEMPERATURE=alternate``
for one run; no pipeline, contract, topic, or downstream change is involved.
Note it measures a different physical quantity, so a model fitted on ambient
air is not automatically valid for a contact probe.

``pressure``, ``gas`` and ``current`` are fake constants. BMP280
(edge/drivers/bmp280.py) and INA219 (edge/drivers/ina219.py) are both
implemented and were each individually hardware-validated earlier, but
neither is physically connected right now; gas (MQ-135) has no driver at
all. Both implemented drivers stay registered as their channels' real
drivers, so connecting either one is a one-line change here
(``DriverSpec(kind="real")``) or ``SHTAPM_DRIVER_PRESSURE=real`` /
``SHTAPM_DRIVER_CURRENT=real`` for a single run — nothing else moves. A
disconnected sensor declared ``kind="real"`` would be permanently unhealthy
and would block every frame (Sampler.sample_once() requires all six
channels healthy) — which is why this table tracks the bench's real wiring
rather than what is merely implemented.

RECONNECTING A SENSOR IS NOW A CONFIGURATION CHANGE, not a code edit: set
``SHTAPM_DRIVER_<CHANNEL>=real`` (e.g. ``SHTAPM_DRIVER_VIBRATION=real``) to
switch that channel to its real driver (constructed with that driver's own
hardware defaults — see edge/drivers/registry.py); ``=fake`` switches a
channel back to a fake constant. ``SHTAPM_FAKE_SIGNAL_MODE=realistic``
switches every still-fake channel from a flat constant to a deterministic,
bounded, time-varying signal (edge/drivers/fake.py's ``realistic_raw`` —
NOT a physical validation claim, see that function's docstring); the
default (unset) is ``constant``, i.e. today's flat values, unchanged. No
code edit or import change is needed for any of this — see
``edge.drivers.registry`` for the full mechanism and its own docstring for
exactly what each variable does. "gas" has no real driver implemented yet;
requesting ``SHTAPM_DRIVER_GAS=real`` fails clearly at startup
(``UnsupportedDriverError``) rather than silently staying fake.

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

DECISION-DIAGNOSTIC PUBLISHING (still observe-only, still no isolation/
actuation): each outcome + its raw values + the current FR-RL4 tracking
result are additionally shaped into a ``DecisionDiagnosticMessage``
(``edge/pipeline/decision_diagnostic.py``) and best-effort-published to
``shtapm/{device_id}/decision_diagnostic`` — a NEW, separate topic, NOT the
frozen Doc05 ``.../decision`` topic/``DecisionMessage`` shape (that would
require health/failure_eta/rl_action/substituted, none of which anything
here computes; see that module's own docstring). Fire-and-forget: no LWT,
no buffering, no retry, no delivery guarantee, and — critically — no way
for a publish failure (or a broker that never even receives this topic) to
affect telemetry publishing or P2 monitoring, both of which run through a
completely separate publisher/connection and neither import nor call into
this one.

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
from edge.drivers.registry import DriverSpec, build_drivers, resolve_channel_specs_from_env
from edge.pipeline.decision_diagnostic import (
    DecisionDiagnosticPublisher,
    build_decision_diagnostic_message,
)
from edge.pipeline.isolation_fallback import decide_isolation
from edge.pipeline.isolation_tracker import IsolationFallbackTracker, IsolationTrackerResult
from edge.pipeline.monitor import LiveP2Monitor, RawChannelValues
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import CorrelationProvider

log = logging.getLogger("shtapm.edge.main")

# This bench's current wiring, as a declarative spec table — see module
# docstring. Constant values match the fake fixtures this file has used
# since before the registry existed (dev only — not authoritative specs).
# Override via SHTAPM_DRIVER_<CHANNEL> / SHTAPM_FAKE_SIGNAL_MODE env vars
# (edge.drivers.registry.resolve_channel_specs_from_env) — never by editing
# this table for a one-off run.
_DEFAULT_CHANNEL_SPECS: dict[str, DriverSpec] = {
    # DHT22 ambient air temp (approved, D028) — same physical sensor as humidity.
    # DS18B20 stays available as kind="alternate" if that hardware is added.
    "temperature": DriverSpec(kind="real"),  # DHT22AdafruitTemperatureDriver(), GPIO17
    "vibration": DriverSpec(kind="real"),  # ADXL335Driver(), MCP3008 CH0-2 / SPI0 CE0
    # BMP280 not connected yet; stays this channel's real driver for when it is.
    "pressure": DriverSpec(kind="fake", fake_mode="constant", params={"value": 1013.0}),
    "humidity": DriverSpec(kind="real"),  # DHT22AdafruitDriver(), GPIO17
    "gas": DriverSpec(kind="fake", fake_mode="constant", params={"value": 150.0}),
    "current": DriverSpec(kind="fake", fake_mode="constant", params={"value": 0.0}),
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


def _build_p2_monitor(
    *,
    fit_window_count: int,
    device_id: str,
    decision_publisher: DecisionDiagnosticPublisher,
) -> LiveP2Monitor:
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
    # LiveP2Monitor calls on_outcome(outcome) then on_raw_values(outcome, raw)
    # synchronously, for the SAME outcome, every cycle (edge/pipeline/monitor.py's
    # _emit()) -- this one-slot box lets on_raw_values reuse the single
    # isolation_tracker.update() call on_outcome already made, rather than
    # calling the stateful tracker a second time for the same cycle.
    last_tracked: dict[str, IsolationTrackerResult] = {}

    def _on_outcome(outcome: WindowOutcome) -> None:
        last_tracked["result"] = _log_window_outcome(outcome, isolation_tracker)

    def _on_raw_values(outcome: WindowOutcome, raw: RawChannelValues) -> None:
        _log_raw_values(outcome, raw)
        tracked = last_tracked.get("result")
        if tracked is None:
            return
        try:
            message = build_decision_diagnostic_message(device_id, outcome, tracked, raw)
            decision_publisher.publish(message)
        except Exception:
            # Best-effort, observe-only (see module docstring's
            # DECISION-DIAGNOSTIC PUBLISHING section) -- a bug here must
            # never interrupt P2 monitoring or telemetry.
            log.debug("decision diagnostic build/publish failed (best-effort)", exc_info=False)

    return LiveP2Monitor(
        preprocessor=preprocessor,
        pipeline=pipeline,
        c_provider=c_provider,
        fit_window_count=fit_window_count,
        on_outcome=_on_outcome,
        on_raw_values=_on_raw_values,
    )


def _log_window_outcome(
    outcome: WindowOutcome, isolation_tracker: IsolationFallbackTracker
) -> IsolationTrackerResult:
    """Monitoring-only: log preprocessing/anomaly/trust/attribution, the
    stateless FR-RL4 isolation decision, and the persistent FR-RL4 tracking
    result. Never isolates a channel for real, actuates, or publishes
    anything — see edge/pipeline/{isolation_fallback,isolation_tracker}.py.
    Returns the tracking result so the caller can reuse it (e.g. for
    decision-diagnostic publishing) without calling the stateful tracker
    a second time for the same cycle."""
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
    return tracked


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

    # Resolve this run's per-channel driver selection (env overrides applied
    # on top of _DEFAULT_CHANNEL_SPECS; unset env = today's bench state,
    # unchanged) and construct the actual SensorDriver instances.
    channel_specs = resolve_channel_specs_from_env(_DEFAULT_CHANNEL_SPECS)
    drivers = build_drivers(channel_specs)

    sampler = Sampler(device_id=device_id, drivers=drivers)
    publisher = ResilientTelemetryPublisher(device_id=device_id, rate_hz=rate_hz)
    publisher.start(host, port)
    # Separate object, separate MQTT connection -- see module docstring's
    # DECISION-DIAGNOSTIC PUBLISHING section. Its start()/publish()/stop()
    # never raise, so a failure here can never affect `publisher` above.
    decision_publisher = DecisionDiagnosticPublisher(device_id=device_id)
    decision_publisher.start(host, port)
    p2_monitor = _build_p2_monitor(
        fit_window_count=p2_fit_window_count,
        device_id=device_id,
        decision_publisher=decision_publisher,
    )
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

    real_channels = sorted(ch for ch in CHANNELS if channel_specs[ch].kind == "real")
    alternates = sorted(ch for ch in CHANNELS if channel_specs[ch].kind == "alternate")
    fake_channels = sorted(ch for ch in CHANNELS if channel_specs[ch].kind == "fake")
    print(
        f"[edge] driver config: real={real_channels or 'none'} "
        f"alternate={alternates or 'none'} fake={fake_channels or 'none'} → "
        f"{publisher.telemetry_topic} at {rate_hz} Hz (Ctrl-C to stop) "
        f"[P2 monitoring: observe-only, no isolation/actuation/publish]"
    )
    # The wire frame carries no sensor identity, so name the temperature source
    # here — it is the one channel with two supported sources (D028).
    temperature_kind = channel_specs["temperature"].kind
    if temperature_kind == "real":
        print(
            "[edge] temperature = DHT22 ambient air, GPIO17 (approved project "
            "configuration, D028) — one shared sensor with humidity"
        )
    elif temperature_kind == "alternate":
        print("[edge] temperature = DS18B20 contact probe (alternate source, D028)")
    try:
        runtime.run(should_continue=lambda: running["go"], sleep=time.sleep)
    finally:
        runtime.stop()
        decision_publisher.stop()
        print("[edge] stopped (status offline)")


if __name__ == "__main__":
    main()
