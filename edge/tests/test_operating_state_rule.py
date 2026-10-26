"""OperatingStateRule: current<->vibration motor-state consistency attribution."""

from __future__ import annotations

import pytest
from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import AttributionEngine
from edge.anomaly.operating_state_rule import (
    BENCH_CURRENT_BANDS,
    BENCH_VIBRATION_BANDS,
    IDLE,
    RUNNING,
    UNCLEAR,
    OperatingStateRule,
    StateBands,
)
from edge.anomaly.preprocess import Window

N = 30
_OTHER = {"temperature": 27.0, "pressure": 916.0, "humidity": 60.0, "gas": 150.0}


def _frames(current, vibration):
    cur = current if isinstance(current, list) else [current] * N
    vib = vibration if isinstance(vibration, list) else [vibration] * N
    return [
        build_telemetry(
            "pump-01", "2026-10-26T10:00:00.000Z", {**_OTHER, "current": c, "vibration": v}, i
        )
        for i, (c, v) in enumerate(zip(cur, vib, strict=True))
    ]


WINDOW = Window(start_index=0, end_index=N, features={ch: (0.5,) * N for ch in CHANNELS})
IDLE_F = _frames(0.0002, 0.18)
RUN_F = _frames(0.8, 0.7)


def _rule() -> OperatingStateRule:
    rule = OperatingStateRule()
    rule.fit([WINDOW])
    return rule


def _step(rule, frames):
    rule.observe_raw_window(frames)
    return rule.check(WINDOW)


def test_bands_classify_with_a_hysteresis_gap():
    bands = StateBands(idle_max=0.05, running_min=0.3)
    assert bands.classify(0.0) == IDLE
    assert bands.classify(0.05) == IDLE
    assert bands.classify(0.2) == UNCLEAR
    assert bands.classify(0.3) == RUNNING
    with pytest.raises(ValueError):
        StateBands(idle_max=0.3, running_min=0.3)


def test_bench_bands_sit_between_measured_idle_and_running_levels():
    assert 0.0002 < BENCH_CURRENT_BANDS.idle_max < BENCH_CURRENT_BANDS.running_min <= 0.31
    assert 0.347 <= BENCH_VIBRATION_BANDS.idle_max < BENCH_VIBRATION_BANDS.running_min <= 0.684


def test_consistent_idle_and_running_are_not_violations():
    rule = _rule()
    assert _step(rule, IDLE_F).violated is False
    assert _step(rule, RUN_F).violated is False  # both moved together: a real start


def test_a_channel_that_changes_state_alone_is_the_suspect():
    rule = _rule()
    _step(rule, IDLE_F)
    check = _step(rule, _frames(0.8, 0.18))  # current claims running, vibration idle
    assert check.violated is True
    assert check.suspect_channel == "current"
    assert "current says the motor is running while vibration says it is idle" in check.reason


def test_hiding_a_running_motor_names_the_falsified_channel():
    rule = _rule()
    _step(rule, RUN_F)
    check = _step(rule, _frames(0.8, 0.15))  # vibration pinned to idle while current runs
    assert check.violated is True
    assert check.suspect_channel == "vibration"


def test_impulsive_events_do_not_flip_the_median_state():
    """A tap or glitch: a few huge samples in an otherwise idle window."""
    rule = _rule()
    _step(rule, IDLE_F)
    tapped = [0.18] * N
    tapped[10:13] = [5.0, 4.0, 6.0]
    assert _step(rule, _frames(0.0002, tapped)).violated is False


def test_unclear_band_gives_no_verdict():
    rule = _rule()
    _step(rule, IDLE_F)
    assert _step(rule, _frames(0.15, 0.18)).violated is False  # current in its gap


def test_simultaneous_disagreement_without_history_names_no_suspect():
    rule = _rule()
    check = _step(rule, _frames(0.8, 0.18))  # first window ever: both states new
    assert check.violated is True
    assert check.suspect_channel is None


