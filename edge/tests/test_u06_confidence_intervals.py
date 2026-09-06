"""Tests for edge/eval/u06_confidence_intervals.py (U06 within-episode
Wilson score confidence intervals -- pure, additive, opt-in). No
cross-seed, pooled, mean, standard-deviation, or distributional interval
exists here, no threshold/verdict/recommendation logic exists here, and no
existing axis module or rate value is modified -- see the module's own
docstring.
"""

from __future__ import annotations

import inspect
import math
from statistics import NormalDist

import pytest

from edge.eval.rl_baseline_eval import (
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF,
    run_baseline_policy_episode,
)
from edge.eval.u06_channel_agreement import summarize_channel_agreement
from edge.eval.u06_confidence_intervals import (
    APPROVED_CONFIDENCE_LEVEL,
    WilsonScoreInterval,
    axis_i_false_isolation_interval,
    axis_i_missed_fault_interval,
    axis_ii_tracker_agreement_interval,
    axis_iii_false_isolation_interval,
    axis_iii_missed_fault_interval,
    channel_agreement_interval,
    wilson_score_interval,
)
from edge.eval.u06_ground_truth_rate_summary import summarize_ground_truth_rates
from edge.eval.u06_rate_summary import summarize_episode_rates
from edge.eval.u06_tracker_agreement import summarize_tracker_agreement


def _manual_wilson(numerator: int, denominator: int, confidence_level: float = 0.95):
    """Independent, hand-derived re-implementation of the same closed-form
    Wilson formula, used only to cross-check the module's own output --
    not imported from the module under test."""
    n = float(denominator)
    phat = numerator / n
    z = NormalDist().inv_cdf(1.0 - (1.0 - confidence_level) / 2.0)
    z2 = z * z
    denom_term = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom_term
    margin = (z / denom_term) * ((phat * (1.0 - phat) / n + z2 / (4.0 * n * n)) ** 0.5)
    return max(0.0, center - margin), min(1.0, center + margin)


# ---------------------------------------------------------------------------
# Known reference-value / cross-check tests
# ---------------------------------------------------------------------------


def test_wilson_interval_matches_independent_manual_computation():
    """Known reference case (n=20, x=15, phat=0.75) -- cross-checked
    against an independently-written, hand-derived implementation of the
    identical closed-form Wilson equation, not the module's own code."""
    result = wilson_score_interval(15, 20)
    expected_lower, expected_upper = _manual_wilson(15, 20)
    assert math.isclose(result.lower_bound, expected_lower, rel_tol=1e-12)
    assert math.isclose(result.upper_bound, expected_upper, rel_tol=1e-12)
    assert result.rate == 0.75


def test_wilson_interval_matches_manual_computation_for_several_cases():
    for numerator, denominator in [(1, 3), (2, 9), (50, 100), (99, 100), (3, 5)]:
        result = wilson_score_interval(numerator, denominator)
        expected_lower, expected_upper = _manual_wilson(numerator, denominator)
        assert math.isclose(result.lower_bound, expected_lower, rel_tol=1e-12)
        assert math.isclose(result.upper_bound, expected_upper, rel_tol=1e-12)


# ---------------------------------------------------------------------------
# Boundary cases: 0/denominator and denominator/denominator
# ---------------------------------------------------------------------------


def test_zero_numerator_boundary_case():
    """rate=0.0 (0 successes) must produce a lower bound of exactly 0.0 and
    a non-degenerate positive upper bound -- not a (0.0, 0.0) point."""
    result = wilson_score_interval(0, 1)
    assert result.rate == 0.0
    assert result.lower_bound == 0.0
    assert result.upper_bound > 0.0
    assert result.upper_bound < 1.0


def test_numerator_equals_denominator_boundary_case():
    """rate=1.0 (all successes) must produce an upper bound of exactly 1.0
    and a non-degenerate lower bound below 1.0 -- not a (1.0, 1.0) point."""
    result = wilson_score_interval(1, 1)
    assert result.rate == 1.0
    assert result.upper_bound == 1.0
    assert result.lower_bound < 1.0
    assert result.lower_bound > 0.0


def test_ordinary_interior_proportion():
    result = wilson_score_interval(15, 20)
    assert 0.0 < result.lower_bound < result.rate < result.upper_bound < 1.0


