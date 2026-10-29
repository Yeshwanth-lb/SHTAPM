"""SHTAPM edge acquisition runtime — configuration-driven hardware/fake drivers.

Runs the C1→C2→C3 pipeline with one ``SensorDriver`` per frozen channel,
selected via ``edge.drivers.registry`` from a declarative per-channel
``DriverSpec`` table (``_DEFAULT_CHANNEL_SPECS`` below) rather than
hand-written ``drivers[channel] = XDriver()`` lines:

    registry.build_drivers(...) → Sampler → TelemetryMessage → Publisher → Mosquitto
                                                              ↘ LiveP2Monitor (observe-only)

``_DEFAULT_CHANNEL_SPECS`` matches this bench's actual wiring — FIVE real
channels across four physical sensors, one fake constant:

  channel      sensor / interface                       driver
  ----------   --------------------------------------   ----------------------
  temperature  DHT22 ambient air, GPIO17 (shared)       DHT22AdafruitTemperature
  humidity     DHT22 %RH, GPIO17 (shared)               DHT22Adafruit
  vibration    ADXL335, MCP3008 CH0-2 over SPI0 CE0     ADXL335
  pressure     BMP280, I²C bus 1, address 0x76          BMP280
  gas          MQ-135 AO via divider, MCP3008 CH3        fake constant 150.0 (D044: driver ready)
  current      INA219, I²C bus 1, address 0x40          INA219

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

``pressure`` is now BMP280 (edge/drivers/bmp280.py) — hardware-validated on
this Pi (I²C bus 1, address 0x76, chip ID 0x58 confirmed) and wired here as
this channel's real driver with the driver's own hardware defaults (no
params needed; see edge/drivers/registry.py). ``current`` is INA219
(edge/drivers/ina219.py) — hardware-validated on this Pi (I²C bus 1, address
0x40, same bus as BMP280) and likewise wired with the driver's own defaults:
the board's shunt is R100 (0.1 Ω), matching the driver's ``shunt_ohms``
default, so no params are needed. U09 (pump model / rated current) is still
open, so the driver's 5.0 A ``max_expected_amps`` is a default, not a sizing
decision. ``gas`` remains a fake constant until the MQ-135 is wired: its driver
exists (D044) and needs only SHTAPM_DRIVER_GAS=real + SHTAPM_GAS_DIVIDER_RATIO.
A disconnected sensor declared ``kind="real"`` would be permanently
unhealthy and would block every frame (Sampler.sample_once() requires all
six channels healthy) — which is why this table tracks the bench's real
wiring rather than what is merely implemented.

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
exactly what each variable does. ``SHTAPM_DRIVER_GAS=real`` without
``SHTAPM_GAS_DIVIDER_RATIO`` fails clearly at startup (``UnsupportedDriverError``
naming the variable) rather than silently staying fake (D044).

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
which P2 components are used and why. The detector is now a real
``IsolationForestDetector`` (2026-09-13 — previously ``NullDetector``, which
never flagged anything); it, ``SeverityThresholdFlagPolicy``, and
``OperatingStateRule`` (D034; ``TrendSignPhysicsRule`` until then) are all
fit together (``LiveP2Monitor``'s
``additional_fit_targets``) alongside ``ConsistencyProvider`` on
``P2_FIT_WINDOW_COUNT`` clean live windows — required, no default; a
single-window bootstrap was found to collapse the consistency signal to a
binary 0.0/1.0 output even on clean data, see the module docstring for the
fix. See ``_P2_DETECTOR_FLAG_THRESHOLD`` below for the detector threshold's
provenance (a real, full-dataset SWaT.A1 evaluation, not an invented value).

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
memory — a channel judged Malicious stays isolated while its trust is only
Suspicious, and is released once trust is back at ``TRUSTED_MIN`` (D018
pt.2, the same rule ``SelfHealOrchestrator`` uses to end substitution). It
adds no new threshold/cooldown/cap; the tracker itself never calls
process_isolated_channels/SelfHealOrchestrator/actuation/ledger/MQTT/
dashboard code.

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
from collections import deque
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from app.schemas.command import MAX_DURATION_S
from app.schemas.contracts import CHANNELS

from edge.acquisition.command_listener import CommandListener
from edge.acquisition.health import ChannelHealthBoard
from edge.acquisition.mqtt_publisher import ResilientTelemetryPublisher
from edge.acquisition.replay import ReplaySampler, load_replay_frames
from edge.acquisition.runtime import AcquisitionRuntime
from edge.acquisition.sampler import Sampler
from edge.actuation.gpio import PinctrlActuator, relay_config_from_env
from edge.actuation.mqtt import ActuationPublisher, RelayCommandListener
from edge.actuation.relay import FakeActuator, RelayController
from edge.actuation.supervisor import WATCHDOG_TIMEOUT_S, DryRunDetector, SafetySupervisor
from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.iforest import IsolationForestDetector
from edge.anomaly.operating_state_rule import (
    BENCH_VIBRATION_BANDS,
    OperatingStateRule,
    StateBands,
    calibrate_vibration_bands,
)
from edge.anomaly.pipeline import P2Pipeline, WindowOutcome
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor
from edge.drivers.registry import DriverSpec, build_drivers, resolve_channel_specs_from_env
from edge.injection.live import LiveInjector
from edge.models.p2_baseline import RECOMMENDED_MIN_SECONDS, P2Baseline, load_baseline
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
from edge.trust.k_operating_state import OperatingStateCorrelationProvider

if TYPE_CHECKING:
    from edge.pipeline.self_heal_runtime import SelfHealRuntime

log = logging.getLogger("shtapm.edge.main")


def _load_self_heal(
    model_dir: str, window_size: int, safe_stop: Callable[[], None] | None = None
) -> SelfHealRuntime | None:
    """Load the self-heal runtime, or None if its optional stack is unavailable.

    self_heal_runtime imports torch (edge/requirements-p3.txt). Imported here
    rather than at module top so a Pi without torch still runs telemetry, P2
    and trust -- previously a missing torch crash-looped the whole service.
    """
    try:
        from edge.pipeline.self_heal_runtime import load_self_heal_runtime
    except ImportError as e:
        log.warning(
            "self-heal DISABLED: %s -- telemetry, detection and trust continue; "
            "install edge/requirements-p3.txt to enable substitution",
            e,
        )
        return None
    if safe_stop is None:
        return load_self_heal_runtime(model_dir, window_size)
    return load_self_heal_runtime(model_dir, window_size, safe_stop=safe_stop)


SELF_HEAL_ESCALATION = (
    "self-heal escalation (D018: divergence over threshold, or a channel still "
    "isolated after 60 s of substitution)"
)


def _build_safety_supervisor(
    *, device_id: str, replay: bool, publish: Callable, env: Mapping[str, str] | None = None
) -> SafetySupervisor:
    """The relay owner (D041). A physical relay only when configured AND the
    edge reads live sensors: replayed current says nothing about the real
    motor, so the fallback profile always runs the logic in memory."""
    env = os.environ if env is None else env
    config = relay_config_from_env(env)  # an unsafe configuration stops the boot here
    if config is not None and not replay:
        pin, active_low = config
        actuator = PinctrlActuator(pin, active_low=active_low)
        hardware = True
    else:
        if config is not None:
            log.warning("replay source: the physical relay is NOT driven (in-memory relay)")
        actuator = FakeActuator()
        hardware = False
    relay = RelayController(actuator)  # forces OFF at construction
    raw_threshold = env.get("SHTAPM_DRY_RUN_CURRENT_A", "").strip()
    dry_run = (
        DryRunDetector(_env_number("SHTAPM_DRY_RUN_CURRENT_A", raw_threshold, float, env=env))
        if raw_threshold
        else None
    )
    if dry_run is None:
        log.warning("dry-run protection OFF: SHTAPM_DRY_RUN_CURRENT_A not set (FR-R2)")
    watchdog_s = _env_number("SHTAPM_WATCHDOG_S", str(WATCHDOG_TIMEOUT_S), float, env=env)
    return SafetySupervisor(
        device_id=device_id,
        relay=relay,
        hardware=hardware,
        publish=publish,
        dry_run=dry_run,
        watchdog_timeout_s=watchdog_s,
    )


def _load_p2_baseline(model_dir: str) -> P2Baseline | None:
    """Load the persisted clean baseline (D031), logging what was found.

    None means: no baseline, or an unusable one (load_baseline logs why). The
    caller then falls back to live warm-up fitting on P2_FIT_WINDOW_COUNT
    windows -- the pre-D031 behaviour, kept so a missing file degrades
    calibration instead of stopping the service."""
    baseline = load_baseline(model_dir)
    if baseline is None:
        log.warning(
            "no P2 baseline in %s -- falling back to live warm-up fitting "
            "(create one with edge/scripts/fit_p2_baseline.py)",
            model_dir,
        )
        return None
    log.info(
        "P2 baseline loaded: %d frames, %d segments, %.1f min clean, source=%s, created=%s",
        baseline.frame_count,
        len(baseline.segments),
        baseline.duration_s / 60.0,
        baseline.source,
        baseline.created_at,
    )
    if baseline.duration_s < RECOMMENDED_MIN_SECONDS:
        log.warning(
            "P2 baseline covers only %.1f min; the 2026-10-26 replay needed >= %d min "
            "before false Malicious windows disappeared (D031)",
            baseline.duration_s / 60.0,
            RECOMMENDED_MIN_SECONDS // 60,
        )
    return baseline


# Isolation Forest flag threshold: chosen from a real, full-dataset SWaT.A1
# evaluation (2026-09-13, all 944,919 rows, 35 real labelled attacks) — the
# best-by-F1 point of a full 0.80-0.99 threshold sweep (detection_rate=0.494,
# fp_rate=0.123 at the window level; separately, 34/35 real attacks were
# eventually flagged at least once, 16/35 within the PRD's <=3-window
# target). Full report: project-state/P2_IF_SWAT_TUNING.md.
#
# This is a SWaT-domain-derived STARTING POINT, not a bench calibration:
# severity is a percentile within whatever IsolationForestDetector is fit on
# (see edge/anomaly/iforest.py's own D-B design note), so this value travels
# as a "flag the most unusual ~10%" POLICY choice — but the underlying fit
# happens on THIS bench's own clean data at every process start, never reused
# from the SWaT-fitted model: from the persisted baseline when one exists
# (D031, edge/models/p2_baseline.py), otherwise from live warm-up windows (see
# LiveP2Monitor's additional_fit_targets below). Must be revisited once real
# bench clean/faulty/spoofed data exists to validate this value directly (U07).
_P2_DETECTOR_FLAG_THRESHOLD = 0.90
_P2_DETECTOR_RANDOM_STATE = 0  # determinism only, matches edge/eval/*.py convention

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
    "pressure": DriverSpec(kind="real"),  # BMP280Driver(), I²C bus 1, address 0x76
    "humidity": DriverSpec(kind="real"),  # DHT22AdafruitDriver(), GPIO17
    "gas": DriverSpec(kind="fake", fake_mode="constant", params={"value": 150.0}),
    "current": DriverSpec(kind="real"),  # INA219Driver(), I²C bus 1, address 0x40
}


EDGE_SOURCES = ("sensors", "replay")


def _edge_source(env: Mapping[str, str] | None = None) -> tuple[str, str | None]:
    """``EDGE_SOURCE`` (default ``sensors``) and, for ``replay``, the required
    ``FALLBACK_REPLAY_PATH`` (D040). Bad values fail at boot, naming the
    variable."""
    env = os.environ if env is None else env
    source = env.get("EDGE_SOURCE", "sensors")
    if source not in EDGE_SOURCES:
        raise RuntimeError(f"EDGE_SOURCE={source!r} must be one of {EDGE_SOURCES}")
    if source == "sensors":
        return source, None
    path = env.get("FALLBACK_REPLAY_PATH")
    if not path:
        raise RuntimeError("EDGE_SOURCE=replay requires FALLBACK_REPLAY_PATH (see .env.example)")
    return source, path


def _env_number(name: str, default: str, cast: type, env: Mapping[str, str] | None = None):
    """A numeric env var with a default; a malformed value fails at boot with
    an error naming the variable (TRD §02.7, AC10 P1-4), not a bare
    ``could not convert string to float``."""
    env = os.environ if env is None else env
    raw = env.get(name, default)
    try:
        return cast(raw)
    except ValueError:
        raise RuntimeError(
            f"{name}={raw!r} is not a valid {cast.__name__} (see .env.example)"
        ) from None


def _required_env_int(name: str) -> int:
    """Read a required integer env var — raises with a clear message if
    unset, per TRD §02.7's "missing var → clear boot error naming it"
    acceptance criterion. No default is invented for values this project
    has not specified (see .env.example)."""
    value = os.environ.get(name)
    if value is None:
        raise RuntimeError(f"{name} is required (see .env.example) — no default is invented")
    return _env_number(name, value, int)


def _vibration_bands(baseline: P2Baseline | None, window: int) -> StateBands:
    """Vibration motor-state bands for THIS installation (D036): learned from
    the persisted baseline when there is one, otherwise the bench defaults."""
    if baseline is None:
        return BENCH_VIBRATION_BANDS
    cur, vib = CHANNELS.index("current"), CHANNELS.index("vibration")
    bands = calibrate_vibration_bands(
        [(seg[:, cur].tolist(), seg[:, vib].tolist()) for seg in baseline.segments], window
    )
    log.info(
        "vibration motor-state bands from baseline: idle <= %.3f g, running >= %.3f g",
        bands.idle_max,
        bands.running_min,
    )
    return bands


def _build_p2_monitor(
    *,
    fit_window_count: int | None,
    device_id: str,
    decision_publisher: DecisionDiagnosticPublisher,
    self_heal: SelfHealRuntime | None = None,
    recent_frames: deque | None = None,
    baseline: P2Baseline | None = None,
    channel_health: ChannelHealthBoard | None = None,
) -> LiveP2Monitor:
    """Compose the real (non-stub) P2 pipeline for observe-only live
    monitoring. The detector, flag policy, and physics rule are real, fitted
    components (fit alongside ConsistencyProvider — see
    edge/pipeline/monitor.py's ``additional_fit_targets``); previously all
    three relied on ``NullDetector`` never flagging to stay silently unfit
    but structurally unreachable (see that module's docstring history). See
    edge/pipeline/monitor.py's docstring for the ``fit_window_count``
    buffer-size derivation, and ``_P2_DETECTOR_FLAG_THRESHOLD`` above for the
    detector threshold's provenance.

    With ``baseline`` (D031) the four fitted components are fit here, once, on
    the persisted clean windows, and the monitor starts prefitted -- no live
    warm-up, and ``fit_window_count`` is unused. Without it, behaviour is
    exactly the pre-D031 live warm-up on ``fit_window_count`` windows."""
    preprocessor = Preprocessor(median_kernel=1, low_pass_alpha=1.0)  # identity filters;
    # median_kernel/low_pass_alpha have no documented spec value (see
    # edge/anomaly/preprocess.py) — 1/1.0 are the module's own documented
    # identity settings, not an invented smoothing amount.
    c_provider = ConsistencyProvider()
    detector = IsolationForestDetector(
        flag_threshold=_P2_DETECTOR_FLAG_THRESHOLD, random_state=_P2_DETECTOR_RANDOM_STATE
    )
    flag_policy = SeverityThresholdFlagPolicy()
    # D034: motor-state consistency between current and vibration replaces
    # the trend-sign heuristic (D013), and a violation flags its suspect.
    vibration_bands = _vibration_bands(baseline, preprocessor.window_size)
    physics_rule = OperatingStateRule(vibration_bands=vibration_bands)
    pipeline = P2Pipeline(
        preprocessor=preprocessor,
        detector=detector,
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(physics_rule),
        c_provider=c_provider,
        # D035: k objects only to a physically impossible motor state, using
        # the same model as attribution (D034). The trend-sign k (D010/D033)
        # punished both channels for noise during steady operation.
        k_provider=OperatingStateCorrelationProvider(
            OperatingStateRule(vibration_bands=vibration_bands)
        ),
        h_provider=HReliabilityProvider(),
        flag_policy=flag_policy,
        physics_flags=True,
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
        twin_values = _run_self_heal(outcome, tracked, self_heal, recent_frames)
        try:
            message = build_decision_diagnostic_message(
                device_id,
                outcome,
                tracked,
                raw,
                substituted_channels=list(twin_values),
                stale_channels=channel_health.stale() if channel_health is not None else (),
                motor_state=physics_rule.motor_states(),
                twin_values=twin_values,
            )
            decision_publisher.publish(message)
        except Exception:
            # Best-effort, observe-only (see module docstring's
            # DECISION-DIAGNOSTIC PUBLISHING section) -- a bug here must
            # never interrupt P2 monitoring or telemetry.
            log.debug("decision diagnostic build/publish failed (best-effort)", exc_info=False)

    fit_targets = [detector, flag_policy, physics_rule]
    if baseline is not None:
        windows = baseline.windows(preprocessor)
        c_provider.fit(windows)
        for target in fit_targets:
            target.fit(windows)
        log.info(
            "P2 monitor: fit ConsistencyProvider + %d component(s) on %d persisted "
            "baseline windows (no live warm-up)",
            len(fit_targets),
            len(windows),
        )
    return LiveP2Monitor(
        preprocessor=preprocessor,
        pipeline=pipeline,
        c_provider=c_provider,
        additional_fit_targets=fit_targets,
        fit_window_count=fit_window_count,
        on_outcome=_on_outcome,
        on_raw_values=_on_raw_values,
        prefitted=baseline is not None,
    )


def _run_self_heal(
    outcome: WindowOutcome,
    tracked: IsolationTrackerResult,
    self_heal: SelfHealRuntime | None,
    recent_frames: deque | None,
) -> dict[str, float]:
    """Reconstruct any isolated channel the trained twin can serve, and log it.
    Returns channel -> reconstructed value in engineering units (D054).

    OBSERVE-ONLY, in three specific senses:
      * the reconstruction is logged, never written into the telemetry frame --
        the frozen contract keeps carrying what the sensor actually said;
      * escalation to Safe Pump-Stop is unreachable (divergence_threshold is
        +inf, see edge/pipeline/self_heal_runtime.py) because U05 failed on
        measured evidence, not because a number is merely pending;
      * no actuation, relay or GPIO call exists anywhere in this path.

    Substitution runs on the tracker's PERSISTENT candidates rather than this
    cycle's stateless decision: a channel whose trust briefly recovers is still
    being substituted, and flapping the reconstruction on and off would
    misrepresent that.
    """
    if self_heal is None or recent_frames is None:
        return {}
    # Called with an empty set too: that is how a release resets the 60 s
    # substitution clock (D050).
    try:
        reports = self_heal.substitute(
            outcome, frozenset(tracked.tracked_channels), list(recent_frames)
        )
    except Exception:
        # A self-healing fault must never stop telemetry or P2.
        log.debug("self-heal substitution failed (observe-only)", exc_info=False)
        return {}
    for report in reports:
        log.info(
            "SELF-HEAL substitution (observe-only, not written to telemetry): "
            "%s sensor=%.6f twin=%.6f divergence=%s uncertainty=%s",
            report.channel,
            report.observed_value,
            report.substituted_value,
            f"{report.divergence:.3f}" if report.divergence is not None else "n/a",
            f"{report.uncertainty:.3f}" if report.uncertainty is not None else "n/a",
        )
    return {report.channel: report.substituted_value for report in reports}


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
    rate_hz = _env_number("SAMPLE_RATE_HZ", "1", float)
    host = os.environ.get("EDGE_MQTT_HOST", "localhost")
    port = _env_number("EDGE_MQTT_PORT", "1883", int)
    model_dir = os.environ.get("MODEL_DIR", "./models")
    # A persisted clean baseline (D031) replaces live warm-up fitting. Only
    # without one is P2_FIT_WINDOW_COUNT needed -- and then still required,
    # with the same named boot error as before.
    p2_baseline = _load_p2_baseline(model_dir)
    p2_fit_window_count = (
        None if p2_baseline is not None else _required_env_int("P2_FIT_WINDOW_COUNT")
    )

    # Resolve this run's per-channel driver selection (env overrides applied
    # on top of _DEFAULT_CHANNEL_SPECS; unset env = today's bench state,
    # unchanged) and construct the actual SensorDriver instances.
    channel_specs = resolve_channel_specs_from_env(_DEFAULT_CHANNEL_SPECS)
    # Recorded-session fallback (D040): EDGE_SOURCE=replay serves a recorded
    # telemetry file through the identical live path instead of the sensors.
    source, replay_path = _edge_source()
    if source == "replay":
        sampler = ReplaySampler(device_id=device_id, frames=load_replay_frames(replay_path))
    else:
        # Degraded mode (D045): a sensor that dies mid-run holds its last good
        # value and is reported stale, instead of stopping every frame.
        sampler = Sampler(
            device_id=device_id, drivers=build_drivers(channel_specs), hold_last_good=True
        )
    channel_health = ChannelHealthBoard()
    publisher = ResilientTelemetryPublisher(device_id=device_id, rate_hz=rate_hz)
    publisher.start(host, port)
    # Separate object, separate MQTT connection -- see module docstring's
    # DECISION-DIAGNOSTIC PUBLISHING section. Its start()/publish()/stop()
    # never raise, so a failure here can never affect `publisher` above.
    decision_publisher = DecisionDiagnosticPublisher(device_id=device_id)
    decision_publisher.start(host, port)
    # The twin consumes windows in D029's fixed clean-baseline scale, which is
    # NOT the per-window min-max space LiveP2Monitor's windows use. Keep the raw
    # frames so the self-heal runtime can build its own correctly-scaled window.
    window_size = _env_number("WINDOW_SIZE", "30", int)
    recent_frames: deque = deque(maxlen=window_size)

    # Safety supervisor (D041): the only owner of the pump relay. Built before
    # self-heal so its escalation reaches the relay.
    actuation_publisher = ActuationPublisher(device_id=device_id)
    actuation_publisher.start(host, port)
    supervisor = _build_safety_supervisor(
        device_id=device_id, replay=source == "replay", publish=actuation_publisher.publish
    )
    supervisor.start()
    relay_listener = RelayCommandListener(device_id=device_id, supervisor=supervisor)
    relay_listener.start(host, port)

    self_heal = _load_self_heal(
        model_dir,
        window_size,
        safe_stop=lambda: supervisor.safe_stop("safe_stop", SELF_HEAL_ESCALATION),
    )

    p2_monitor = _build_p2_monitor(
        fit_window_count=p2_fit_window_count,
        device_id=device_id,
        decision_publisher=decision_publisher,
        self_heal=self_heal,
        recent_frames=recent_frames,
        baseline=p2_baseline,
        channel_health=channel_health,
    )

    def _on_healthy_frame(frame) -> None:
        supervisor.on_frame(frame, stale=channel_health.stale())  # safety first
        recent_frames.append(frame)
        p2_monitor.on_frame(frame)

    # Scenario injection (FR-A4/FR-D7, D032): backend commands arrive on
    # shtapm/{device_id}/command and rewrite frames before P2 and publishing,
    # for a bounded time. History covers the longest replay a command can ask
    # for (lookback >= duration, duration <= MAX_DURATION_S).
    injector = LiveInjector(
        device_id=device_id, rate_hz=rate_hz, history_seconds=2 * MAX_DURATION_S
    )
    command_listener = CommandListener(device_id=device_id, injector=injector)
    command_listener.start(host, port)

    runtime = AcquisitionRuntime(
        sampler=sampler,
        publisher=publisher,
        rate_hz=rate_hz,
        on_healthy_frame=_on_healthy_frame,
        frame_transform=injector.transform,
        on_result=channel_health.update,
    )

    running = {"go": True}

    def _stop(*_a: object) -> None:
        running["go"] = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    if source == "replay":
        print(
            f"[edge] SOURCE = RECORDED SESSION (fallback profile, D040): replaying "
            f"{sampler.frame_count} recorded frames from {replay_path}, looping -- "
            "values are recorded measurements, not live sensors"
        )
    status = supervisor.last_status
    relay_kind = "PHYSICAL" if status and status.hardware else "in-memory (no relay driven)"
    print(
        f"[edge] relay: {relay_kind}, OFF at startup; remote start/stop on "
        f"{relay_listener.topic} (D041)"
    )
    real_channels = sorted(ch for ch in CHANNELS if channel_specs[ch].kind == "real")
    alternates = sorted(ch for ch in CHANNELS if channel_specs[ch].kind == "alternate")
    fake_channels = sorted(ch for ch in CHANNELS if channel_specs[ch].kind == "fake")
    print(
        f"[edge] driver config: real={real_channels or 'none'} "
        f"alternate={alternates or 'none'} fake={fake_channels or 'none'} -> "
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
        supervisor.stop()  # relay OFF and announced while the publisher is still up
        relay_listener.stop()
        actuation_publisher.stop()
        runtime.stop()
        command_listener.stop()
        decision_publisher.stop()
        print("[edge] stopped (status offline)")


if __name__ == "__main__":
    main()
