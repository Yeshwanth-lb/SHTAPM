"""Tests for edge/pipeline/cycle.py (P2->P3 narrow adapter).

`DIVERGENCE_THRESHOLD_FIXTURE`/`SUBSTITUTION_MAX_SECONDS_FIXTURE` below are
TEST FIXTURES ONLY -- neither is presented as a project specification
value. `_DEFAULT_TRUST_FIXTURE` is test scaffolding (a baseline "healthy"
trust for channels not under test in a given case). `uncertainty_cap`/the
scaling formula are NOT fixtures: they are the real, D020-approved values
(`UNCERTAINTY_CAP_D020` / `linear_scaling`), imported directly.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping

import pytest
from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import AttributionResult
from edge.anomaly.detector import AnomalyResult
from edge.anomaly.pipeline import WindowOutcome
from edge.anomaly.preprocess import Window
from edge.pipeline.cycle import process_isolated_channels
from edge.pipeline.divergence import DivergenceScorer
from edge.pipeline.self_heal import UNCERTAINTY_CAP_D020, SelfHealOrchestrator
from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy, linear_scaling
from edge.trust.beta import classify
from edge.trust.engine import TrustReading

# ---------------------------------------------------------------------------
# Fixtures -- TEST FIXTURES ONLY, never project specification values.
# ---------------------------------------------------------------------------

DIVERGENCE_THRESHOLD_FIXTURE = 3.0
SUBSTITUTION_MAX_SECONDS_FIXTURE = 60.0
_DEFAULT_TRUST_FIXTURE = 0.9  # baseline "healthy" trust for channels not under test


class _FixedReconstructionTwinFixture:
    """TEST FIXTURE ONLY -- not a production TwinReconstructor
    implementation (edge/models/twin.py ships none by design). Always
    reconstructs to a caller-supplied constant, regardless of window."""

    def __init__(self, value: float) -> None:
        self._value = value

    def reconstruct(self, window: Window, missing_channel: str) -> float:
        return self._value


class _CapturingTwinFixture:
    """TEST FIXTURE ONLY. Records every (window, missing_channel) it was
    called with, so a test can assert exactly what the adapter passed
    through, and returns a fixed reconstruction value."""

    def __init__(self, value: float) -> None:
        self._value = value
        self.calls: list[tuple[Window, str]] = []

    def reconstruct(self, window: Window, missing_channel: str) -> float:
        self.calls.append((window, missing_channel))
        return self._value


def _empty_window() -> Window:
    return Window(start_index=0, end_index=1, features={ch: (0.0,) for ch in CHANNELS})


def _window_outcome(trust_overrides: Mapping[str, float]) -> WindowOutcome:
    """Build a minimal, realistic WindowOutcome. Only `window` and `trust`
    matter to the adapter under test; anomaly/channel_flags/attribution are
    filled with inert placeholders."""
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


def _make_orchestrator(twin=None):
    twin = twin if twin is not None else _FixedReconstructionTwinFixture(0.0)
    divergence_scorer = DivergenceScorer()
    # Both channels fit identically (same tight fixture spread) so
    # multi-channel tests can reason about either one predictably.
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1], "current": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    calls = {"n": 0}

    def safe_stop():
        calls["n"] += 1

    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=safe_stop,
        substitution_max_seconds=SUBSTITUTION_MAX_SECONDS_FIXTURE,
    )
    return orchestrator, calls


# ---------------------------------------------------------------------------
# Only explicitly-supplied channels are processed -- never derived from trust
# ---------------------------------------------------------------------------


def test_only_explicitly_supplied_channels_are_processed():
    """A channel with LOW trust (well below TRUSTED_MIN) but absent from
    isolated_channels must be ignored -- proves isolation is never
    re-derived from trust/band by this adapter."""
    orchestrator, calls = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.9, "vibration": 0.1})

    result = process_isolated_channels(
        outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 0.0},
        orchestrator=orchestrator,
    )

    assert set(result.keys()) == {"temperature"}
    assert "vibration" not in result
    assert calls["n"] == 0


def test_empty_isolated_channels_returns_empty_dict():
    orchestrator, calls = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2})

    result = process_isolated_channels(
        outcome, isolated_channels=set(), raw_values={}, orchestrator=orchestrator
    )

    assert result == {}
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Values pass through unchanged
# ---------------------------------------------------------------------------


def test_trust_passed_through_unchanged():
    """A channel already at/above TRUSTED_MIN must be reported as
    recovered/not-substituted -- proves outcome.trust[channel].trust (not
    some other value) reached process_isolated_channel."""
    orchestrator, _ = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.95})

    result = process_isolated_channels(
        outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 0.0},
        orchestrator=orchestrator,
    )

    assert result["temperature"].substituted is False


def test_low_trust_reported_as_substituted_through_adapter():
    """Companion to test_trust_passed_through_unchanged: a trust value
    BELOW TRUSTED_MIN must produce substituted=True through the adapter.
    Paired with the above (which uses an ABOVE-threshold value), this
    proves the actual outcome.trust[channel].trust value reaches
    process_isolated_channel -- a bug that hardcoded a fixed high trust
    value would pass the above test alone but fail this one."""
    orchestrator, _ = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2})

    result = process_isolated_channels(
        outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 0.0},
        orchestrator=orchestrator,
    )

    assert result["temperature"].substituted is True


def test_window_passed_through_unchanged():
    twin = _CapturingTwinFixture(0.0)
    orchestrator, _ = _make_orchestrator(twin=twin)
    outcome = _window_outcome({"temperature": 0.2})

    process_isolated_channels(
        outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 0.0},
        orchestrator=orchestrator,
    )

    assert len(twin.calls) == 1
    called_window, called_channel = twin.calls[0]
    assert called_window is outcome.window
    assert called_channel == "temperature"


def test_raw_value_passed_through_unchanged_escalates():
    """twin reconstructs to 0.0; a raw_value far from 0.0 must produce a
    large divergence and escalate -- proves the exact supplied raw_values
    entry (not some derived/default value) reached the residual."""
    orchestrator, calls = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2})

    result = process_isolated_channels(
        outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 100.0},
        orchestrator=orchestrator,
    )

    assert result["temperature"].escalated is True
    assert calls["n"] == 1


def test_raw_value_near_reconstruction_does_not_escalate():
    orchestrator, calls = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2})

    result = process_isolated_channels(
        outcome,
        isolated_channels={"temperature"},
        raw_values={"temperature": 0.0},
        orchestrator=orchestrator,
    )

    assert result["temperature"].escalated is False
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Multiple channels in one call
# ---------------------------------------------------------------------------


def test_two_channels_processed_independently():
    """Two channels named in isolated_channels together must each get
    their own correct window/raw_value/trust routed through, with no
    cross-contamination between the two result entries."""
    orchestrator, calls = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2, "current": 0.2})

    result = process_isolated_channels(
        outcome,
        isolated_channels={"temperature", "current"},
        # "temperature" stays near its reconstruction (no escalation);
        # "current" is far from it (escalates) -- proves per-channel
        # raw_values are routed independently, not shared/averaged.
        raw_values={"temperature": 0.0, "current": 100.0},
        orchestrator=orchestrator,
    )

    assert set(result.keys()) == {"temperature", "current"}
    assert result["temperature"].escalated is False
    assert result["temperature"].substituted is True
    assert result["current"].escalated is True
    assert result["current"].substituted is False
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Required-input failure behavior
# ---------------------------------------------------------------------------


def test_unknown_channel_in_isolated_channels_raises():
    orchestrator, _ = _make_orchestrator()
    outcome = _window_outcome({})

    with pytest.raises(ValueError):
        process_isolated_channels(
            outcome,
            isolated_channels={"not_a_channel"},
            raw_values={"not_a_channel": 0.0},
            orchestrator=orchestrator,
        )


def test_missing_raw_value_for_isolated_channel_raises():
    orchestrator, _ = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2})

    with pytest.raises(ValueError):
        process_isolated_channels(
            outcome, isolated_channels={"temperature"}, raw_values={}, orchestrator=orchestrator
        )


def test_unknown_channel_prevents_side_effects_for_valid_channel_in_same_call():
    """isolated_channels naming one valid channel and one unknown channel
    together must raise ValueError WITHOUT any side effect for the valid
    channel -- proves all channels are validated before any is acted on
    (validate-all-upfront, Item 4 / Option A)."""
    orchestrator, calls = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2})

    with pytest.raises(ValueError):
        process_isolated_channels(
            outcome,
            isolated_channels={"temperature", "not_a_channel"},
            raw_values={"temperature": 0.0, "not_a_channel": 0.0},
            orchestrator=orchestrator,
        )

    assert calls["n"] == 0
    assert orchestrator._episodes == {}


def test_missing_raw_value_prevents_side_effects_for_valid_channel_in_same_call():
    """Same guarantee when the second channel is missing from raw_values
    instead of being an unknown channel name."""
    orchestrator, calls = _make_orchestrator()
    outcome = _window_outcome({"temperature": 0.2, "current": 0.2})

    with pytest.raises(ValueError):
        process_isolated_channels(
            outcome,
            isolated_channels={"temperature", "current"},
            raw_values={"temperature": 0.0},  # "current" is missing
            orchestrator=orchestrator,
        )

    assert calls["n"] == 0
    assert orchestrator._episodes == {}


def test_isolated_channels_and_raw_values_have_no_default():
    """Structural proof, mirroring test_uncertainty.py's scaling_fn check:
    both required inputs must have no library default."""
    sig = inspect.signature(process_isolated_channels)
    assert sig.parameters["isolated_channels"].default is inspect.Parameter.empty
    assert sig.parameters["raw_values"].default is inspect.Parameter.empty
