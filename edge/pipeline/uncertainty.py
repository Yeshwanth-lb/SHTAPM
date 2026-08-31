"""Elapsed-substitution-time uncertainty proxy (P3 · D019, provisional).

Implements ONLY the uncertainty-estimation METHOD D019 already decided: a
deterministic proxy based on elapsed time since the current substitution
episode began, non-decreasing, bounded relative to substitution_max_seconds.

The elapsed-time -> uncertainty SCALING FORMULA remains explicitly open
(D019 "Does NOT resolve"). It is a REQUIRED constructor argument here --
never defaulted, never chosen by this module -- so ElapsedTimeUncertaintyProxy
cannot be instantiated without the caller supplying a scaling function, and
no shape (linear or otherwise) ships as a library default.

uncertainty_cap comparison is NOT performed here (see
edge/pipeline/self_heal.py): this module only produces a value in the
proxy's own output domain and knows nothing about any cap, keeping the
uncertainty signal independent of the cap/threshold logic that consumes it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ScalingFn(Protocol):
    """Maps elapsed_fraction in [0, 1] to an uncertainty value. Contract
    only -- the shape (linear or otherwise) is UNDECIDED (D019); real or
    fixture implementations are supplied by the caller."""

    def __call__(self, elapsed_fraction: float) -> float: ...


@runtime_checkable
class UncertaintyProxy(Protocol):
    def uncertainty(self, elapsed_seconds: float, substitution_max_seconds: float) -> float: ...


class ElapsedTimeUncertaintyProxy:
    """D019's deterministic elapsed-time proxy. ``scaling_fn`` is the ONLY
    thing that determines the actual output values -- this class supplies
    just the elapsed/max normalization D019 itself specifies ("bounded
    relative to substitution_max_seconds"), not the mapping past that point.
    """

    def __init__(self, scaling_fn: ScalingFn) -> None:
        self._scaling_fn = scaling_fn

    def uncertainty(self, elapsed_seconds: float, substitution_max_seconds: float) -> float:
        if substitution_max_seconds <= 0:
            raise ValueError(
                f"substitution_max_seconds must be > 0, got {substitution_max_seconds}"
            )
        if elapsed_seconds < 0:
            raise ValueError(f"elapsed_seconds must be >= 0, got {elapsed_seconds}")
        fraction = min(elapsed_seconds / substitution_max_seconds, 1.0)
        return self._scaling_fn(fraction)