def test_no_raw_frames_means_no_verdict_and_check_consumes_them():
    rule = _rule()
    assert rule.check(WINDOW).violated is False
    _step(rule, IDLE_F)
    rule.observe_raw_window(_frames(0.8, 0.18))
    assert rule.check(WINDOW).violated is True
    assert rule.check(WINDOW).violated is False  # consumed


def test_check_requires_fit_and_fit_requires_windows():
    with pytest.raises(RuntimeError):
        OperatingStateRule().check(WINDOW)
    with pytest.raises(ValueError):
        OperatingStateRule().fit([])


def test_engine_forwards_raw_frames_and_attributes_attack_only_to_the_suspect():
    rule = _rule()
    engine = AttributionEngine(rule)
    engine.observe_raw_window(IDLE_F)
    engine.attribute({ch: False for ch in CHANNELS}, WINDOW)
    engine.observe_raw_window(_frames(0.8, 0.18))
    flags = {ch: ch in ("current", "vibration") for ch in CHANNELS}
    out = engine.attribute(flags, WINDOW)
    assert out["current"].attribution is Attribution.attack
    assert out["vibration"].attribution is Attribution.fault
    assert out["temperature"].attribution is Attribution.none


def test_engine_tolerates_rules_without_the_raw_hook():
    class _Plain:
        def check(self, window):
            from edge.anomaly.attribution import PhysicsCheck

            return PhysicsCheck(violated=False, suspect_channel=None, reason="")

    engine = AttributionEngine(_Plain())
    engine.observe_raw_window(IDLE_F)  # no-op, must not raise
    assert engine.attribute({"current": True}, WINDOW)["current"].attribution is Attribution.fault


# --- pipeline: physics violations as flags --------------------------------------


def _pipeline(physics_flags: bool):
    from edge.anomaly.detector import NullDetector
    from edge.anomaly.pipeline import P2Pipeline
    from edge.anomaly.policy import SeverityThresholdFlagPolicy
    from edge.anomaly.preprocess import Preprocessor
    from edge.trust.c_consistency import ConsistencyProvider
    from edge.trust.engine import TrustEngine
    from edge.trust.h_reliability import HReliabilityProvider
    from edge.trust.k_correlation import BENCH_RUNNING_GATE, CorrelationProvider

    pre = Preprocessor(median_kernel=1, low_pass_alpha=1.0, window_size=N)
    c = ConsistencyProvider()
    noisy = [0.0002 + (i % 3) * 1e-5 for i in range(N)]
    c.fit(pre.process(_frames(noisy, [0.18 + (i % 4) * 1e-3 for i in range(N)])))
    rule = _rule()
    return P2Pipeline(
        preprocessor=pre,
        detector=NullDetector(),  # never flags: only physics can
        trust_engine=TrustEngine(),
        attribution_engine=AttributionEngine(rule),
        c_provider=c,
        k_provider=CorrelationProvider(running_gate=BENCH_RUNNING_GATE),
        h_provider=HReliabilityProvider(),
        flag_policy=SeverityThresholdFlagPolicy(),
        physics_flags=physics_flags,
    )


def _sustained_spoof_stream():
    """60 idle frames, then current pinned to a running value for 60 frames
    while vibration stays idle: a sustained, physically impossible state."""
    idle = [0.0002] * 60
    return _frames(idle + [0.8] * 60, [0.18] * 120)


def test_physics_flags_catch_a_sustained_spoof_the_statistics_miss():
    outcomes = _pipeline(physics_flags=True).process(_sustained_spoof_stream())
    inside = [o for o in outcomes if o.window.start_index >= 75]  # median flipped
    assert inside and all(o.channel_flags["current"] for o in inside)
    assert all(o.attribution["current"].attribution is Attribution.attack for o in inside)
    assert not any(o.channel_flags["vibration"] for o in inside)
    assert inside[-1].trust["current"].trust < outcomes[0].trust["current"].trust


def test_without_physics_flags_behaviour_is_unchanged():
    outcomes = _pipeline(physics_flags=False).process(_sustained_spoof_stream())
    assert not any(o.channel_flags["current"] for o in outcomes)  # NullDetector, no physics flags
    assert all(o.attribution["current"].attribution is Attribution.none for o in outcomes)
