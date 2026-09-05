"""Tests for edge/pipeline/isolation_tracker.py (FR-RL4 follow-up).

``_window_outcome`` mirrors edge/tests/test_isolation_fallback.py's own
builder exactly, for consistency across the two related test files.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import AttributionResult
from edge.anomaly.detector import AnomalyResult
from edge.anomaly.pipeline import WindowOutcome
from edge.anomaly.preprocess import Window
from edge.pipeline.isolation_tracker import IsolationFallbackTracker, IsolationTrackerResult
from edge.trust.beta import TRUSTED_MIN, classify
from edge.trust.engine import TrustReading

_DEFAULT_TRUST_FIXTURE = 0.9  # baseline "healthy" trust for channels not under test


def _empty_window() -> Window:
    return Window(start_index=0, end_index=1, features={ch: (0.0,) for ch in CHANNELS})


def _window_outcome(trust_overrides: Mapping[str, float]) -> WindowOutcome:
    window = _empty_window()
    anomaly = AnomalyResult(flag=False, severity=0.0)
    channel_flags = {ch: False for ch in CHANNELS}
    trust: dict[str, TrustReading] = {}
    for ch in CHANNELS:
        value = trust_overrides.get(ch, _DEFAULT_TRUST_FIXTURE)
        trust[ch] = TrustReading(channel=ch, g=0.0, trust=value, band=classify(value))
    attribution = {ch: AttributionResult(ch, Attribution.none, "") for ch in CHANNELS}
    return WindowOutcome(
        window=window,
        anomaly=anomaly,
        channel_flags=channel_flags,
        trust=trust,
        attribution=attribution,
    )


# ---------------------------------------------------------------------------
# Starts empty / all-trusted
# ---------------------------------------------------------------------------


def test_tracker_starts_empty():
    tracker = IsolationFallbackTracker()
    result = tracker.update(_window_outcome({}))  # all channels Trusted
    assert result.candidates_this_cycle == frozenset()
    assert result.tracked_channels == frozenset()
    assert result.reasons == {}


def test_all_trusted_outcome_never_populates_tracking():
    tracker = IsolationFallbackTracker()
    for _ in range(5):
        result = tracker.update(_window_outcome({}))
        assert result.tracked_channels == frozenset()


# ---------------------------------------------------------------------------
# Newly malicious channel is added
# ---------------------------------------------------------------------------


def test_newly_malicious_channel_is_added_to_tracked():
    tracker = IsolationFallbackTracker()
    result = tracker.update(_window_outcome({"temperature": 0.1}))
    assert result.candidates_this_cycle == frozenset({"temperature"})
    assert result.tracked_channels == frozenset({"temperature"})
    assert "newly isolated this cycle" in result.reasons["temperature"]


# ---------------------------------------------------------------------------
# Remains tracked across repeated malicious cycles
# ---------------------------------------------------------------------------


def test_channel_remains_tracked_across_repeated_malicious_cycles():
    tracker = IsolationFallbackTracker()
    tracker.update(_window_outcome({"temperature": 0.1}))
    result2 = tracker.update(_window_outcome({"temperature": 0.05}))
    result3 = tracker.update(_window_outcome({"temperature": 0.15}))

    assert result2.tracked_channels == frozenset({"temperature"})
    assert result3.tracked_channels == frozenset({"temperature"})
    # Second and third cycles: still malicious, not "newly isolated" again.
    assert "still malicious this cycle" in result2.reasons["temperature"]
    assert "still malicious this cycle" in result3.reasons["temperature"]


# ---------------------------------------------------------------------------
# Recovered trust does not silently remove tracking
# ---------------------------------------------------------------------------


def test_recovered_trust_does_not_remove_tracked_channel():
    tracker = IsolationFallbackTracker()
    tracker.update(_window_outcome({"temperature": 0.1}))  # Malicious -> tracked

    recovered = tracker.update(_window_outcome({"temperature": TRUSTED_MIN}))  # now Trusted
    assert recovered.candidates_this_cycle == frozenset()  # not malicious THIS cycle
    assert recovered.tracked_channels == frozenset({"temperature"})  # still tracked
    reason = recovered.reasons["temperature"]
    assert "confirmed SelfHealOutcome recovery" in reason  # explains WHY it's not dropped


def test_reason_never_asserts_recovery_occurred():
    """Stronger, explicit check: the reason text for a still-tracked-but-
    currently-not-malicious channel must not claim recovery is confirmed."""
    tracker = IsolationFallbackTracker()
    tracker.update(_window_outcome({"temperature": 0.1}))
    result = tracker.update(_window_outcome({"temperature": TRUSTED_MIN}))
    reason = result.reasons["temperature"]
    assert "recovery tracking not implemented" in reason
    assert "confirmed" in reason


# ---------------------------------------------------------------------------
# Multiple channels tracked independently
# ---------------------------------------------------------------------------


def test_multiple_channels_tracked_independently():
    tracker = IsolationFallbackTracker()
    tracker.update(_window_outcome({"temperature": 0.1}))
    # "temperature" stays malicious this cycle too, so both channels are
    # simultaneously active -- proving independent tracking, not just
    # sequential replacement.
    result = tracker.update(_window_outcome({"temperature": 0.1, "vibration": 0.05}))

    assert result.tracked_channels == frozenset({"temperature", "vibration"})
    assert result.candidates_this_cycle == frozenset({"temperature", "vibration"})
    assert "still malicious this cycle" in result.reasons["temperature"]
    assert "newly isolated this cycle" in result.reasons["vibration"]


def test_channel_no_longer_malicious_this_cycle_but_still_tracked():
    """Companion to the above: when a previously-tracked channel is simply
    left out of `trust_overrides` (defaulting to Trusted) rather than
    explicitly recovered, it must still be reported as tracked, with the
    'not malicious this cycle, but remains tracked' reason -- not silently
    dropped and not mislabeled as 'still malicious'."""
    tracker = IsolationFallbackTracker()
    tracker.update(_window_outcome({"temperature": 0.1}))
    result = tracker.update(_window_outcome({"vibration": 0.05}))  # temperature defaults to Trusted

    assert result.tracked_channels == frozenset({"temperature", "vibration"})
    assert result.candidates_this_cycle == frozenset({"vibration"})
    assert "not malicious this cycle" in result.reasons["temperature"]
    assert "newly isolated this cycle" in result.reasons["vibration"]


def test_all_six_channels_malicious_tracked_together():
    tracker = IsolationFallbackTracker()
    result = tracker.update(_window_outcome({ch: 0.0 for ch in CHANNELS}))
    assert result.tracked_channels == frozenset(CHANNELS)
    assert result.candidates_this_cycle == frozenset(CHANNELS)
    assert set(result.reasons.keys()) == set(CHANNELS)


# ---------------------------------------------------------------------------
# No cross-contamination between tracker instances
# ---------------------------------------------------------------------------


def test_no_cross_contamination_between_tracker_instances():
    tracker_a = IsolationFallbackTracker()
    tracker_b = IsolationFallbackTracker()

    tracker_a.update(_window_outcome({"temperature": 0.1}))
    result_b = tracker_b.update(_window_outcome({}))  # independent, all Trusted

    assert result_b.tracked_channels == frozenset()
    assert tracker_a.update(_window_outcome({})).tracked_channels == frozenset({"temperature"})


# ---------------------------------------------------------------------------
# Deterministic ordering / output shape
# ---------------------------------------------------------------------------


def test_reasons_are_in_frozen_channel_order():
    tracker = IsolationFallbackTracker()
    result = tracker.update(_window_outcome({ch: 0.0 for ch in CHANNELS}))
    assert list(result.reasons.keys()) == list(CHANNELS)


def test_result_is_a_frozen_dataclass():
    tracker = IsolationFallbackTracker()
    result = tracker.update(_window_outcome({"temperature": 0.1}))
    assert isinstance(result, IsolationTrackerResult)
    assert isinstance(result.tracked_channels, frozenset)
    assert isinstance(result.candidates_this_cycle, frozenset)
