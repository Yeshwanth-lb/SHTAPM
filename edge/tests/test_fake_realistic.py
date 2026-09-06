"""Tests for edge/drivers/fake.py's realistic_raw() -- deterministic,
reproducible, time-varying signal generation for hardware-free "realistic"
fake sensors. See that function's own docstring: this is NOT a physical
model, NOT a validation claim, NOT calibrated against any real sensor.
"""

from __future__ import annotations

import inspect

import pytest

from edge.drivers.base import Sensor
from edge.drivers.fake import realistic_raw


def _fixed_clock() -> str:
    return "2026-01-01T00:00:00.000Z"


def test_deterministic_under_the_same_seed():
    a = realistic_raw(baseline=10.0, noise_std=0.5, drift_std=0.1, seed=42)
    b = realistic_raw(baseline=10.0, noise_std=0.5, drift_std=0.1, seed=42)
    assert [a() for _ in range(20)] == [b() for _ in range(20)]


def test_different_seeds_produce_different_sequences():
    a = realistic_raw(baseline=10.0, noise_std=0.5, drift_std=0.1, seed=1)
    b = realistic_raw(baseline=10.0, noise_std=0.5, drift_std=0.1, seed=2)
    assert [a() for _ in range(10)] != [b() for _ in range(10)]


def test_values_vary_over_time_rather_than_remaining_constant():
    raw = realistic_raw(baseline=10.0, noise_std=0.5, drift_std=0.1, seed=7)
    values = [raw() for _ in range(20)]
    assert len(set(values)) > 1


def test_values_stay_bounded_around_baseline():
    """Physically plausible: with small noise/drift std, values stay within
    a generous, deterministic multiple of those magnitudes around baseline
    -- not an unbounded/arbitrary walk."""
    baseline, noise_std, drift_std = 100.0, 1.0, 0.2
    raw = realistic_raw(baseline=baseline, noise_std=noise_std, drift_std=drift_std, seed=3)
    values = [raw() for _ in range(500)]
    bound = 10 * max(noise_std, drift_std)
    assert all(abs(v - baseline) < bound for v in values)


def test_repeated_samples_show_temporal_continuity():
    """Consecutive reads are correlated through the persisted drift level,
    not independent draws -- consecutive differences stay much smaller than
    an arbitrary jump would be."""
    raw = realistic_raw(baseline=50.0, noise_std=0.05, drift_std=0.01, seed=11)
    values = [raw() for _ in range(200)]
    consecutive_diffs = [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
    assert max(consecutive_diffs) < 1.0


def test_zero_noise_and_drift_reproduces_a_flat_baseline():
    """Edge case sanity check: with both stds at zero, the signal is exactly
    the baseline forever -- no hidden randomness sneaks in."""
    raw = realistic_raw(baseline=42.0, noise_std=0.0, drift_std=0.0, seed=5)
    assert [raw() for _ in range(10)] == [42.0] * 10


def test_negative_noise_std_rejected():
    with pytest.raises(ValueError):
        realistic_raw(baseline=1.0, noise_std=-0.1, drift_std=0.1, seed=1)


def test_negative_drift_std_rejected():
    with pytest.raises(ValueError):
        realistic_raw(baseline=1.0, noise_std=0.1, drift_std=-0.1, seed=1)


def test_seed_has_no_invented_default():
    sig = inspect.signature(realistic_raw)
    assert sig.parameters["seed"].default is inspect.Parameter.empty


def test_wrapped_in_sensor_satisfies_the_reading_contract():
    raw = realistic_raw(baseline=20.0, noise_std=0.5, drift_std=0.1, seed=9)
    sensor = Sensor(unit="°C", raw_read=raw, value_range=(-50.0, 100.0), clock=_fixed_clock)
    for _ in range(5):
        r = sensor.read()
        assert r.healthy is True
        assert r.unit == "°C"
        assert r.ts == "2026-01-01T00:00:00.000Z"
        assert -50.0 <= r.value <= 100.0
        assert set(r.as_dict()) == {"value", "unit", "ts", "healthy"}


def test_value_range_clamps_realistic_output_via_sensor():
    """Boundedness is delegated to Sensor's existing value_range clamp
    (P1-ACQ-E2), not duplicated inside realistic_raw itself."""
    raw = realistic_raw(baseline=1000.0, noise_std=0.0, drift_std=0.0, seed=1)
    sensor = Sensor(unit="hPa", raw_read=raw, value_range=(0.0, 10.0), clock=_fixed_clock)
    assert sensor.read().value == 10.0
