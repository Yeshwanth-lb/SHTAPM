"""Tests for edge/pipeline/isolation_fallback.py (FR-RL4, decision-only,
stateless slice).

``_window_outcome`` mirrors edge/tests/test_cycle.py's own builder exactly
(same helper shape, same "only trust matters to the code under test"
convention) so these tests stay consistent with the rest of the P2/P3 test
suite's style.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import AttributionResult
from edge.anomaly.detector import AnomalyResult
from edge.anomaly.pipeline import WindowOutcome
from edge.anomaly.preprocess import Window
from edge.pipeline.isolation_fallback import IsolationDecision, decide_isolation
from edge.trust.beta import MALICIOUS_MAX, TRUSTED_MIN, classify
from edge.trust.engine import TrustReading

_DEFAULT_TRUST_FIXTURE = 0.9  # baseline "healthy" trust for channels not under test


def _empty_window() -> Window:
    return Window(start_index=0, end_index=1, features={ch: (0.0,) for ch in CHANNELS})


def _window_outcome(trust_overrides: Mapping[str, float]) -> WindowOutcome:
    """Build a minimal, realistic WindowOutcome. Only `trust` matters to
    decide_isolation; anomaly/channel_flags/attribution are inert
    placeholders (decide_isolation must not read them for its decision)."""
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
# Trusted / Suspicious / Malicious, in isolation
# ---------------------------------------------------------------------------


def test_all_trusted_channels_yield_no_isolation_candidates():
    outcome = _window_outcome({})  # every channel defaults to 0.9 (Trusted)
    decision = decide_isolation(outcome)
    assert decision.isolated_channels == frozenset()


def test_single_malicious_channel_is_isolation_candidate():
    outcome = _window_outcome({"temperature": 0.1})  # well below MALICIOUS_MAX
    decision = decide_isolation(outcome)
    assert decision.isolated_channels == frozenset({"temperature"})


def test_suspicious_channel_is_not_isolated():
    mid = (MALICIOUS_MAX + TRUSTED_MIN) / 2  # squarely inside the Suspicious band
    outcome = _window_outcome({"vibration": mid})
    decision = decide_isolation(outcome)
    assert decision.isolated_channels == frozenset()


def test_trusted_channel_is_not_isolation_candidate():
    outcome = _window_outcome({"pressure": TRUSTED_MIN})
    decision = decide_isolation(outcome)
    assert "pressure" not in decision.isolated_channels


# ---------------------------------------------------------------------------
# Frozen-boundary exactness (no new threshold — must match classify() exactly)
# ---------------------------------------------------------------------------


def test_trust_exactly_at_malicious_max_is_not_isolated():
    """classify() uses strict '<' for Malicious — trust == MALICIOUS_MAX is
    Suspicious, not Malicious (edge/trust/beta.py:classify)."""
    outcome = _window_outcome({"gas": MALICIOUS_MAX})
    decision = decide_isolation(outcome)
    assert "gas" not in decision.isolated_channels


def test_trust_just_below_malicious_max_is_isolated():
    outcome = _window_outcome({"gas": MALICIOUS_MAX - 1e-9})
    decision = decide_isolation(outcome)
    assert "gas" in decision.isolated_channels


def test_trust_exactly_at_trusted_min_is_not_isolated():
    outcome = _window_outcome({"current": TRUSTED_MIN})
    decision = decide_isolation(outcome)
    assert "current" not in decision.isolated_channels


# ---------------------------------------------------------------------------
# Mixed / multi-channel
# ---------------------------------------------------------------------------


def test_mixed_bands_isolates_only_the_malicious_channels():
    outcome = _window_outcome(
        {
            "temperature": 0.9,  # Trusted
            "vibration": 0.5,  # Suspicious
            "pressure": 0.1,  # Malicious
            "humidity": 0.35,  # Malicious
            "gas": TRUSTED_MIN,  # Trusted (boundary)
            "current": MALICIOUS_MAX,  # Suspicious (boundary)
        }
    )
    decision = decide_isolation(outcome)
    assert decision.isolated_channels == frozenset({"pressure", "humidity"})


def test_all_six_channels_malicious_are_all_isolated():
    outcome = _window_outcome({ch: 0.0 for ch in CHANNELS})
    decision = decide_isolation(outcome)
    assert decision.isolated_channels == frozenset(CHANNELS)


# ---------------------------------------------------------------------------
# Output shape: reasons, immutability, statelessness
# ---------------------------------------------------------------------------


def test_reasons_present_for_every_frozen_channel():
    outcome = _window_outcome({"temperature": 0.1, "vibration": 0.5})
    decision = decide_isolation(outcome)
    assert set(decision.reasons.keys()) == set(CHANNELS)
    assert all(isinstance(r, str) and r for r in decision.reasons.values())


def test_decision_is_a_frozen_dataclass_with_frozenset_isolated_channels():
    outcome = _window_outcome({"temperature": 0.1})
    decision = decide_isolation(outcome)
    assert isinstance(decision, IsolationDecision)
    assert isinstance(decision.isolated_channels, frozenset)
    with pytest.raises(Exception):  # noqa: B017 -- frozen dataclass raises FrozenInstanceError
        decision.isolated_channels = frozenset()  # must reject mutation


def test_decide_isolation_is_stateless_across_independent_calls():
    """Two independent calls must not leak state: a malicious channel in
    the first call must not linger into a second, all-trusted call."""
    first = decide_isolation(_window_outcome({"temperature": 0.1}))
    assert first.isolated_channels == frozenset({"temperature"})

    second = decide_isolation(_window_outcome({}))  # all Trusted
    assert second.isolated_channels == frozenset()

    # Calling again with the same malicious input as `first` reproduces the
    # same result — no accumulated/mutated state from the calls in between.
    third = decide_isolation(_window_outcome({"temperature": 0.1}))
    assert third.isolated_channels == frozenset({"temperature"})


def test_decide_isolation_does_not_read_anomaly_or_attribution():
    """Structural proof the decision is trust-band-only: an outcome with
    anomaly.flag=True and attribution=attack on a TRUSTED channel must
    still NOT isolate it (decide_isolation must ignore both fields)."""
    outcome = _window_outcome({"temperature": TRUSTED_MIN})
    outcome = WindowOutcome(
        window=outcome.window,
        anomaly=AnomalyResult(flag=True, severity=1.0),
        channel_flags={ch: True for ch in CHANNELS},
        trust=outcome.trust,
        attribution={
            ch: AttributionResult(ch, Attribution.attack, "irrelevant") for ch in CHANNELS
        },
    )
    decision = decide_isolation(outcome)
    assert "temperature" not in decision.isolated_channels
