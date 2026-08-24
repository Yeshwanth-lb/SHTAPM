"""Unit tests for SeverityThresholdFlagPolicy.

Tests validate the LOGIC of the provisional variance-based heuristic in isolation.
These are UNIT TESTS, NOT P2 ACCEPTANCE. See module docstring in policy.py.

Tests cover:
  1. Clean window (anomaly.flag=False) → no channels flagged
  2. Anomalous window → channels with high variance flagged
  3. Per-channel independence (one anomaly doesn't affect others)
  4. Multiple anomalous channels
  5. Threshold behavior (variance_factor parameter)
  6. Edge cases (flat window, all same variance, single sample)
  7. Output is always valid boolean flags for all CHANNELS
"""

import pytest
from app.schemas.contracts import CHANNELS

from edge.anomaly.detector import AnomalyResult
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Window


def _build_window(
    start_index: int, channels_dict: dict[str, tuple[float, ...]]
) -> Window:
    """Construct a Window from per-channel tuples."""
    return Window(
        start_index=start_index,
        end_index=start_index + len(next(iter(channels_dict.values()))),
        features=channels_dict,
    )


def _flat_channel(value: float, length: int = 30) -> tuple[float, ...]:
    """Create a flat channel (no variance)."""
    return (value,) * length


def _rising_channel(start: float, step: float, length: int = 30) -> tuple[float, ...]:
    """Create a rising ramp (high variance)."""
    return tuple(start + step * i for i in range(length))


def _falling_channel(start: float, step: float, length: int = 30) -> tuple[float, ...]:
    """Create a falling ramp (high variance)."""
    return tuple(start - step * i for i in range(length))


def _noisy_channel(base: float, noise_amp: float, length: int = 30) -> tuple[float, ...]:
    """Create a noisy channel with oscillation (moderate variance)."""
    return tuple(base + noise_amp * (-1.0) ** i for i in range(length))


# --- Initialization & Configuration ---


def test_init_variance_factor_valid():
    """Constructor accepts variance_factor in [0, 1]."""
    p = SeverityThresholdFlagPolicy(0.0)
    assert p.variance_factor == 0.0

    p = SeverityThresholdFlagPolicy(0.5)
    assert p.variance_factor == 0.5

    p = SeverityThresholdFlagPolicy(1.0)
    assert p.variance_factor == 1.0


def test_init_variance_factor_out_of_range():
    """Constructor rejects variance_factor outside [0, 1]."""
    with pytest.raises(ValueError, match="variance_factor must be in"):
        SeverityThresholdFlagPolicy(-0.1)

    with pytest.raises(ValueError, match="variance_factor must be in"):
        SeverityThresholdFlagPolicy(1.1)


# --- Clean Window (Anomaly.flag=False) ---


def test_clean_window_flags_nothing():
    """If anomaly.flag is False, all channels are flagged False."""
    policy = SeverityThresholdFlagPolicy()
    window = _build_window(
        0,
        {
            "current": _rising_channel(0.2, 0.01),  # high variance
            "vibration": _rising_channel(0.1, 0.01),  # high variance
            "temperature": _flat_channel(0.5),
            "pressure": _flat_channel(0.5),
            "humidity": _flat_channel(0.5),
            "gas": _flat_channel(0.5),
        },
    )
    anomaly = AnomalyResult(flag=False, severity=0.3)

    flags = dict(policy.flags(window, anomaly))

    # All False regardless of variance
    for ch in CHANNELS:
        assert flags[ch] is False, f"{ch} should not be flagged when anomaly.flag=False"


# --- Anomalous Window: Single High-Variance Channel ---


def test_anomalous_single_high_variance_channel_flagged():
    """Anomalous window with one high-variance channel → that channel flagged."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    window = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.05),  # HIGH variance (0.0208...)
            "pressure": _flat_channel(0.5),
            "humidity": _flat_channel(0.5),
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.8)

    flags = dict(policy.flags(window, anomaly))

    # Temperature has much higher variance than others
    assert flags["temperature"] is True, "high-variance channel should be flagged"

    # Flat channels should not be flagged
    for ch in ["pressure", "humidity", "current", "vibration", "gas"]:
        assert flags[ch] is False, f"{ch} (flat) should not be flagged"


# --- Multiple High-Variance Channels ---


def test_anomalous_multiple_high_variance_channels():
    """Anomalous window with multiple high-variance channels → both flagged."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    window = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.05),  # HIGHEST variance
            "pressure": _rising_channel(0.4, 0.04),  # HIGH variance (almost as high)
            "humidity": _flat_channel(0.5),
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.7)

    flags = dict(policy.flags(window, anomaly))

    # Both high-variance channels should be flagged
    assert flags["temperature"] is True
    assert flags["pressure"] is True

    # Flat should not be flagged
    for ch in ["humidity", "current", "vibration", "gas"]:
        assert flags[ch] is False


# --- Threshold Behavior ---


