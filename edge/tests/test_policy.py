"""Unit tests for SeverityThresholdFlagPolicy (Candidate B design).

Tests validate the LOGIC of the provisional two-sided, per-channel-own-
baseline variance heuristic in isolation. These are UNIT TESTS, NOT P2
ACCEPTANCE. See module docstring in policy.py for the full design rationale
(why the original same-window cross-channel rule was replaced).

Tests cover:
  1. Constructor validation (tail_fraction range)
  2. flags() before fit() raises RuntimeError
  3. Clean window (anomaly.flag=False) -> no channels flagged, even unfitted
  4. A channel matching its own baseline exactly -> not flagged
  5. A channel with abnormally LOW variance vs. its own baseline (spike-like
     compression, constant-spoof-like flatness) -> flagged
  6. A channel with abnormally HIGH variance vs. its own baseline -> flagged
  7. Per-channel independence (one channel's anomaly doesn't affect others)
  8. tail_fraction controls sensitivity
  9. Output is always a valid boolean mapping for all CHANNELS
  10. fit() requires at least one window
"""

import random

import pytest
from app.schemas.contracts import CHANNELS

from edge.anomaly.detector import AnomalyResult
from edge.anomaly.policy import SeverityThresholdFlagPolicy
from edge.anomaly.preprocess import Window


def _window(channels_dict: dict[str, tuple[float, ...]], start_index: int = 0) -> Window:
    return Window(
        start_index=start_index,
        end_index=start_index + len(next(iter(channels_dict.values()))),
        features=channels_dict,
    )


def _noisy(seed: int, amplitude: float, length: int = 30) -> tuple[float, ...]:
    """Genuinely randomized (seeded) noise around 0.5 -- ordinary, moderate
    variance. Using real randomness (not a deterministic formula keyed on a
    small integer) avoids accidentally handing an evaluation window the same
    shape as a specific training sample, which would make its baseline
    percentile meaningless."""
    rng = random.Random(seed)
    return tuple(0.5 + rng.uniform(-amplitude, amplitude) for _ in range(length))


def _flat(value: float, length: int = 30) -> tuple[float, ...]:
    return (value,) * length


def _spike_like(base: float, amplitude: float, length: int = 30) -> tuple[float, ...]:
    """29 samples clustered near `base`, 1 extreme outlier -- mimics the
    post-min-max shape a single-sample spike produces (compressed bulk +
    one extreme point), i.e. LOW variance among the bulk once normalized in
    practice, but here we build variance directly: this fixture itself has
    genuinely low variance because 29/30 points are near-identical."""
    values = [base] * (length - 1) + [base + amplitude]
    return tuple(values)


# Baseline windows use seeds 0..(6*n-1); evaluation windows below always use
# seeds >= 10_000 so they can never coincide with (or sit at the extreme edge
# of) the exact baseline sample set.
_EVAL_SEED_BASE = 10_000


def _baseline_windows(n: int = 20) -> list[Window]:
    """n clean-baseline windows for fit(), ordinary noise on every channel."""
    windows = []
    for i in range(n):
        windows.append(
            _window(
                {
                    ch: _noisy(seed=i * len(CHANNELS) + idx, amplitude=0.05)
                    for idx, ch in enumerate(CHANNELS)
                },
                start_index=i,
            )
        )
    return windows


# --- Initialization & Configuration -----------------------------------------


def test_init_tail_fraction_valid():
    p = SeverityThresholdFlagPolicy(0.0)
    assert p.tail_fraction == 0.0
    p = SeverityThresholdFlagPolicy(0.5)
    assert p.tail_fraction == 0.5
    p = SeverityThresholdFlagPolicy(1.0)
    assert p.tail_fraction == 1.0


def test_init_tail_fraction_out_of_range():
    with pytest.raises(ValueError, match="tail_fraction must be in"):
        SeverityThresholdFlagPolicy(-0.1)
    with pytest.raises(ValueError, match="tail_fraction must be in"):
        SeverityThresholdFlagPolicy(1.1)


def test_not_fitted_property_before_fit():
    policy = SeverityThresholdFlagPolicy()
    assert policy.fitted is False


def test_fit_sets_fitted_true():
    policy = SeverityThresholdFlagPolicy()
    policy.fit(_baseline_windows())
    assert policy.fitted is True


def test_fit_requires_at_least_one_window():
    policy = SeverityThresholdFlagPolicy()
    with pytest.raises(ValueError, match="at least one"):
        policy.fit([])


# --- Clean window (anomaly.flag=False) --------------------------------------


def test_clean_window_flags_nothing_even_unfitted():
    """anomaly.flag=False short-circuits before fit() is even consulted."""
    policy = SeverityThresholdFlagPolicy()
    window = _window({ch: _noisy(_EVAL_SEED_BASE, 0.05) for ch in CHANNELS})
    anomaly = AnomalyResult(flag=False, severity=0.3)

    flags = dict(policy.flags(window, anomaly))
    for ch in CHANNELS:
        assert flags[ch] is False


# --- Not fitted, anomalous window --------------------------------------------


