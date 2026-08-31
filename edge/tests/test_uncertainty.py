"""Tests for edge/pipeline/uncertainty.py (P3 · D019, provisional).

The scaling function used below is an explicit TEST FIXTURE, labelled as
such -- linear scaling is NOT the project's approved elapsed-time ->
uncertainty formula (D019 leaves that open); it is chosen here only because
it makes the boundary/monotonicity assertions easy to state precisely.
"""

import inspect

import pytest

from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy


def _LINEAR_SCALING_FIXTURE(elapsed_fraction: float) -> float:
    """TEST FIXTURE ONLY -- not the approved D019 scaling formula."""
    return elapsed_fraction


def test_zero_elapsed_is_minimum():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=_LINEAR_SCALING_FIXTURE)
    assert proxy.uncertainty(0.0, 60.0) == pytest.approx(0.0)


def test_non_decreasing_with_elapsed_time():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=_LINEAR_SCALING_FIXTURE)
    u1 = proxy.uncertainty(10.0, 60.0)
    u2 = proxy.uncertainty(30.0, 60.0)
    u3 = proxy.uncertainty(50.0, 60.0)
    assert u1 <= u2 <= u3


def test_bounded_relative_to_substitution_max_seconds():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=_LINEAR_SCALING_FIXTURE)
    at_max = proxy.uncertainty(60.0, 60.0)
    past_max = proxy.uncertainty(120.0, 60.0)
    assert at_max == pytest.approx(1.0)
    assert past_max == pytest.approx(at_max)  # clamped, not unbounded past max


def test_rejects_non_positive_substitution_max_seconds():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=_LINEAR_SCALING_FIXTURE)
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            proxy.uncertainty(1.0, bad)


def test_rejects_negative_elapsed():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=_LINEAR_SCALING_FIXTURE)
    with pytest.raises(ValueError):
        proxy.uncertainty(-1.0, 60.0)


def test_output_is_entirely_determined_by_injected_scaling_fn():
    """Swapping the scaling_fn changes the output for identical elapsed/max
    inputs -- proves the module invents no formula of its own."""
    proxy_linear = ElapsedTimeUncertaintyProxy(scaling_fn=_LINEAR_SCALING_FIXTURE)
    proxy_constant = ElapsedTimeUncertaintyProxy(scaling_fn=lambda fraction: 0.5)
    assert proxy_linear.uncertainty(10.0, 60.0) != proxy_constant.uncertainty(10.0, 60.0)


def test_scaling_fn_has_no_default_shape():
    """Structural proof that the scaling formula is a required argument,
    never a library default (D019: scaling formula NOT chosen)."""
    sig = inspect.signature(ElapsedTimeUncertaintyProxy.__init__)
    assert sig.parameters["scaling_fn"].default is inspect.Parameter.empty
