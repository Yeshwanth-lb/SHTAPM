"""Unit tests for CorrelationProvider (U02 · PROVISIONAL HEURISTIC).

Validates that the cross-sensor correlation k provider works correctly with the
provisional current↔vibration trend-sign heuristic.

Scope: BEHAVIORAL/UNIT VALIDATION ONLY
    These tests verify the heuristic LOGIC and protocol compliance in isolation.
    They do NOT constitute real P2 acceptance (P2-TRUST-H2, P2-ANOM-H3).

These tests make NO claim about:
  - Real spoof/attack detection accuracy
  - Effectiveness on real pump data
  - P2 acceptance criteria (requires SWaT/WADI labeled dataset)
  - Generalization to different pump models or installations

The heuristic is NOT validated physics. Validation requires:
  - SWaT/WADI or real bench data with labeled attacks
  - Tuning of trend detection parameters (currently sign-based, no epsilon)
  - Measurement of false positive/negative rates on real attacks
"""

import pytest
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Window
from edge.trust.k_correlation import CorrelationProvider

# ---------------------------------------------------------------------------
# Helpers: Window Builders
# ---------------------------------------------------------------------------


def _build_window(start_index: int, channels_dict: dict[str, tuple[float, ...]]) -> Window:
    """Construct a Window from per-channel tuples."""
    return Window(
        start_index=start_index,
        end_index=start_index + len(next(iter(channels_dict.values()))),
        features=channels_dict,
    )


def _make_current_ramp(start: float, step: float, length: int = 30) -> tuple[float, ...]:
    """Build current channel: rising/falling ramp.

    Example: start=0.2, step=0.01, length=30 → (0.2, 0.21, ..., 0.49)
    """
    return tuple(start + step * i for i in range(length))


def _make_vibration_ramp(start: float, step: float, length: int = 30) -> tuple[float, ...]:
    """Build vibration channel: rising/falling ramp."""
    return tuple(start + step * i for i in range(length))


def _make_flat_channel(value: float, length: int = 30) -> tuple[float, ...]:
    """Build a channel with constant value (no trend)."""
    return (value,) * length


def _make_correlated_rising_window() -> Window:
    """Both current and vibration rising (trends both +1 = consistent)."""
    return _build_window(
        0,
        {
            "current": _make_current_ramp(0.2, 0.01),  # 0.2 → 0.49
            "vibration": _make_vibration_ramp(0.1, 0.01),  # 0.1 → 0.39
            "temperature": _make_flat_channel(0.5),
            "pressure": _make_flat_channel(0.5),
            "humidity": _make_flat_channel(0.5),
            "gas": _make_flat_channel(0.5),
        },
    )


def _make_anticorrelated_window() -> Window:
    """Current rising, vibration falling (trends +1 and -1 = inconsistent)."""
    return _build_window(
        0,
        {
            "current": _make_current_ramp(0.2, 0.01),  # rising
            "vibration": _make_vibration_ramp(0.9, -0.01),  # falling
            "temperature": _make_flat_channel(0.5),
            "pressure": _make_flat_channel(0.5),
            "humidity": _make_flat_channel(0.5),
            "gas": _make_flat_channel(0.5),
        },
    )


def _make_both_flat_window() -> Window:
    """Both current and vibration flat (trends both 0 = consistent)."""
    return _build_window(
        0,
        {
            "current": _make_flat_channel(0.5),
            "vibration": _make_flat_channel(0.5),
            "temperature": _make_flat_channel(0.5),
            "pressure": _make_flat_channel(0.5),
            "humidity": _make_flat_channel(0.5),
            "gas": _make_flat_channel(0.5),
        },
    )


def _make_current_rising_vibration_flat_window() -> Window:
    """Current rising, vibration flat (trends +1 and 0 = (+1)*0=0 ≥ 0 = pass)."""
    return _build_window(
        0,
        {
            "current": _make_current_ramp(0.2, 0.01),  # rising
            "vibration": _make_flat_channel(0.5),  # flat (trend=0)
            "temperature": _make_flat_channel(0.5),
            "pressure": _make_flat_channel(0.5),
            "humidity": _make_flat_channel(0.5),
            "gas": _make_flat_channel(0.5),
        },
    )


def _make_correlated_falling_window() -> Window:
    """Both current and vibration falling (trends both -1 = consistent)."""
    return _build_window(
        0,
        {
            "current": _make_current_ramp(0.9, -0.01),  # 0.9 → 0.61
            "vibration": _make_vibration_ramp(0.8, -0.01),  # 0.8 → 0.51
            "temperature": _make_flat_channel(0.5),
            "pressure": _make_flat_channel(0.5),
            "humidity": _make_flat_channel(0.5),
            "gas": _make_flat_channel(0.5),
        },
    )


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


