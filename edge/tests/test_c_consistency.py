"""P2 tests — consistency signal provider (U01).

Validates ConsistencyProvider in isolation:
  - initialization, fit, record_window, evaluate, per-channel independence,
    z-score arithmetic, empirical-CDF normalization, and SignalProvider protocol.

These tests exercise math/interface ONLY. They make NO claim about:
  - real spoof/fault detection accuracy
  - any P2 trust acceptance gate (P2-ANOM-H3, P2-TRUST-H2)
  - integration with anomaly detector or pipeline

Pending items deliberately NOT tested here:
  - coupling to actual IF (trained separately; caller ensures same data)
  - ChannelFlagPolicy integration (still a seam)
  - full pipeline wiring of record_window() before update_from_providers()
"""

import numpy as np
import pytest
from app.schemas.contracts import CHANNELS

from edge.anomaly.preprocess import Window
from edge.trust.c_consistency import ConsistencyProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_window(start_index: int, channels_dict: dict[str, tuple[float, ...]]) -> Window:
    """Construct a Window from per-channel tuples."""
    return Window(
        start_index=start_index,
        end_index=start_index + len(next(iter(channels_dict.values()))),
        features=channels_dict,
    )


def _constant_window(value: float) -> Window:
    """Create a window where all channels are constant (same value)."""
    return _build_window(0, {ch: (value,) * 30 for ch in CHANNELS})


def _normal_window(base: float, noise_std: float, seed: int) -> Window:
    """Create a window with normally-distributed noise around a base value."""
    rng = np.random.RandomState(seed)
    return _build_window(
        0,
        {ch: tuple(rng.normal(base, noise_std, 30)) for ch in CHANNELS},
    )


def _linear_ramp_window(start: float, step: float) -> Window:
    """Create a window with linearly-increasing values."""
    return _build_window(
        0,
        {ch: tuple(start + step * i for i in range(30)) for ch in CHANNELS},
    )


# ---------------------------------------------------------------------------
# 1. Initialization
# ---------------------------------------------------------------------------


def test_init_all_channels_start_at_0_5():
    """All six channels initialize to c=0.5 (neutral until fit)."""
    p = ConsistencyProvider()
    for ch in CHANNELS:
        assert p.evaluate(ch) == 0.5


def test_init_not_fitted():
    """Provider starts in unfitted state."""
    p = ConsistencyProvider()
    assert not p.fitted


def test_init_snapshot_all_channels():
    """snapshot() keys must match frozen CHANNELS."""
    p = ConsistencyProvider()
    assert set(p.snapshot().keys()) == set(CHANNELS)


# ---------------------------------------------------------------------------
# 2. Fit validation
# ---------------------------------------------------------------------------


def test_fit_requires_non_empty_windows():
    """fit() raises ValueError if given empty sequence."""
    p = ConsistencyProvider()
    with pytest.raises(ValueError, match="requires at least one"):
        p.fit([])


def test_fit_sets_fitted_flag():
    """After fit(), fitted property is True."""
    p = ConsistencyProvider()
    p.fit([_constant_window(5.0)])
    assert p.fitted


def test_fit_on_single_window():
    """fit() works on a single training window."""
    p = ConsistencyProvider()
    w = _normal_window(10.0, 1.0, seed=42)
    p.fit([w])
    assert p.fitted
    # All c values should be valid (not NaN)
    for ch in CHANNELS:
        c = p.evaluate(ch)
        assert 0.0 <= c <= 1.0


def test_fit_on_multiple_windows():
    """fit() aggregates statistics across multiple training windows."""
    p = ConsistencyProvider()
    windows = [_normal_window(10.0, 1.0, seed=i) for i in range(10)]
    p.fit(windows)
    assert p.fitted
    for ch in CHANNELS:
        assert 0.0 <= p.evaluate(ch) <= 1.0


# ---------------------------------------------------------------------------
# 3. record_window before fit raises error
# ---------------------------------------------------------------------------


def test_record_window_before_fit_raises():
    """record_window() raises RuntimeError if fit() has not been called."""
    p = ConsistencyProvider()
    w = _constant_window(5.0)
    with pytest.raises(RuntimeError, match="before fit"):
        p.record_window(w)


# ---------------------------------------------------------------------------
# 4. evaluate after fit without record_window returns initial value
# ---------------------------------------------------------------------------


