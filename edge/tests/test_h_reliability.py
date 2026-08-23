"""P2 tests -- historical-reliability signal provider (D009).

Validates HReliabilityProvider in isolation:
  - initialization, EMA arithmetic, output bounds, per-channel independence,
    bool-to-float mapping, recovery dynamics, and SignalProvider protocol.

These tests exercise math/interface ONLY.  They make NO claim about:
  - how the outcome is produced (ChannelFlagPolicy is still a seam)
  - real spoof/fault detection accuracy
  - any P2 trust acceptance gate

Pending items deliberately NOT tested here (still undecided):
  - lambda=0.7 (U01 pending)
  - c signal definition (U01)
  - k signal definition (U02)
  - ChannelFlagPolicy (seam)
"""

import pytest
from app.schemas.contracts import CHANNELS

from edge.trust.engine import SignalProvider
from edge.trust.h_reliability import GAMMA, H_INIT, HReliabilityProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drive_bad(provider: HReliabilityProvider, channel: str, n: int) -> list[float]:
    """Record n consecutive unhealthy outcomes; return h after each."""
    results = []
    for _ in range(n):
        provider.record_outcome(channel, was_healthy=False)
        results.append(provider.evaluate(channel))
    return results


def _drive_good(provider: HReliabilityProvider, channel: str, n: int) -> list[float]:
    """Record n consecutive healthy outcomes; return h after each."""
    results = []
    for _ in range(n):
        provider.record_outcome(channel, was_healthy=True)
        results.append(provider.evaluate(channel))
    return results


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


def test_all_channels_initialize_to_h0():
    """All six channels start at H_INIT = 1.0."""
    p = HReliabilityProvider()
    for ch in CHANNELS:
        assert p.evaluate(ch) == pytest.approx(H_INIT)


def test_init_channel_set_matches_frozen_channels():
    """snapshot keys must match exactly the frozen CHANNELS tuple."""
    p = HReliabilityProvider()
    assert set(p.snapshot().keys()) == set(CHANNELS)


# ---------------------------------------------------------------------------
# 2. evaluate() returns initialized value before any outcome
# ---------------------------------------------------------------------------


def test_evaluate_before_any_record_returns_h0():
    p = HReliabilityProvider()
    # All channels should still be at 1.0; call evaluate directly.
    for ch in CHANNELS:
        assert p.evaluate(ch) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3. One bad outcome: 1.0 -> GAMMA * 1.0 + (1-GAMMA) * 0.0 = 0.95
# ---------------------------------------------------------------------------


def test_one_bad_outcome_decays_to_gamma():
    """h_1 = GAMMA * 1.0 + 0 = 0.95 after one unhealthy window."""
    p = HReliabilityProvider()
    p.record_outcome("pressure", was_healthy=False)
    assert p.evaluate("pressure") == pytest.approx(GAMMA, abs=1e-9)


# ---------------------------------------------------------------------------
# 4. Repeated bad outcomes follow EMA formula
# ---------------------------------------------------------------------------


def test_repeated_bad_outcomes_follow_ema():
    """h_n = GAMMA^n after n consecutive unhealthy windows from h0=1.0."""
    p = HReliabilityProvider()
    for n, h in enumerate(_drive_bad(p, "temperature", 5), start=1):
        expected = GAMMA**n  # h0=1.0, so h_n = GAMMA^n * 1 + 0
        assert h == pytest.approx(expected, abs=1e-9), f"window {n}: expected {expected}, got {h}"


# ---------------------------------------------------------------------------
# 5. A clean outcome from a degraded state increases h
# ---------------------------------------------------------------------------


def test_clean_outcome_increases_h():
    """After a bad outcome (h=0.95), a clean outcome should push h up."""
    p = HReliabilityProvider()
    p.record_outcome("vibration", was_healthy=False)
    h_bad = p.evaluate("vibration")  # 0.95

    p.record_outcome("vibration", was_healthy=True)
    h_clean = p.evaluate("vibration")  # 0.95 * 0.95 + 0.05 * 1.0 = 0.9525

    assert h_clean > h_bad
    expected = GAMMA * h_bad + (1.0 - GAMMA) * 1.0
    assert h_clean == pytest.approx(expected, abs=1e-9)


# ---------------------------------------------------------------------------
# 6. Recovery from a low value
# ---------------------------------------------------------------------------


def test_recovery_from_low_value_is_monotonically_increasing():
    """After many bad outcomes h is low; consecutive clean outcomes raise it monotonically."""
    p = HReliabilityProvider()
    # Drive h well below 0.5 (~0.36 after 20 bad windows).
    _drive_bad(p, "gas", 20)
    assert p.evaluate("gas") < 0.5

    # Now recover: each good outcome should raise h.
    trail = _drive_good(p, "gas", 15)
    assert trail == sorted(trail), "recovery must be monotonically increasing"


def test_recovery_never_exceeds_one():
    """h must stay <= 1.0 even after many clean outcomes."""
    p = HReliabilityProvider()
    # Start from 0.0 (manually degrade to near 0).
    _drive_bad(p, "current", 200)
    # Recover with 200 clean outcomes.
    for _ in range(200):
        p.record_outcome("current", was_healthy=True)
    assert p.evaluate("current") <= 1.0