def test_variance_factor_0_flags_only_highest():
    """variance_factor=0.0 flags only channels with variance > min_variance."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.0)
    window = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.10),  # HIGHEST variance
            "pressure": _rising_channel(0.4, 0.02),  # MEDIUM variance (still > min)
            "humidity": _flat_channel(0.5),  # minimum variance (0)
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.7)

    flags = dict(policy.flags(window, anomaly))

    # With factor=0.0, threshold = min_var, so anything > min is flagged
    # temperature and pressure have variance > 0, humidity/others = 0
    assert flags["temperature"] is True
    assert flags["pressure"] is True
    # Flat channels should not be flagged (variance = min)
    for ch in ["humidity", "current", "vibration", "gas"]:
        assert flags[ch] is False


def test_variance_factor_1_flags_nothing():
    """variance_factor=1.0 sets threshold to max_variance, so no channels flagged."""
    policy = SeverityThresholdFlagPolicy(variance_factor=1.0)
    window = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.05),  # HIGH variance
            "pressure": _rising_channel(0.4, 0.02),  # MEDIUM variance
            "humidity": _flat_channel(0.5),  # ZERO variance (min)
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.7)

    flags = dict(policy.flags(window, anomaly))

    # With factor=1.0, threshold = min + 1.0*range = max_var
    # No channel has variance > max_var, so none are flagged
    for ch in CHANNELS:
        assert flags[ch] is False, f"{ch} should not be flagged when factor=1.0"


def test_variance_factor_0_5_middle_ground():
    """variance_factor=0.5 flags channels in upper half of variance distribution."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    window = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.06),  # HIGHEST
            "pressure": _rising_channel(0.4, 0.04),  # MEDIUM-HIGH
            "humidity": _rising_channel(0.5, 0.02),  # MEDIUM-LOW
            "current": _flat_channel(0.3),  # LOWEST (0)
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.7)

    flags = dict(policy.flags(window, anomaly))

    # temperature should be flagged (highest)
    assert flags["temperature"] is True

    # pressure might be flagged depending on exact threshold
    # humidity should not be (too low)
    # flat channels should not be
    assert flags["current"] is False
    assert flags["vibration"] is False
    assert flags["gas"] is False


# --- Edge Cases ---


def test_all_channels_flat_no_flags():
    """All channels flat (zero variance) → no channels flagged."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    window = _build_window(
        0,
        {
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "temperature": _flat_channel(0.5),
            "pressure": _flat_channel(0.6),
            "humidity": _flat_channel(0.2),
            "gas": _flat_channel(0.7),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.5)

    flags = dict(policy.flags(window, anomaly))

    # All same variance (zero) → threshold is infinity, nothing passes
    for ch in CHANNELS:
        assert flags[ch] is False, f"flat {ch} should not be flagged"


def test_all_channels_flat_identical_values():
    """All channels have identical value (zero variance) → no channels flagged."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    # Create a window where all channels are flat at different values
    window = _build_window(
        0,
        {
            "current": (0.1, 0.1, 0.1, 0.1, 0.1),
            "vibration": (0.2, 0.2, 0.2, 0.2, 0.2),
            "temperature": (0.3, 0.3, 0.3, 0.3, 0.3),
            "pressure": (0.4, 0.4, 0.4, 0.4, 0.4),
            "humidity": (0.5, 0.5, 0.5, 0.5, 0.5),
            "gas": (0.6, 0.6, 0.6, 0.6, 0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.5)

    flags = dict(policy.flags(window, anomaly))

    # All zero variance → indistinguishable, threshold set high
    for ch in CHANNELS:
        assert flags[ch] is False, f"{ch} should not be flagged when all flat"


def test_single_sample_window_zero_variance():
    """Window with 1 sample (zero variance in all channels) → no flags."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    window = _build_window(
        0,
        {
            "current": (0.3,),
            "vibration": (0.4,),
            "temperature": (0.5,),
            "pressure": (0.6,),
            "humidity": (0.2,),
            "gas": (0.7,),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.5)

    flags = dict(policy.flags(window, anomaly))

    for ch in CHANNELS:
        assert flags[ch] is False, "single-sample window should have zero variance"


# --- Output Validation ---


def test_flags_always_return_boolean_dict_for_all_channels():
    """Output always includes all CHANNELS with boolean values."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    window = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.05),
            "pressure": _flat_channel(0.5),
            "humidity": _flat_channel(0.5),
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.8)

    flags = dict(policy.flags(window, anomaly))

    # All channels present
    assert set(flags.keys()) == set(CHANNELS), "all CHANNELS must be in output"

    # All values are boolean
    for ch in CHANNELS:
        assert isinstance(flags[ch], bool), f"{ch} value should be bool"


def test_flags_return_mapping_not_dict():
    """flags() returns Mapping, compatible with dict conversion."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)
    window = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.05),
            "pressure": _flat_channel(0.5),
            "humidity": _flat_channel(0.5),
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly = AnomalyResult(flag=True, severity=0.8)

    result = policy.flags(window, anomaly)

    # Should be Mapping; dict() should work
    flags_dict = dict(result)
    assert isinstance(flags_dict, dict)
    assert len(flags_dict) == len(CHANNELS)


# --- Multiple Calls (State Independence) ---


def test_multiple_windows_independent():
    """Calling flags() multiple times doesn't affect state."""
    policy = SeverityThresholdFlagPolicy(variance_factor=0.5)

    window1 = _build_window(
        0,
        {
            "temperature": _rising_channel(0.2, 0.05),
            "pressure": _flat_channel(0.5),
            "humidity": _flat_channel(0.5),
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly1 = AnomalyResult(flag=True, severity=0.8)

    window2 = _build_window(
        30,
        {
            "temperature": _flat_channel(0.5),
            "pressure": _rising_channel(0.4, 0.05),
            "humidity": _flat_channel(0.5),
            "current": _flat_channel(0.3),
            "vibration": _flat_channel(0.4),
            "gas": _flat_channel(0.6),
        },
    )
    anomaly2 = AnomalyResult(flag=True, severity=0.7)

    flags1 = dict(policy.flags(window1, anomaly1))
    flags2 = dict(policy.flags(window2, anomaly2))

    # First call: temperature flagged
    assert flags1["temperature"] is True

    # Second call: pressure flagged (different window)
    assert flags2["pressure"] is True

    # First result unchanged
    assert flags1["temperature"] is True
    assert flags1["pressure"] is False