def test_init_all_channels_start_at_0_5():
    """All channels initialize to k=0.5 (neutral, no evidence yet)."""
    p = CorrelationProvider()
    for ch in CHANNELS:
        assert p.evaluate(ch) == 0.5, f"{ch} should initialize to 0.5"


def test_init_snapshot():
    """snapshot() returns all channels at 0.5."""
    p = CorrelationProvider()
    snap = p.snapshot()
    assert set(snap.keys()) == set(CHANNELS)
    assert all(v == 0.5 for v in snap.values())


# ---------------------------------------------------------------------------
# 2. Correlated Motion (Both Channels Same Direction)
# ---------------------------------------------------------------------------


def test_correlated_rising_gives_k_1_0():
    """Both current and vibration rising → k=1.0 for both, 1.0 for others."""
    p = CorrelationProvider()
    window = _make_correlated_rising_window()
    p.record_window(window)

    # Current and vibration: consistent
    assert p.evaluate("current") == 1.0, "rising current should have k=1.0"
    assert p.evaluate("vibration") == 1.0, "rising vibration should have k=1.0"

    # Others: not involved in rule
    assert p.evaluate("temperature") == 1.0, "temperature not constrained"
    assert p.evaluate("pressure") == 1.0, "pressure not constrained"
    assert p.evaluate("humidity") == 1.0, "humidity not constrained"
    assert p.evaluate("gas") == 1.0, "gas not constrained"


def test_correlated_falling_gives_k_1_0():
    """Both current and vibration falling → k=1.0 for both."""
    p = CorrelationProvider()
    window = _make_correlated_falling_window()
    p.record_window(window)

    assert p.evaluate("current") == 1.0, "falling current should have k=1.0"
    assert p.evaluate("vibration") == 1.0, "falling vibration should have k=1.0"


# ---------------------------------------------------------------------------
# 3. Anticorrelated Motion (Opposite Directions)
# ---------------------------------------------------------------------------


def test_anticorrelated_gives_k_0_0():
    """Current rising, vibration falling → k=0.0 for both (violation)."""
    p = CorrelationProvider()
    window = _make_anticorrelated_window()
    p.record_window(window)

    # Both channels suspect (we can't tell which is lying)
    assert p.evaluate("current") == 0.0, "rising current vs. falling vibration violates rule"
    assert p.evaluate("vibration") == 0.0, "falling vibration vs. rising current violates rule"

    # Others not involved
    assert p.evaluate("temperature") == 1.0, "temperature unaffected by pair rule"
    assert p.evaluate("pressure") == 1.0, "pressure unaffected by pair rule"


# ---------------------------------------------------------------------------
# 4. Both Flat (No Trend)
# ---------------------------------------------------------------------------


def test_both_flat_gives_k_1_0():
    """Both flat (trend=0 for both) → 0*0=0 ≥ 0 → k=1.0 (consistent)."""
    p = CorrelationProvider()
    window = _make_both_flat_window()
    p.record_window(window)

    assert p.evaluate("current") == 1.0, "flat current + flat vibration is consistent"
    assert p.evaluate("vibration") == 1.0, "flat vibration + flat current is consistent"


# ---------------------------------------------------------------------------
# 5. One Rising, One Flat (Edge Case)
# ---------------------------------------------------------------------------


def test_one_rising_one_flat_gives_k_1_0():
    """Current rising, vibration flat → (+1)*0=0 ≥ 0 → k=1.0 (passes)."""
    p = CorrelationProvider()
    window = _make_current_rising_vibration_flat_window()
    p.record_window(window)

    # Both pass: 0 * anything = 0 ≥ 0
    assert (
        p.evaluate("current") == 1.0
    ), "rising current + flat vibration should pass (0 * 1 = 0 ≥ 0)"
    assert (
        p.evaluate("vibration") == 1.0
    ), "flat vibration + rising current should pass (0 * 1 = 0 ≥ 0)"


# ---------------------------------------------------------------------------
# 6. Per-Channel Independence
# ---------------------------------------------------------------------------


def test_other_channels_unaffected_by_pair_rule():
    """Temperature anomaly doesn't affect k_current or k_vibration."""
    # Create a window where current and vibration are consistent,
    # but temperature is anomalous
    window = _build_window(
        0,
        {
            "current": _make_current_ramp(0.2, 0.01),  # rising
            "vibration": _make_vibration_ramp(0.1, 0.01),  # rising (consistent)
            "temperature": _make_current_ramp(0.9, -0.01),  # falling (anomalous)
            "pressure": _make_flat_channel(0.5),
            "humidity": _make_flat_channel(0.5),
            "gas": _make_flat_channel(0.5),
        },
    )

    p = CorrelationProvider()
    p.record_window(window)

    # Current/vibration: consistent (both rising) → k=1.0
    assert p.evaluate("current") == 1.0
    assert p.evaluate("vibration") == 1.0

    # Temperature: anomalous, but k doesn't constrain it → k=1.0
    # (c and h will detect the anomaly)
    assert p.evaluate("temperature") == 1.0, "temperature not constrained by pair rule"


