"""Tests for edge/models/scaling.py (P3 · D029)."""

from __future__ import annotations

import pytest

from edge.models.scaling import ChannelScaler


def _fitted(channel: str = "current", values=(0.0, 1.0, 2.0, 3.0, 4.0)) -> ChannelScaler:
    scaler = ChannelScaler()
    scaler.fit({channel: values})
    return scaler


def test_round_trip_is_exact():
    """The property the whole design rests on: a reconstruction can only stand
    in for a sensor reading if the scale inverts exactly."""
    scaler = _fitted()
    for raw in (-5.0, 0.0, 0.7734, 2.0, 917.5):
        assert scaler.denormalize("current", scaler.normalize("current", raw)) == pytest.approx(raw)


def test_scale_is_fixed_not_per_window():
    """The same engineering value maps to the same scaled value every time,
    regardless of what data is seen later -- unlike Preprocessor's per-window
    min-max, which is why that one cannot be inverted for substitution."""
    scaler = _fitted()
    first = scaler.normalize("current", 2.0)
    for _ in range(5):
        assert scaler.normalize("current", 2.0) == first


def test_normalizes_to_z_score():
    scaler = _fitted(values=(1.0, 3.0))  # mean 2.0, population std 1.0
    assert scaler.normalize("current", 3.0) == pytest.approx(1.0)
    assert scaler.normalize("current", 2.0) == pytest.approx(0.0)
    assert scaler.normalize("current", 0.0) == pytest.approx(-2.0)


def test_outlier_does_not_relocate_typical_values_to_an_extreme():
    """Why z-score rather than min-max.

    A real capture contains genuine single-sample dropouts (the BMP280 read
    750.86 hPa twice against a ~917 hPa baseline, 2026-09-18). A min-max fit is
    defined ENTIRELY by the two extreme samples, so one dropout redefines the
    whole range and pushes every ordinary reading to one end of it. Mean/std
    dilutes a single outlier across all n samples.

    This is a claim about WHERE typical values land, not that z-score is
    unaffected: the outlier does inflate std substantially. It just does not
    relocate ordinary readings to the edge of the scale.
    """
    clean = [917.0 + i * 0.01 for i in range(200)]  # ~917.00 .. 918.99
    contaminated = [*clean, 750.86]
    typical = 917.5

    scaler = ChannelScaler()
    scaler.fit({"pressure": contaminated})

    # Min-max on the same contaminated data, for contrast.
    lo, hi = min(contaminated), max(contaminated)
    min_max_position = (typical - lo) / (hi - lo)
    assert min_max_position > 0.98  # shoved against the top of the range

    # Z-score keeps it near the centre of the distribution.
    assert abs(scaler.normalize("pressure", typical)) < 1.0


def test_zero_variance_channel_does_not_divide_by_zero():
    """A perfectly flat channel is real -- `current` sat at one value for 7 h
    on the idle bench -- and must not produce inf/NaN."""
    scaler = ChannelScaler()
    scaler.fit({"current": [0.0, 0.0, 0.0]})
    scaled = scaler.normalize("current", 0.0)
    assert scaled == pytest.approx(0.0)
    assert scaler.denormalize("current", scaled) == pytest.approx(0.0)


def test_unfitted_channel_raises_rather_than_assuming_unit_scale():
    scaler = _fitted("current")
    with pytest.raises(RuntimeError, match="before fit"):
        scaler.normalize("pressure", 917.0)
    with pytest.raises(RuntimeError, match="before fit"):
        scaler.denormalize("pressure", 0.0)


def test_unknown_channel_rejected():
    scaler = ChannelScaler()
    with pytest.raises(ValueError, match="unknown channel"):
        scaler.fit({"not_a_channel": [1.0]})
    with pytest.raises(ValueError, match="unknown channel"):
        _fitted().normalize("not_a_channel", 1.0)


def test_empty_inputs_rejected():
    scaler = ChannelScaler()
    with pytest.raises(ValueError, match="at least one channel"):
        scaler.fit({})
    with pytest.raises(ValueError, match="at least one value"):
        scaler.fit({"current": []})


def test_partial_fit_leaves_other_channels_unfitted():
    scaler = ChannelScaler()
    scaler.fit({"current": [1.0, 2.0]})
    assert scaler.fitted_channels == frozenset({"current"})
    scaler.fit({"vibration": [0.1, 0.2]})
    assert scaler.fitted_channels == frozenset({"current", "vibration"})
