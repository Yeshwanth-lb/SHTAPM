"""D033: the current<->vibration rule applies only while the motor runs."""

from __future__ import annotations

import pytest
from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.detector import NullDetector
from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.pipeline import P2Pipeline
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Preprocessor, Window
from edge.trust.c_consistency import ConsistencyProvider
from edge.trust.engine import TrustEngine
from edge.trust.h_reliability import HReliabilityProvider
from edge.trust.k_correlation import BENCH_RUNNING_GATE, CorrelationProvider, RunningGate

N = 30
_BASE = {"temperature": 27.0, "pressure": 916.0, "humidity": 60.0, "gas": 150.0}


def _frames(current: list[float], vibration: list[float]):
    return [
        build_telemetry(
            "pump-01",
            "2026-10-26T10:00:00.000Z",
            {**_BASE, "current": c, "vibration": v},
            i,
        )
        for i, (c, v) in enumerate(zip(current, vibration, strict=True))
    ]


def _anticorrelated_window() -> Window:
    """Current rising, vibration falling: the rule's k = 0.0 case."""
    features = {ch: (0.5,) * N for ch in CHANNELS}
    features["current"] = tuple(i / (N - 1) for i in range(N))
    features["vibration"] = tuple(1 - i / (N - 1) for i in range(N))
    return Window(start_index=0, end_index=N, features=features)


IDLE = _frames([0.0002] * N, [0.18] * N)
RUNNING_BY_CURRENT = _frames([0.8] * N, [0.18] * N)
RUNNING_BY_VIBRATION = _frames([0.0] * N, [0.7] * N)


def test_without_a_gate_behaviour_is_unchanged():
    k = CorrelationProvider()
    k.observe_raw_window(IDLE)  # no-op without a gate
    k.record_window(_anticorrelated_window())
    assert k.evaluate("current") == 0.0
    assert k.evaluate("vibration") == 0.0
    assert k.running is None


def test_idle_motor_makes_the_pair_neutral():
    k = CorrelationProvider(running_gate=BENCH_RUNNING_GATE)
    k.observe_raw_window(IDLE)
    k.record_window(_anticorrelated_window())
    assert k.evaluate("current") == 1.0
    assert k.evaluate("vibration") == 1.0
    assert k.running is False


@pytest.mark.parametrize("frames", [RUNNING_BY_CURRENT, RUNNING_BY_VIBRATION])
def test_either_channel_showing_the_motor_running_keeps_the_rule_active(frames):
    """Pinning one channel to an idle-looking value cannot disable the check."""
    k = CorrelationProvider(running_gate=BENCH_RUNNING_GATE)
    k.observe_raw_window(frames)
    k.record_window(_anticorrelated_window())
    assert k.evaluate("current") == 0.0
    assert k.running is True


def test_unobserved_window_fails_towards_applying_the_rule():
    k = CorrelationProvider(running_gate=BENCH_RUNNING_GATE)
    k.record_window(_anticorrelated_window())  # wiring fault: no raw frames given
    assert k.evaluate("current") == 0.0


def test_each_window_needs_its_own_observation():
    k = CorrelationProvider(running_gate=BENCH_RUNNING_GATE)
    k.observe_raw_window(IDLE)
    k.record_window(_anticorrelated_window())
    k.record_window(_anticorrelated_window())  # verdict consumed by the first
    assert k.evaluate("current") == 0.0


def test_uninvolved_channels_stay_at_one():
    k = CorrelationProvider(running_gate=BENCH_RUNNING_GATE)
    k.observe_raw_window(RUNNING_BY_CURRENT)
    k.record_window(_anticorrelated_window())
    assert [k.evaluate(ch) for ch in ("temperature", "pressure", "humidity", "gas")] == [1.0] * 4


def test_gate_thresholds_are_inclusive_and_validated():
    gate = RunningGate(current_min=0.1, vibration_min=0.5)
    assert gate.is_running(_frames([0.1] * 3, [0.0] * 3)) is True
    assert gate.is_running(_frames([0.0999] * 3, [0.4999] * 3)) is False
    assert gate.is_running([]) is False
    with pytest.raises(ValueError):
        RunningGate(current_min=0, vibration_min=0.5)


def test_bench_gate_sits_between_measured_idle_and_running_levels():
    """2026-10-26 window means: idle current <= 0.0001 A, vibration <= 0.347 g;
    running current >= 0.31 A."""
    assert 0.0001 < BENCH_RUNNING_GATE.current_min < 0.31
    assert 0.347 < BENCH_RUNNING_GATE.vibration_min


def _pipeline(k: CorrelationProvider) -> tuple[P2Pipeline, ConsistencyProvider]:
    pre = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=N)
    c = ConsistencyProvider()
    pipeline = P2Pipeline(
        preprocessor=pre,
        detector=NullDetector(),
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(TrendSignPhysicsRule()),
        c_provider=c,
        k_provider=k,
        h_provider=HReliabilityProvider(),
        flag_policy=SeverityThresholdFlagPolicy(),
    )
    return pipeline, c


def test_pipeline_passes_each_windows_raw_frames_to_the_gate():
    k = CorrelationProvider(running_gate=BENCH_RUNNING_GATE)
    pipeline, c = _pipeline(k)
    rising = [i / 1000 for i in range(N)]
    falling = [0.2 - i / 1000 for i in range(N)]
    c.fit(
        Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=N).process(
            _frames(rising, falling)
        )
    )
    # Idle levels, anticorrelated shapes: gated to neutral.
    [idle] = pipeline.process(_frames(rising, falling))
    assert k.running is False and k.evaluate("current") == 1.0
    # Same shapes with the motor running by current: the rule applies.
    [running] = pipeline.process(_frames([0.8 + x for x in rising], falling))
    assert k.running is True and k.evaluate("current") == 0.0
    assert idle.trust["current"].trust > running.trust["current"].trust
