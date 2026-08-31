"""Tests for edge/pipeline/uncertainty.py (P3 · D019/D020).

This file's purpose is to prove ElapsedTimeUncertaintyProxy works
correctly with ANY injected scaling_fn -- it is not specifically about
validating one chosen formula. Most tests below use the real,
D020-approved ``linear_scaling`` (imported, not re-derived) as a
representative example; ``test_output_is_entirely_determined_by_injected_
scaling_fn`` deliberately pairs it with an independent, non-approved
constant function to prove the Proxy is not tied to any single formula.
"""

import inspect

import pytest

from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy, linear_scaling


def test_zero_elapsed_is_minimum():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    assert proxy.uncertainty(0.0, 60.0) == pytest.approx(0.0)


def test_non_decreasing_with_elapsed_time():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    u1 = proxy.uncertainty(10.0, 60.0)
    u2 = proxy.uncertainty(30.0, 60.0)
    u3 = proxy.uncertainty(50.0, 60.0)
    assert u1 <= u2 <= u3


def test_bounded_relative_to_substitution_max_seconds():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    at_max = proxy.uncertainty(60.0, 60.0)
    past_max = proxy.uncertainty(120.0, 60.0)
    assert at_max == pytest.approx(1.0)
    assert past_max == pytest.approx(at_max)  # clamped, not unbounded past max


def test_rejects_non_positive_substitution_max_seconds():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            proxy.uncertainty(1.0, bad)


def test_rejects_negative_elapsed():
    proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    with pytest.raises(ValueError):
        proxy.uncertainty(-1.0, 60.0)


def test_output_is_entirely_determined_by_injected_scaling_fn():
    """Swapping the scaling_fn changes the output for identical elapsed/max
    inputs -- proves the module invents no formula of its own."""
    proxy_linear = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    proxy_constant = ElapsedTimeUncertaintyProxy(scaling_fn=lambda fraction: 0.5)
    assert proxy_linear.uncertainty(10.0, 60.0) != proxy_constant.uncertainty(10.0, 60.0)


def test_scaling_fn_has_no_default_shape():
    """Structural proof that the scaling formula is a required argument,
    never a library default -- even after D020 approved a formula
    (linear_scaling), the API itself still refuses to supply one
    implicitly."""
    sig = inspect.signature(ElapsedTimeUncertaintyProxy.__init__)
    assert sig.parameters["scaling_fn"].default is inspect.Parameter.empty