# ---------------------------------------------------------------------------
# Zero-opportunity / None handling
# ---------------------------------------------------------------------------


def test_zero_denominator_returns_no_interval():
    assert wilson_score_interval(0, 0) is None


def test_axis_wrapper_returns_none_when_source_summary_rate_is_none():
    """The wrappers must return None exactly when the underlying summary's
    own rate is None (zero-denominator case) -- verified against a real,
    already-committed scenario known to produce zero opportunities for
    at least one axis."""
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    rates = summarize_episode_rates(record)
    ground_truth = summarize_ground_truth_rates(record)
    channel_agreement = summarize_channel_agreement(record)

    assert rates.missed_fault_rate is None
    assert axis_i_missed_fault_interval(rates) is None

    assert ground_truth.missed_fault_rate is None
    assert axis_iii_missed_fault_interval(ground_truth) is None

    assert channel_agreement.channel_match_rate is None
    assert channel_agreement_interval(channel_agreement) is None


# ---------------------------------------------------------------------------
# Defensive input validation
# ---------------------------------------------------------------------------


def test_negative_numerator_is_rejected():
    with pytest.raises(ValueError):
        wilson_score_interval(-1, 10)


def test_negative_denominator_is_rejected():
    with pytest.raises(ValueError):
        wilson_score_interval(0, -1)


def test_numerator_exceeding_denominator_is_rejected():
    with pytest.raises(ValueError):
        wilson_score_interval(11, 10)


def test_confidence_level_out_of_range_is_rejected():
    with pytest.raises(ValueError):
        wilson_score_interval(1, 2, confidence_level=1.0)
    with pytest.raises(ValueError):
        wilson_score_interval(1, 2, confidence_level=0.0)
    with pytest.raises(ValueError):
        wilson_score_interval(1, 2, confidence_level=-0.5)


def test_approved_confidence_level_constant_is_ninety_five_percent():
    assert APPROVED_CONFIDENCE_LEVEL == 0.95


def test_default_confidence_level_is_the_approved_one():
    result = wilson_score_interval(1, 2)
    assert result.confidence_level == APPROVED_CONFIDENCE_LEVEL


# ---------------------------------------------------------------------------
# Per-axis wrappers use ORIGINAL counts, never rounded rates
# ---------------------------------------------------------------------------


def test_axis_i_false_isolation_wrapper_uses_original_counts():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    rates = summarize_episode_rates(record)
    result = axis_i_false_isolation_interval(rates)
    assert result is not None
    assert result.numerator == rates.false_isolation_numerator
    assert result.denominator == rates.false_isolation_denominator
    assert result.rate == rates.false_isolation_numerator / rates.false_isolation_denominator


def test_axis_iii_false_isolation_wrapper_uses_original_counts():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    ground_truth = summarize_ground_truth_rates(record)
    result = axis_iii_false_isolation_interval(ground_truth)
    assert result is not None
    assert result.numerator == ground_truth.false_isolation_numerator
    assert result.denominator == ground_truth.false_isolation_denominator


def test_axis_ii_tracker_agreement_wrapper_reconstructs_numerator_from_raw_counts():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    agreement = summarize_tracker_agreement(record)
    result = axis_ii_tracker_agreement_interval(agreement)
    assert result is not None
    assert result.numerator == agreement.agreement_active_count + agreement.agreement_nominal_count
    assert result.denominator == agreement.total_observations
    assert math.isclose(result.rate, agreement.agreement_rate, rel_tol=1e-12)


def test_channel_agreement_wrapper_uses_original_counts():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    channel_agreement = summarize_channel_agreement(record)
    result = channel_agreement_interval(channel_agreement)
    assert result is not None
    assert result.numerator == channel_agreement.channel_match_count
    assert result.denominator == channel_agreement.channel_match_observation_count
    assert result.rate == channel_agreement.channel_match_rate


# ---------------------------------------------------------------------------
# Confirm no existing rate value changes
# ---------------------------------------------------------------------------


def test_computing_intervals_does_not_mutate_the_source_summaries():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    rates_before = summarize_episode_rates(record)
    axis_i_false_isolation_interval(rates_before)
    rates_after = summarize_episode_rates(record)
    assert rates_before == rates_after