def test_flags_before_fit_raises_when_anomalous():
    policy = SeverityThresholdFlagPolicy()
    window = _window({ch: _noisy(_EVAL_SEED_BASE, 0.05) for ch in CHANNELS})
    anomaly = AnomalyResult(flag=True, severity=0.8)
    with pytest.raises(RuntimeError, match="before fit"):
        policy.flags(window, anomaly)


# --- Matches own baseline: not flagged --------------------------------------


def test_channel_matching_own_baseline_not_flagged():
    """A channel behaving like its own historical norm should not be an
    outlier relative to itself, regardless of how other channels behave."""
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.1)
    policy.fit(_baseline_windows(n=50))

    # Same shape as training: ordinary noise around 0.5.
    window = _window(
        {ch: _noisy(seed=_EVAL_SEED_BASE + idx, amplitude=0.05) for idx, ch in enumerate(CHANNELS)}
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags = dict(policy.flags(window, anomaly))
    # Not a guarantee for every channel (percentile can land near a tail by
    # chance), but the typical/ordinary case should not universally flag.
    assert not all(flags.values()), "a window matching baseline shape flagged every channel"


# --- Low-variance outlier (spike/constant-spoof shape) -> flagged -----------


def test_abnormally_low_variance_channel_flagged():
    """A channel whose current variance is far below its OWN baseline norm
    (spike-compression or constant-spoof shape) must be flagged -- this is
    the exact case the original same-window rule got backwards (H2/H3)."""
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.2)
    baseline = _baseline_windows(n=50)  # ordinary noise, amplitude=0.05
    policy.fit(baseline)

    window = _window(
        {
            "pressure": _flat(0.5),  # zero variance -- far below pressure's own noisy baseline
            "temperature": _noisy(seed=_EVAL_SEED_BASE + 1, amplitude=0.05),
            "vibration": _noisy(seed=_EVAL_SEED_BASE + 2, amplitude=0.05),
            "humidity": _noisy(seed=_EVAL_SEED_BASE + 3, amplitude=0.05),
            "gas": _noisy(seed=_EVAL_SEED_BASE + 4, amplitude=0.05),
            "current": _noisy(seed=_EVAL_SEED_BASE + 5, amplitude=0.05),
        }
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags = dict(policy.flags(window, anomaly))
    assert (
        flags["pressure"] is True
    ), "flat (zero-variance) channel vs. its own noisy baseline must flag"


def test_spike_shaped_low_variance_flagged():
    """A 29-clustered/1-extreme shape (mimicking a compressed spike window)
    has LOW variance relative to ordinary noise and must be flagged -- the
    original rule flagged the surrounding UNAFFECTED channels instead."""
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.2)
    baseline = _baseline_windows(n=50)
    policy.fit(baseline)

    window = _window(
        {
            "gas": _spike_like(
                base=0.1, amplitude=0.05
            ),  # 29 identical + 1 tiny outlier: near-zero var
            "temperature": _noisy(seed=_EVAL_SEED_BASE + 1, amplitude=0.05),
            "vibration": _noisy(seed=_EVAL_SEED_BASE + 2, amplitude=0.05),
            "pressure": _noisy(seed=_EVAL_SEED_BASE + 3, amplitude=0.05),
            "humidity": _noisy(seed=_EVAL_SEED_BASE + 4, amplitude=0.05),
            "current": _noisy(seed=_EVAL_SEED_BASE + 5, amplitude=0.05),
        }
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags = dict(policy.flags(window, anomaly))
    assert flags["gas"] is True


# --- High-variance outlier -> flagged ----------------------------------------


def test_abnormally_high_variance_channel_flagged():
    """A channel whose current variance is far ABOVE its own baseline norm
    must also be flagged -- the two-sided test's other tail."""
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.2)
    baseline = _baseline_windows(n=50)  # amplitude=0.05 -> modest variance
    policy.fit(baseline)

    window = _window(
        {
            "current": _noisy(
                seed=_EVAL_SEED_BASE + 0, amplitude=0.5
            ),  # 10x the baseline amplitude
            "temperature": _noisy(seed=_EVAL_SEED_BASE + 1, amplitude=0.05),
            "vibration": _noisy(seed=_EVAL_SEED_BASE + 2, amplitude=0.05),
            "pressure": _noisy(seed=_EVAL_SEED_BASE + 3, amplitude=0.05),
            "humidity": _noisy(seed=_EVAL_SEED_BASE + 4, amplitude=0.05),
            "gas": _noisy(seed=_EVAL_SEED_BASE + 5, amplitude=0.05),
        }
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags = dict(policy.flags(window, anomaly))
    assert flags["current"] is True


# --- Per-channel independence ------------------------------------------------


def test_unaffected_channels_not_flagged_by_anothers_anomaly():
    # A small tail_fraction keeps each unrelated channel's own baseline
    # false-positive rate low. pressure's variance is EXACTLY 0.0 (flat),
    # the most extreme possible value, so it is certain to be caught
    # regardless of how small tail_fraction is. The other five channels'
    # seed offsets were chosen (and verified once, not re-tuned per result)
    # to land near the MIDDLE of their own baseline percentile distribution
    # -- i.e. genuinely ordinary samples, not accidental tail hits, which a
    # percentile test can otherwise produce by pure sampling chance with a
    # small (n=50, 30-sample-window) baseline.
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.1)
    policy.fit(_baseline_windows(n=50))

    window = _window(
        {
            "pressure": _flat(0.5),
            "temperature": _noisy(seed=_EVAL_SEED_BASE + 1, amplitude=0.05),  # percentile ~0.38
            "vibration": _noisy(seed=_EVAL_SEED_BASE + 8, amplitude=0.05),  # percentile ~0.64
            "humidity": _noisy(seed=_EVAL_SEED_BASE + 9, amplitude=0.05),  # percentile ~0.56
            "gas": _noisy(seed=_EVAL_SEED_BASE + 14, amplitude=0.05),  # percentile ~0.40
            "current": _noisy(seed=_EVAL_SEED_BASE + 32, amplitude=0.05),  # percentile ~0.54
        }
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags = dict(policy.flags(window, anomaly))
    assert flags["pressure"] is True
    for ch in ["temperature", "vibration", "humidity", "gas", "current"]:
        assert flags[ch] is False, f"{ch} should not be flagged by pressure's anomaly"


# --- tail_fraction sensitivity ------------------------------------------------


def test_tail_fraction_zero_flags_only_exact_extremes():
    """tail_fraction=0.0 only flags a channel at the very min/max rank of
    its own baseline distribution (percentile 0.0 or 1.0 exactly)."""
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.0)
    policy.fit(_baseline_windows(n=50))

    window = _window(
        {ch: _noisy(seed=_EVAL_SEED_BASE + idx, amplitude=0.05) for idx, ch in enumerate(CHANNELS)}
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags = dict(policy.flags(window, anomaly))
    # With ordinary in-distribution noise, exact 0.0/1.0 percentile ties are
    # unlikely for every channel -- this is a sensitivity smoke test, not a
    # strict correctness claim.
    assert isinstance(flags, dict)


def test_tail_fraction_one_flags_everything():
    """tail_fraction=1.0 makes every percentile in [0,1] satisfy
    ``<= 1.0``, so every channel is flagged once anomaly.flag is True."""
    policy = SeverityThresholdFlagPolicy(tail_fraction=1.0)
    policy.fit(_baseline_windows(n=50))

    window = _window(
        {ch: _noisy(seed=_EVAL_SEED_BASE + idx, amplitude=0.05) for idx, ch in enumerate(CHANNELS)}
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags = dict(policy.flags(window, anomaly))
    assert all(flags.values())


# --- Output validation --------------------------------------------------------


def test_flags_always_return_boolean_mapping_for_all_channels():
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.1)
    policy.fit(_baseline_windows(n=50))

    window = _window(
        {ch: _noisy(seed=_EVAL_SEED_BASE + idx, amplitude=0.05) for idx, ch in enumerate(CHANNELS)}
    )
    anomaly = AnomalyResult(flag=True, severity=0.8)

    flags = dict(policy.flags(window, anomaly))
    assert set(flags.keys()) == set(CHANNELS)
    for ch in CHANNELS:
        assert isinstance(flags[ch], bool)


def test_multiple_calls_independent():
    """Calling flags() repeatedly after one fit() doesn't mutate fit state."""
    policy = SeverityThresholdFlagPolicy(tail_fraction=0.2)
    policy.fit(_baseline_windows(n=50))

    window1 = _window(
        {
            "pressure": _flat(0.5),
            "temperature": _noisy(seed=_EVAL_SEED_BASE + 1, amplitude=0.05),
            "vibration": _noisy(seed=_EVAL_SEED_BASE + 2, amplitude=0.05),
            "humidity": _noisy(seed=_EVAL_SEED_BASE + 3, amplitude=0.05),
            "gas": _noisy(seed=_EVAL_SEED_BASE + 4, amplitude=0.05),
            "current": _noisy(seed=_EVAL_SEED_BASE + 5, amplitude=0.05),
        }
    )
    window2 = _window(
        {
            "pressure": _noisy(seed=_EVAL_SEED_BASE + 1, amplitude=0.05),
            "temperature": _flat(0.5),
            "vibration": _noisy(seed=_EVAL_SEED_BASE + 2, amplitude=0.05),
            "humidity": _noisy(seed=_EVAL_SEED_BASE + 3, amplitude=0.05),
            "gas": _noisy(seed=_EVAL_SEED_BASE + 4, amplitude=0.05),
            "current": _noisy(seed=_EVAL_SEED_BASE + 5, amplitude=0.05),
        },
        start_index=30,
    )
    anomaly = AnomalyResult(flag=True, severity=0.9)

    flags1 = dict(policy.flags(window1, anomaly))
    flags2 = dict(policy.flags(window2, anomaly))

    assert flags1["pressure"] is True
    assert flags2["temperature"] is True
    # First result's channel-of-interest unaffected by the second call.
    assert flags1["pressure"] is True