# ---------------------------------------------------------------------------
# 7. Values remain bounded in [0, 1]
# ---------------------------------------------------------------------------


def test_values_bounded_after_many_bad_outcomes():
    """h must never go below 0.0."""
    p = HReliabilityProvider()
    for _ in range(500):
        p.record_outcome("humidity", was_healthy=False)
    assert 0.0 <= p.evaluate("humidity") <= 1.0


def test_values_bounded_after_many_good_outcomes():
    """h must never exceed 1.0."""
    p = HReliabilityProvider()
    for _ in range(500):
        p.record_outcome("humidity", was_healthy=True)
    assert 0.0 <= p.evaluate("humidity") <= 1.0


# ---------------------------------------------------------------------------
# 8. Per-channel independence
# ---------------------------------------------------------------------------


def test_record_outcome_only_updates_specified_channel():
    """Updating one channel must not change any other channel."""
    p = HReliabilityProvider()
    p.record_outcome("pressure", was_healthy=False)

    # Pressure should have decayed.
    assert p.evaluate("pressure") == pytest.approx(GAMMA, abs=1e-9)

    # Every other channel must still be at H_INIT.
    for ch in CHANNELS:
        if ch != "pressure":
            assert p.evaluate(ch) == pytest.approx(
                H_INIT
            ), f"channel {ch!r} was unexpectedly modified"


def test_independent_channels_do_not_interfere_over_many_windows():
    """Drive each channel with a distinct number of bad outcomes; verify independence."""
    p = HReliabilityProvider()
    counts = {ch: i for i, ch in enumerate(CHANNELS)}  # 0..5 bad outcomes per ch

    for ch, n in counts.items():
        for _ in range(n):
            p.record_outcome(ch, was_healthy=False)

    for ch, n in counts.items():
        expected = GAMMA**n  # h0=1.0
        assert p.evaluate(ch) == pytest.approx(
            expected, abs=1e-9
        ), f"channel {ch!r}: expected {expected:.6f}, got {p.evaluate(ch):.6f}"


# ---------------------------------------------------------------------------
# 9. record_outcome bool mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("was_healthy,expected_outcome", [(True, 1.0), (False, 0.0)])
def test_bool_maps_to_correct_outcome(was_healthy, expected_outcome):
    """True -> 1.0 contribution; False -> 0.0 contribution to EMA."""
    p = HReliabilityProvider()
    p.record_outcome("temperature", was_healthy=was_healthy)
    # h_1 = GAMMA * 1.0 + (1 - GAMMA) * expected_outcome
    expected_h = GAMMA * H_INIT + (1.0 - GAMMA) * expected_outcome
    assert p.evaluate("temperature") == pytest.approx(expected_h, abs=1e-9)


# ---------------------------------------------------------------------------
# 10. SignalProvider protocol compliance
# ---------------------------------------------------------------------------


def test_satisfies_signal_provider_protocol():
    """HReliabilityProvider must be recognised as a SignalProvider at runtime."""
    p = HReliabilityProvider()
    assert isinstance(
        p, SignalProvider
    ), "HReliabilityProvider does not satisfy the SignalProvider runtime-checkable protocol"


def test_evaluate_signature_returns_float():
    """evaluate(channel) must return a plain float in [0, 1]."""
    p = HReliabilityProvider()
    for ch in CHANNELS:
        result = p.evaluate(ch)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# 11. Unknown channel handling (consistent with TrustEngine convention)
# ---------------------------------------------------------------------------


def test_evaluate_unknown_channel_raises_value_error():
    with pytest.raises(ValueError, match="unknown channel"):
        HReliabilityProvider().evaluate("flow")


def test_record_outcome_unknown_channel_raises_value_error():
    with pytest.raises(ValueError, match="unknown channel"):
        HReliabilityProvider().record_outcome("flow", was_healthy=True)


def test_record_outcome_does_not_mutate_state_on_unknown_channel():
    """State must not be partially updated before the ValueError is raised."""
    p = HReliabilityProvider()
    before = p.snapshot()
    with pytest.raises(ValueError):
        p.record_outcome("flow", was_healthy=False)
    assert p.snapshot() == before


# ---------------------------------------------------------------------------
# 12. snapshot() correctness
# ---------------------------------------------------------------------------


def test_snapshot_returns_copy_not_reference():
    """Mutating the returned snapshot dict must not change provider state."""
    p = HReliabilityProvider()
    snap = p.snapshot()
    snap["temperature"] = 0.0  # mutate the copy
    assert p.evaluate("temperature") == pytest.approx(H_INIT)  # provider unchanged


def test_snapshot_reflects_recorded_outcomes():
    """snapshot() must reflect the current EMA state after record_outcome calls."""
    p = HReliabilityProvider()
    p.record_outcome("current", was_healthy=False)
    snap = p.snapshot()
    assert snap["current"] == pytest.approx(GAMMA, abs=1e-9)
    for ch in CHANNELS:
        if ch != "current":
            assert snap[ch] == pytest.approx(H_INIT)