# ---------------------------------------------------------------------------
# 7. Window Size Adaptation
# ---------------------------------------------------------------------------


def test_window_size_derived_not_hardcoded():
    """Trend split is derived from window.size, adapts to different lengths."""
    # Create a smaller window (15 samples instead of 30)
    small_window = _build_window(
        0,
        {
            "current": tuple(0.2 + 0.01 * i for i in range(15)),  # rising
            "vibration": tuple(0.1 + 0.01 * i for i in range(15)),  # rising
            "temperature": (0.5,) * 15,
            "pressure": (0.5,) * 15,
            "humidity": (0.5,) * 15,
            "gas": (0.5,) * 15,
        },
    )

    p = CorrelationProvider()
    p.record_window(small_window)

    # Should still work (early=[0:7], late=[7:15])
    assert p.evaluate("current") == 1.0, "should work with 15-sample window"
    assert p.evaluate("vibration") == 1.0


# ---------------------------------------------------------------------------
# 8. Protocol Compliance
# ---------------------------------------------------------------------------


def test_protocol_returns_float_in_0_1():
    """evaluate(channel) returns float in [0, 1]."""
    p = CorrelationProvider()
    window = _make_correlated_rising_window()
    p.record_window(window)

    for ch in CHANNELS:
        result = p.evaluate(ch)
        assert isinstance(result, float), f"{ch} should return float"
        assert 0.0 <= result <= 1.0, f"{ch} k={result} should be in [0, 1]"


def test_evaluate_unknown_channel_raises():
    """evaluate() raises ValueError for unknown channel."""
    p = CorrelationProvider()
    with pytest.raises(ValueError, match="unknown channel"):
        p.evaluate("invalid_channel")


# ---------------------------------------------------------------------------
# 9. Error Handling
# ---------------------------------------------------------------------------


def test_record_window_missing_current_raises():
    """record_window() raises if 'current' feature is missing."""
    p = CorrelationProvider()
    window = _build_window(
        0,
        {
            "vibration": _make_flat_channel(0.5),
            "temperature": _make_flat_channel(0.5),
            "pressure": _make_flat_channel(0.5),
            "humidity": _make_flat_channel(0.5),
            "gas": _make_flat_channel(0.5),
            # 'current' intentionally omitted
        },
    )

    with pytest.raises(ValueError, match="current"):
        p.record_window(window)


def test_record_window_length_mismatch_raises():
    """record_window() raises if current and vibration have different lengths."""
    p = CorrelationProvider()
    window = _build_window(
        0,
        {
            "current": tuple(0.5 + 0.01 * i for i in range(30)),
            "vibration": tuple(0.5 + 0.01 * i for i in range(25)),  # mismatch
            "temperature": (0.5,) * 30,
            "pressure": (0.5,) * 30,
            "humidity": (0.5,) * 30,
            "gas": (0.5,) * 30,
        },
    )

    with pytest.raises(ValueError, match="same length"):
        p.record_window(window)


# ---------------------------------------------------------------------------
# 10. State Persistence Across Calls
# ---------------------------------------------------------------------------


def test_state_persists_across_windows():
    """Multiple record_window() calls update state independently."""
    p = CorrelationProvider()

    # First window: both rising
    w1 = _make_correlated_rising_window()
    p.record_window(w1)
    k1_current = p.evaluate("current")
    assert k1_current == 1.0

    # Second window: both falling
    w2 = _make_correlated_falling_window()
    p.record_window(w2)
    k2_current = p.evaluate("current")
    assert k2_current == 1.0  # still consistent

    # Third window: anticorrelated
    w3 = _make_anticorrelated_window()
    p.record_window(w3)
    k3_current = p.evaluate("current")
    assert k3_current == 0.0  # now inconsistent

    # Fourth window: back to correlated
    w4 = _make_correlated_rising_window()
    p.record_window(w4)
    k4_current = p.evaluate("current")
    assert k4_current == 1.0  # recovered


# ---------------------------------------------------------------------------
# 11. Non-Involved Channels Always 1.0
# ---------------------------------------------------------------------------


def test_noninvolved_channels_always_1_0():
    """Temperature, pressure, humidity, gas always receive k=1.0."""
    p = CorrelationProvider()

    # Test with anticorrelated window (strongest violation)
    window = _make_anticorrelated_window()
    p.record_window(window)

    # Current/vibration: violated (k=0.0)
    assert p.evaluate("current") == 0.0
    assert p.evaluate("vibration") == 0.0

    # Others: always 1.0 (not constrained)
    assert p.evaluate("temperature") == 1.0
    assert p.evaluate("pressure") == 1.0
    assert p.evaluate("humidity") == 1.0
    assert p.evaluate("gas") == 1.0
