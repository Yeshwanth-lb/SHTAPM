"""Unit tests for TrendSignPhysicsRule (minimal provisional PhysicsRule).

Tests validate the LOGIC in isolation: fit/not-fit guards, agreement vs.
disagreement, tie-breaking, and the documented flat-trend blind spot. These
are UNIT TESTS, NOT P2 acceptance and NOT a real physics validation claim —
see module docstring in edge/anomaly/physics_rule.py.
"""

import pytest
from app.schemas.contracts import CHANNELS

from edge.anomaly.physics_rule import TrendSignPhysicsRule
from edge.anomaly.preprocess import Window


def _window(overrides: dict[str, tuple[float, ...]], length: int = 30) -> Window:
    base = {ch: tuple(0.5 for _ in range(length)) for ch in CHANNELS}
    base.update(overrides)
    return Window(start_index=0, end_index=length, features=base)


def _rising(start: float, step: float, length: int = 30) -> tuple[float, ...]:
    return tuple(start + step * i for i in range(length))


def _falling(start: float, step: float, length: int = 30) -> tuple[float, ...]:
    return tuple(start - step * i for i in range(length))


def _flat(value: float, length: int = 30) -> tuple[float, ...]:
    return (value,) * length


def _baseline_windows(n: int = 20) -> list[Window]:
    """Clean baseline: current/vibration both flat at 0.5 (their own norm)."""
    return [_window({"current": _flat(0.5), "vibration": _flat(0.5)}) for _ in range(n)]


# --- fit guards ---------------------------------------------------------------


def test_not_fitted_before_fit():
    rule = TrendSignPhysicsRule()
    assert rule.fitted is False


def test_check_before_fit_raises():
    rule = TrendSignPhysicsRule()
    window = _window({})
    with pytest.raises(RuntimeError, match="before fit"):
        rule.check(window)


def test_fit_requires_at_least_one_window():
    rule = TrendSignPhysicsRule()
    with pytest.raises(ValueError, match="at least one"):
        rule.fit([])


def test_fit_sets_fitted_true():
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    assert rule.fitted is True


# --- agreement -> no violation -------------------------------------------------


def test_both_rising_no_violation():
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window({"current": _rising(0.2, 0.02), "vibration": _rising(0.1, 0.02)})
    check = rule.check(window)
    assert check.violated is False
    assert check.suspect_channel is None


def test_both_falling_no_violation():
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window({"current": _falling(0.8, 0.02), "vibration": _falling(0.7, 0.02)})
    check = rule.check(window)
    assert check.violated is False


def test_one_flat_one_rising_no_violation_known_limitation():
    """Documented, pre-existing blind spot (same as k_correlation.py):
    zero-trend 'passes' against any sign. This is exactly why a pure
    constant-spoof can never be caught by this rule."""
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window({"current": _flat(0.5), "vibration": _rising(0.1, 0.05)})
    check = rule.check(window)
    assert check.violated is False


def test_both_flat_no_violation():
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window({"current": _flat(0.5), "vibration": _flat(0.3)})
    check = rule.check(window)
    assert check.violated is False


# --- disagreement -> violation, tie-broken by baseline deviation -------------


def test_opposing_trends_violated():
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window({"current": _rising(0.2, 0.05), "vibration": _falling(0.8, 0.05)})
    check = rule.check(window)
    assert check.violated is True
    assert check.suspect_channel in ("current", "vibration")
    assert check.reason != ""


def test_tie_break_picks_larger_baseline_deviation():
    """Baseline is flat at 0.5 for both. current ranges further from 0.5
    (mean ~0.5+0.05*14.5=1.225) than vibration ranges from 0.5 in the
    opposite direction (mean ~0.5-0.01*14.5=0.355) -- current should be
    named suspect."""
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window(
        {
            "current": _rising(0.2, 0.05),  # large excursion from baseline mean 0.5
            "vibration": _falling(0.55, 0.01),  # small excursion from baseline mean 0.5
        }
    )
    check = rule.check(window)
    assert check.violated is True
    assert check.suspect_channel == "current"


def test_tie_break_reverses_when_deviation_reverses():
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window(
        {
            "current": _rising(0.48, 0.01),  # small excursion
            "vibration": _falling(0.8, 0.05),  # large excursion
        }
    )
    check = rule.check(window)
    assert check.violated is True
    assert check.suspect_channel == "vibration"


# --- scope: only current/vibration are ever named ----------------------------


def test_never_names_a_non_pair_channel():
    """The rule only ever inspects current/vibration; it cannot name any
    other channel regardless of their values (no rule defined for them,
    same scope as D010's k)."""
    rule = TrendSignPhysicsRule()
    rule.fit(_baseline_windows())
    window = _window(
        {
            "current": _rising(0.2, 0.05),
            "vibration": _falling(0.8, 0.05),
            "temperature": _rising(0.9, 0.1),  # wildly anomalous, irrelevant to this rule
        }
    )
    check = rule.check(window)
    assert check.suspect_channel in ("current", "vibration", None)