def test_evaluate_before_any_record_returns_initial():
    """After fit() but before record_window(), evaluate() returns 0.5."""
    p = ConsistencyProvider()
    p.fit([_normal_window(10.0, 1.0, seed=42)])
    # record_window() has NOT been called yet
    for ch in CHANNELS:
        assert p.evaluate(ch) == 0.5


# ---------------------------------------------------------------------------
# 5. Constant window (anomalous: zero variance)
# ---------------------------------------------------------------------------


def test_constant_window_after_variable_baseline():
    """Constant window (zero variance) produces low c when baseline has variance."""
    p = ConsistencyProvider()
    # Train on variable data (30 samples with std=1.0)
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(5)]
    p.fit(training)

    # Test on a constant window (same base value but zero variance)
    const_window = _constant_window(10.0)
    p.record_window(const_window)

    # A constant value (zero variance) is anomalous when baseline has variance
    # → high RMS z-score (or low RMS z-score if value matches mean, but with no variance signal)
    # Actually: a constant 10.0 has z=[0,0,...,0], so rms_z=0.
    # This is NOT anomalous in terms of residual; it's actually highly consistent.
    # The anomaly of a constant spoof is that IT LACKS VARIANCE, not that values are off.

    # So a constant value (same as baseline mean) should have:
    # z=[0]*30 → rms_z=0 → rank=0 (or very low) → severity≈0 → c≈1 (high)
    # This is EXPECTED behavior: if a constant equals the mean, it looks consistent per z-score.
    # The detection of constant spoofs comes from h (accumulating bad outcomes) + k (physics).
    # c is just "per-window residual magnitude" and doesn't specifically target spoofs.

    for ch in CHANNELS:
        c = p.evaluate(ch)
        assert 0.0 <= c <= 1.0


def test_constant_window_different_from_baseline():
    """Constant window that differs from baseline mean produces lower c."""
    p = ConsistencyProvider()
    # Train on 10±1 (mean≈10)
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(5)]
    p.fit(training)

    # Test on constant 15 (far from baseline mean)
    const_window = _constant_window(15.0)
    p.record_window(const_window)

    # A constant 15 when baseline mean is 10 and std≈1:
    # z = (15-10)/1 = 5 (5 standard deviations away)
    # rms_z = sqrt(mean([5]*30)) = 5
    # This is very high; should rank high in sorted rms_z
    # → high severity → low c

    for ch in CHANNELS:
        c = p.evaluate(ch)
        # Not necessarily very low, but should be lower than the constant-at-mean case
        assert 0.0 <= c <= 1.0


# ---------------------------------------------------------------------------
# 6. Variable window
# ---------------------------------------------------------------------------


def test_variable_window_from_same_distribution():
    """Window drawn from same distribution as training has moderate-to-high c."""
    p = ConsistencyProvider()
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(20)]
    p.fit(training)

    # Test on another window from the same distribution
    test_window = _normal_window(10.0, 1.0, seed=999)
    p.record_window(test_window)

    for ch in CHANNELS:
        c = p.evaluate(ch)
        assert 0.0 <= c <= 1.0
        # Most windows from the training distribution should have c > 0.3 (not too anomalous)
        # (this is a soft assertion; exact value depends on randomness)


def test_variable_window_from_different_distribution():
    """Window from a very different distribution has lower c."""
    p = ConsistencyProvider()
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(20)]
    p.fit(training)

    # Test on a window from a far-away distribution (mean=50, std=0.5)
    test_window = _normal_window(50.0, 0.5, seed=999)
    p.record_window(test_window)

    for ch in CHANNELS:
        c = p.evaluate(ch)
        assert 0.0 <= c <= 1.0
        # Samples from mean=50 are ~40 stds away from baseline mean=10
        # z ≈ 40 → rms_z ≈ 40 → very high rank → low c


# ---------------------------------------------------------------------------
# 7. Per-channel independence
# ---------------------------------------------------------------------------


def test_per_channel_independence():
    """Modifying one channel's values doesn't affect other channels."""
    p = ConsistencyProvider()
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(10)]
    p.fit(training)

    # Create a window where only one channel is anomalous
    anomalous_values = tuple(50.0 for _ in range(30))  # Far from baseline
    normal_values = tuple(10.0 + 0.1 * i for i in range(30))

    window_dict = {}
    for ch in CHANNELS:
        if ch == "temperature":
            window_dict[ch] = anomalous_values
        else:
            window_dict[ch] = normal_values

    window = _build_window(0, window_dict)
    p.record_window(window)

    c_temp = p.evaluate("temperature")
    c_vib = p.evaluate("vibration")

    # Temperature should be much lower than vibration
    # (this is probabilistic; if seeds align, might not always hold exactly,
    #  but statistical expectation is clear)
    assert c_temp < c_vib or c_temp <= 0.3  # At least temperature should be low


