"""Tests for edge/eval/u05_divergence_analysis.py -- hardware-free,
fixture-only. A stub TwinReconstructor is used throughout (never the real,
untrained LSTMTwinReconstructor) -- this module makes no reconstruction-
accuracy claim regardless of which twin implementation is injected.
"""

from __future__ import annotations

from app.schemas.build import build_telemetry
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Preprocessor
from edge.eval.u05_capture_loader import (
    load_telemetry_capture,
    ordered_messages,
    windows_from_capture,
)
from edge.eval.u05_divergence_analysis import (
    ChannelDivergenceSummary,
    compute_residuals,
    score_residuals,
)
from edge.pipeline.divergence import DivergenceScorer

_SENSORS = {
    "temperature": 26.0,
    "vibration": 0.03,
    "pressure": 1013.0,
    "humidity": 45.0,
    "gas": 150.0,
    "current": 0.0,
}


class _ConstantTwin:
    """Test-only stub: always reconstructs to a fixed value, regardless of
    window/channel -- NOT the real LSTMTwinReconstructor, no accuracy
    claim. Makes residuals fully predictable for assertions."""

    def __init__(self, value: float) -> None:
        self._value = value

    def reconstruct(self, window, missing_channel: str) -> float:  # noqa: ARG002
        return self._value


def _capture(vibration_values: list[float], window_size: int = 3):
    preprocessor = Preprocessor(
        median_kernel=1, low_pass_alpha=1.0, window_size=window_size, step=1
    )
    lines = [
        build_telemetry(
            "pump-01", "2026-09-07T00:00:00.000Z", {**_SENSORS, "vibration": v}, sample_seq=i
        ).model_dump_json()
        for i, v in enumerate(vibration_values)
    ]
    result = load_telemetry_capture(lines)
    messages = ordered_messages(result)
    windows = windows_from_capture(result, preprocessor)
    return windows, messages


def test_compute_residuals_matches_reconstruction_minus_raw():
    # window_size=3 over 4 frames -> 2 windows; last-frame vibration per
    # window is 0.2 (window0: frames 0-2) then 0.3 (window1: frames 1-3).
    windows, messages = _capture([0.1, 0.2, 0.3, 0.4])
    twin = _ConstantTwin(1.0)
    residuals = compute_residuals(windows, messages, twin, channels=("vibration",))
    assert residuals["vibration"] == [1.0 - 0.3, 1.0 - 0.4]


def test_compute_residuals_covers_all_frozen_channels_by_default():
    windows, messages = _capture([0.1, 0.2, 0.3])
    twin = _ConstantTwin(0.0)
    residuals = compute_residuals(windows, messages, twin)
    assert set(residuals) == set(CHANNELS)
    assert all(len(v) == len(windows) for v in residuals.values())


def test_compute_residuals_empty_windows_gives_empty_lists():
    twin = _ConstantTwin(0.0)
    residuals = compute_residuals([], [], twin, channels=("vibration",))
    assert residuals == {"vibration": []}


def test_score_residuals_computes_expected_z_scores():
    scorer = DivergenceScorer()
    scorer.fit({"vibration": [0.0, 0.0, 0.0, 0.0]})  # mean=0, std -> numerical floor
    summary = score_residuals({"vibration": [0.0, 1.0]}, scorer)
    assert isinstance(summary["vibration"], ChannelDivergenceSummary)
    expected = [scorer.score("vibration", 0.0), scorer.score("vibration", 1.0)]
    assert summary["vibration"].sample_count == 2
    assert summary["vibration"].z_score_mean == sum(expected) / 2
    assert summary["vibration"].z_score_min == min(expected)
    assert summary["vibration"].z_score_max == max(expected)
    assert summary["vibration"].execution_mode == "offline_analysis"
    assert summary["vibration"].model_status == "diagnostic_unvalidated"


def test_score_residuals_empty_channel_reports_none_not_zero():
    scorer = DivergenceScorer()
    scorer.fit({"vibration": [0.0, 0.1]})
    summary = score_residuals({"vibration": []}, scorer)
    s = summary["vibration"]
    assert s.sample_count == 0
    assert s.z_score_mean is None
    assert s.z_score_min is None
    assert s.z_score_max is None


def test_score_residuals_produces_no_threshold_or_verdict_field():
    """Structural guard: ChannelDivergenceSummary must never grow a
    threshold/verdict/pass-fail field -- U05 stays data-gated."""
    forbidden = {"threshold", "verdict", "pass", "fail", "acceptable", "divergence_threshold"}
    field_names = {f.lower() for f in ChannelDivergenceSummary.__dataclass_fields__}
    assert forbidden.isdisjoint(field_names)
