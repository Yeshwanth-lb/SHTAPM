"""Tests for edge/pipeline/self_heal_runtime.py (P3 live wiring).

Two properties matter most here and are asserted directly:
  * a missing/broken twin must never stop telemetry (fail-safe, FR-RL4 posture);
  * escalation to Safe Pump-Stop must be unreachable in this build, because U05
    is open on measured evidence (see BENCH_LOAD_VALIDATION.md §8).
"""

from __future__ import annotations

import math

import pytest
from app.schemas.contracts import CHANNELS, TelemetryMessage

from edge.anomaly.detector import AnomalyResult
from edge.anomaly.pipeline import WindowOutcome
from edge.anomaly.preprocess import Window
from edge.models.lstm_twin import LSTMTwinReconstructor, _LSTMTwinNet
from edge.models.scaling import ChannelScaler
from edge.models.twin_bundle import TwinBundle, save_bundle
from edge.pipeline.self_heal_runtime import (
    ESCALATION_DISABLED_THRESHOLD,
    SelfHealRuntime,
    load_self_heal_runtime,
)
from edge.trust.beta import TrustBand
from edge.trust.engine import TrustReading

WINDOW_SIZE = 30
HIDDEN_SIZE_FIXTURE = 4


def _bundle(channel: str = "current") -> TwinBundle:
    scaler = ChannelScaler()
    scaler.fit({ch: [0.0, 1.0, 2.0] for ch in CHANNELS if ch != "gas"})
    return TwinBundle(
        channel=channel,
        reconstructor=LSTMTwinReconstructor(_LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)),
        scaler=scaler,
        residual_mean=0.0,
        residual_std=1.0,
        hidden_size=HIDDEN_SIZE_FIXTURE,
        skill=0.458,
        trained_on="test",
    )


def _frames(n: int = WINDOW_SIZE, current: float = 1.0) -> list[TelemetryMessage]:
    return [
        TelemetryMessage(
            device_id="pump-01",
            ts="2026-09-18T12:00:00.000Z",
            sensors={
                "temperature": 1.0,
                "vibration": 1.0,
                "pressure": 1.0,
                "humidity": 1.0,
                "gas": 150.0,
                "current": current,
            },
            sample_seq=i,
        )
        for i in range(n)
    ]


def _outcome(trust: float) -> WindowOutcome:
    band = TrustBand.MALICIOUS if trust < 0.4 else TrustBand.TRUSTED
    return WindowOutcome(
        window=Window(
            start_index=0,
            end_index=WINDOW_SIZE,
            features={ch: (0.0,) * WINDOW_SIZE for ch in CHANNELS},
        ),
        anomaly=AnomalyResult(flag=False, severity=0.0),
        channel_flags=dict.fromkeys(CHANNELS, False),
        trust={ch: TrustReading(channel=ch, g=0.0, trust=trust, band=band) for ch in CHANNELS},
        attribution={},
    )


def test_escalation_is_unreachable_by_construction():
    """U05 is open because the measurement failed (5.8% false escalations at
    3 sigma on clean data), so the threshold is +inf, not a large guess."""
    assert ESCALATION_DISABLED_THRESHOLD == math.inf


def test_substitutes_an_isolated_channel_in_engineering_units():
    runtime = SelfHealRuntime(_bundle(), window_size=WINDOW_SIZE)
    reports = runtime.substitute(_outcome(trust=0.1), frozenset({"current"}), _frames())

    assert len(reports) == 1
    report = reports[0]
    assert report.channel == "current"
    assert report.unit_space == "engineering"
    # The observed value must come back as the sensor's own reading, not a
    # scaled number -- that round trip is what makes substitution meaningful.
    assert report.observed_value == pytest.approx(1.0)
    assert math.isfinite(report.substituted_value)


def test_healthy_channel_is_not_substituted():
    """Trust at/above TRUSTED_MIN ends the episode; nothing is replaced."""
    runtime = SelfHealRuntime(_bundle(), window_size=WINDOW_SIZE)
    assert runtime.substitute(_outcome(trust=0.9), frozenset({"current"}), _frames()) == []


def test_channel_this_bundle_cannot_serve_is_ignored():
    runtime = SelfHealRuntime(_bundle("current"), window_size=WINDOW_SIZE)
    assert runtime.substitute(_outcome(trust=0.1), frozenset({"pressure"}), _frames()) == []


def test_nothing_isolated_produces_nothing():
    runtime = SelfHealRuntime(_bundle(), window_size=WINDOW_SIZE)
    assert runtime.substitute(_outcome(trust=0.1), frozenset(), _frames()) == []


def test_short_history_produces_nothing_rather_than_a_partial_window():
    """A window shorter than the twin was trained on would be silently wrong."""
    runtime = SelfHealRuntime(_bundle(), window_size=WINDOW_SIZE)
    assert runtime.substitute(_outcome(trust=0.1), frozenset({"current"}), _frames(n=5)) == []


def test_missing_bundle_directory_disables_substitution_without_raising(tmp_path):
    """Fail-safe: no model must never stop telemetry."""
    assert load_self_heal_runtime(tmp_path / "nope", window_size=WINDOW_SIZE) is None


def test_corrupt_bundle_disables_substitution_without_raising(tmp_path):
    (tmp_path / "twin_current.json").write_text("{not json", encoding="utf-8")
    assert load_self_heal_runtime(tmp_path, window_size=WINDOW_SIZE) is None


def test_loads_a_real_bundle_from_disk(tmp_path):
    bundle = _bundle()
    save_bundle(
        tmp_path / "twin_current",
        channel=bundle.channel,
        reconstructor=bundle.reconstructor,
        scaler=bundle.scaler,
        residual_mean=bundle.residual_mean,
        residual_std=bundle.residual_std,
        hidden_size=bundle.hidden_size,
        skill=bundle.skill,
        trained_on=bundle.trained_on,
    )
    runtime = load_self_heal_runtime(tmp_path, window_size=WINDOW_SIZE)
    assert runtime is not None
    assert runtime.channel == "current"


def test_substitution_never_mutates_the_telemetry_frame():
    """The reconstruction is reported alongside the frame, never written into
    it: the frozen contract must keep carrying what the sensor actually said."""
    runtime = SelfHealRuntime(_bundle(), window_size=WINDOW_SIZE)
    frames = _frames(current=0.77)
    runtime.substitute(_outcome(trust=0.1), frozenset({"current"}), frames)
    assert frames[-1].sensors.current == pytest.approx(0.77)