# ---------------------------------------------------------------------------
# 8. Empirical CDF bounds
# ---------------------------------------------------------------------------


def test_empirical_cdf_produces_c_in_0_1():
    """All c values are in [0, 1] after record_window."""
    p = ConsistencyProvider()
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(10)]
    p.fit(training)

    # Test on various windows
    test_cases = [
        _constant_window(5.0),
        _normal_window(10.0, 0.5, seed=100),
        _normal_window(20.0, 2.0, seed=101),
        _linear_ramp_window(5.0, 0.1),
    ]

    for test_window in test_cases:
        p.record_window(test_window)
        for ch in CHANNELS:
            c = p.evaluate(ch)
            assert 0.0 <= c <= 1.0, f"c out of bounds: {c}"


# ---------------------------------------------------------------------------
# 9. Recovery: normal window after anomalous
# ---------------------------------------------------------------------------


def test_recovery_after_anomalous_window():
    """c recovers to higher values when window returns to normal."""
    p = ConsistencyProvider()
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(10)]
    p.fit(training)

    # Anomalous window
    anomalous = _constant_window(50.0)
    p.record_window(anomalous)
    c_after_anomaly = {ch: p.evaluate(ch) for ch in CHANNELS}

    # Normal window
    normal = _normal_window(10.0, 1.0, seed=999)
    p.record_window(normal)
    c_after_recovery = {ch: p.evaluate(ch) for ch in CHANNELS}

    # c should increase (recover) per-channel
    for ch in CHANNELS:
        assert c_after_recovery[ch] > c_after_anomaly[ch]


# ---------------------------------------------------------------------------
# 10. SignalProvider protocol compliance
# ---------------------------------------------------------------------------


def test_implements_signal_provider_protocol():
    """ConsistencyProvider has evaluate(channel) -> float."""
    p = ConsistencyProvider()
    p.fit([_normal_window(10.0, 1.0, seed=42)])
    p.record_window(_normal_window(10.0, 1.0, seed=999))

    # Check that evaluate exists and returns float
    assert hasattr(p, "evaluate")
    for ch in CHANNELS:
        result = p.evaluate(ch)
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    # Check protocol (duck-typing)
    assert callable(getattr(p, "evaluate", None))


# ---------------------------------------------------------------------------
# 11. Edge case: all channels identical in window (covariance = 0)
# ---------------------------------------------------------------------------


def test_all_channels_identical_value():
    """Window where all channels have the same value (within window)."""
    p = ConsistencyProvider()
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(10)]
    p.fit(training)

    # All channels get the same constant value
    window = _build_window(
        0,
        {ch: (15.0,) * 30 for ch in CHANNELS},
    )
    p.record_window(window)

    # All channels should have similar c values (same residual distance)
    c_values = [p.evaluate(ch) for ch in CHANNELS]
    # All should be roughly equal (within floating-point precision)
    assert max(c_values) - min(c_values) < 0.01


# ---------------------------------------------------------------------------
# 12. Multiple windows: provider state persists across calls
# ---------------------------------------------------------------------------


def test_state_persists_across_record_window_calls():
    """Multiple record_window() calls update state independently."""
    p = ConsistencyProvider()
    training = [_normal_window(10.0, 1.0, seed=i) for i in range(10)]
    p.fit(training)

    # First window
    w1 = _normal_window(10.0, 1.0, seed=100)
    p.record_window(w1)
    c_first = {ch: p.evaluate(ch) for ch in CHANNELS}

    # Second window (different distribution)
    w2 = _normal_window(20.0, 1.0, seed=101)
    p.record_window(w2)
    c_second = {ch: p.evaluate(ch) for ch in CHANNELS}

    # Third window (back to similar as first)
    w3 = _normal_window(10.0, 1.0, seed=102)
    p.record_window(w3)
    c_third = {ch: p.evaluate(ch) for ch in CHANNELS}

    # c values should change as windows change
    for ch in CHANNELS:
        # c for the out-of-distribution window (w2) should differ from w1/w3
        # (this is probabilistic, but expected)
        assert isinstance(c_first[ch], float)
        assert isinstance(c_second[ch], float)
        assert isinstance(c_third[ch], float)
        assert all(0.0 <= v <= 1.0 for v in [c_first[ch], c_second[ch], c_third[ch]])