def test_axis_summaries_are_unaffected_by_importing_this_module():
    """Regression guard: merely importing/using this module must not
    change any value the four existing summary functions report."""
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    rates = summarize_episode_rates(record)
    agreement = summarize_tracker_agreement(record)
    ground_truth = summarize_ground_truth_rates(record)
    channel_agreement = summarize_channel_agreement(record)

    axis_i_false_isolation_interval(rates)
    axis_ii_tracker_agreement_interval(agreement)
    axis_iii_false_isolation_interval(ground_truth)
    channel_agreement_interval(channel_agreement)

    assert summarize_episode_rates(record) == rates
    assert summarize_tracker_agreement(record) == agreement
    assert summarize_ground_truth_rates(record) == ground_truth
    assert summarize_channel_agreement(record) == channel_agreement


# ---------------------------------------------------------------------------
# Structural: no threshold, verdict, reward change, pooling, or cross-seed
# aggregation
# ---------------------------------------------------------------------------


def test_module_computes_no_cross_seed_or_pooled_statistic():
    """AST-based check: no builtin mean/stdev/variance call anywhere in
    this module's own code -- this module computes a single proportion's
    interval, never a cross-seed aggregate. (``min``/``max`` are
    deliberately NOT forbidden here -- the module legitimately uses them
    to clamp one interval's own bounds to [0.0, 1.0], which is not
    cross-seed aggregation.)"""
    import ast

    import edge.eval.u06_confidence_intervals as module

    tree = ast.parse(inspect.getsource(module))
    forbidden_call_names = {"mean", "stdev", "variance"}
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert call_names.isdisjoint(forbidden_call_names)


def test_module_makes_no_threshold_verdict_or_real_world_claim():
    import edge.eval.u06_confidence_intervals as module

    source = inspect.getsource(module)
    lowered = source.lower()
    forbidden = (
        "the acceptable rate is",
        "the acceptable threshold is",
        "is validated",
        "confirmed safe",
        "confirmed accurate",
        "proven safe",
        "proven accurate",
        "production-ready",
        "production ready",
        "pass\"",
        "fail\"",
        "passed the",
        "failed the",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_does_not_import_forbidden_modules():
    """The module docstring legitimately NAMES these modules to state the
    scope boundary -- what must never exist is an actual import, checked
    via AST rather than a source-text scan."""
    import ast

    import edge.eval.u06_confidence_intervals as module

    tree = ast.parse(inspect.getsource(module))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "edge.rl.reward",
        "edge.rl.fallback_gate",
        "edge.rl.policy",
        "edge.rl.environment",
        "edge.eval.rl_training",
        "edge.injection",
        "edge.eval.u06_rate_summary",
        "edge.eval.u06_tracker_agreement",
        "edge.eval.u06_ground_truth_rate_summary",
        "edge.eval.u06_channel_agreement",
        "scipy",
        "numpy",
    )
    for imported in imported_modules:
        assert not imported.startswith(forbidden_prefixes)


def test_module_has_no_new_external_dependency():
    """Only standard-library imports (plus __future__) may appear at
    module scope -- confirms the Wilson formula was implemented without
    scipy/numpy or any other third-party package."""
    import ast

    import edge.eval.u06_confidence_intervals as module

    tree = ast.parse(inspect.getsource(module))
    allowed = {"__future__", "dataclasses", "statistics"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] in allowed


def test_no_function_accepts_a_collection_of_seeds_or_summaries():
    """Structural guard against cross-seed aggregation: every public
    function's parameters are singular (a single summary object, or a
    single numerator/denominator pair) -- none accepts a list/tuple of
    summaries, seeds, or scenarios."""
    public_functions = [
        wilson_score_interval,
        axis_i_false_isolation_interval,
        axis_i_missed_fault_interval,
        axis_ii_tracker_agreement_interval,
        axis_iii_false_isolation_interval,
        axis_iii_missed_fault_interval,
        channel_agreement_interval,
    ]
    for func in public_functions:
        signature = inspect.signature(func)
        for name in signature.parameters:
            assert "seeds" not in name.lower()
            assert "summaries" not in name.lower()
            assert "scenarios" not in name.lower()


def test_wilson_score_interval_dataclass_has_no_pooled_field():
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(WilsonScoreInterval)}
    assert field_names == {
        "numerator",
        "denominator",
        "rate",
        "confidence_level",
        "lower_bound",
        "upper_bound",
        "execution_mode",
        "data_source",
        "model_status",
    }
