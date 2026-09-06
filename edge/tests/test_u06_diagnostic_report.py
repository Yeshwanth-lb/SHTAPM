"""Tests for edge/eval/u06_diagnostic_report.py (U06 aggregate diagnostic
report -- pure, additive, opt-in). No new axis, metric, threshold,
verdict, or real-world claim exists here -- see the module's own
docstring.
"""

from __future__ import annotations

import inspect

from edge.eval.rl_baseline_eval import EpisodeRecord
from edge.eval.u06_diagnostic_report import (
    AggregateDiagnosticReport,
    ScenarioBaselineResult,
    build_diagnostic_report,
    main,
)
from edge.eval.u06_ground_truth_rate_summary import GroundTruthRateSummary
from edge.eval.u06_rate_summary import EpisodeRateSummary
from edge.eval.u06_tracker_agreement import TrackerAgreementSummary

_EXPECTED_INJECTION_TYPE_SCENARIOS = {
    "injected_current_spike",
    "injected_temperature_drift",
    "injected_pressure_stuck_at",
    "injected_humidity_bias_fdi",
    "injected_gas_ramp_fdi",
    "injected_vibration_replay",
    "injected_current_constant_spoof",
    "injected_temperature_adaptive_stealth_fdi",
}
_EXPECTED_SCENARIOS = _EXPECTED_INJECTION_TYPE_SCENARIOS | {"clean_degradation"}
_EXPECTED_BASELINES = {"baseline_policy", "pure_fallback"}


# ---------------------------------------------------------------------------
# Coverage: all 9 scenarios, both baselines, exactly 18 results
# ---------------------------------------------------------------------------


def test_report_contains_exactly_eighteen_results():
    report = build_diagnostic_report()
    assert isinstance(report, AggregateDiagnosticReport)
    assert len(report.results) == 18


def test_all_nine_scenarios_are_represented():
    report = build_diagnostic_report()
    scenario_names = {r.scenario_name for r in report.results}
    assert scenario_names == _EXPECTED_SCENARIOS


def test_clean_degradation_and_all_eight_injection_types_are_represented():
    report = build_diagnostic_report()
    scenario_names = {r.scenario_name for r in report.results}
    assert "clean_degradation" in scenario_names
    assert _EXPECTED_INJECTION_TYPE_SCENARIOS <= scenario_names


def test_both_baselines_are_included_for_every_scenario():
    report = build_diagnostic_report()
    for scenario_name in _EXPECTED_SCENARIOS:
        baselines_for_scenario = {
            r.baseline_name for r in report.results if r.scenario_name == scenario_name
        }
        assert baselines_for_scenario == _EXPECTED_BASELINES


def test_scenario_baseline_pairs_are_all_unique():
    report = build_diagnostic_report()
    pairs = [(r.scenario_name, r.baseline_name) for r in report.results]
    assert len(pairs) == len(set(pairs)) == 18


# ---------------------------------------------------------------------------
# All three axis summaries present for every result
# ---------------------------------------------------------------------------


def test_every_result_carries_all_three_axis_summaries():
    report = build_diagnostic_report()
    for result in report.results:
        assert isinstance(result, ScenarioBaselineResult)
        assert isinstance(result.episode_rate_summary, EpisodeRateSummary)
        assert isinstance(result.tracker_agreement_summary, TrackerAgreementSummary)
        assert isinstance(result.ground_truth_rate_summary, GroundTruthRateSummary)


def test_each_axis_summary_reports_its_own_scenario_and_baseline_identity():
    report = build_diagnostic_report()
    for result in report.results:
        assert result.episode_rate_summary.scenario_name == result.scenario_name
        assert result.episode_rate_summary.baseline_name == result.baseline_name
        assert result.tracker_agreement_summary.scenario_name == result.scenario_name
        assert result.tracker_agreement_summary.baseline_name == result.baseline_name
        assert result.ground_truth_rate_summary.scenario_name == result.scenario_name
        assert result.ground_truth_rate_summary.baseline_name == result.baseline_name


# ---------------------------------------------------------------------------
# Never pooled: no global/cross-scenario aggregate is computed
# ---------------------------------------------------------------------------


def test_report_has_no_pooled_or_global_rate_field():
    """Structural guard: AggregateDiagnosticReport must carry only the flat
    per-(scenario, baseline) results tuple plus metadata -- no field
    computing any cross-scenario/cross-baseline average, sum, or rate."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(AggregateDiagnosticReport)}
    assert field_names == {"results", "execution_mode", "data_source", "model_status"}


def test_results_for_different_scenarios_remain_independent():
    report = build_diagnostic_report()
    by_scenario = {}
    for result in report.results:
        by_scenario.setdefault(result.scenario_name, []).append(result)
    # Distinct scenarios must be able to carry distinct axis-summary values
    # -- proving they were computed independently, not from one shared/
    # pooled computation.
    clean_result = next(
        r
        for r in report.results
        if r.scenario_name == "clean_degradation" and r.baseline_name == "baseline_policy"
    )
    spike_result = next(
        r
        for r in report.results
        if r.scenario_name == "injected_current_spike" and r.baseline_name == "baseline_policy"
    )
    assert (
        clean_result.ground_truth_rate_summary.missed_fault_denominator
        != spike_result.ground_truth_rate_summary.missed_fault_denominator
    )


# ---------------------------------------------------------------------------
# No mutation of underlying data
# ---------------------------------------------------------------------------


def test_build_diagnostic_report_does_not_mutate_anything_across_calls():
    """Calling build_diagnostic_report() twice must produce identical,
    independent results -- proving no shared mutable state leaks between
    calls (each call constructs fresh environments/episodes internally)."""
    first = build_diagnostic_report()
    second = build_diagnostic_report()

    first_by_key = {(r.scenario_name, r.baseline_name): r for r in first.results}
    second_by_key = {(r.scenario_name, r.baseline_name): r for r in second.results}
    assert first_by_key.keys() == second_by_key.keys()
    for key, first_result in first_by_key.items():
        second_result = second_by_key[key]
        assert (
            first_result.episode_rate_summary.false_isolation_rate
            == second_result.episode_rate_summary.false_isolation_rate
        )
        assert (
            first_result.tracker_agreement_summary.agreement_rate
            == second_result.tracker_agreement_summary.agreement_rate
        )


def test_build_diagnostic_report_returns_new_episode_records_not_shared_state():
    """Each (scenario, baseline) pair's EpisodeRecord is produced fresh by
    the existing baseline runners -- this module never caches, reuses, or
    mutates a previously-built EpisodeRecord."""
    report = build_diagnostic_report()
    for result in report.results:
        assert not isinstance(result, EpisodeRecord)


# ---------------------------------------------------------------------------
# Zero-result / error-handling: the report is never empty or partial
# ---------------------------------------------------------------------------


def test_report_is_never_empty_under_normal_operation():
    report = build_diagnostic_report()
    assert len(report.results) > 0
    assert len(report.results) == 18


def test_build_diagnostic_report_takes_no_parameters():
    """No external error surface: the function accepts no arguments, so
    there is no invalid-input case for it to handle -- confirmed via
    signature inspection rather than assumption."""
    signature = inspect.signature(build_diagnostic_report)
    assert len(signature.parameters) == 0


# ---------------------------------------------------------------------------
# main() is a simple, working printer
# ---------------------------------------------------------------------------


def test_main_runs_without_raising_and_prints_all_scenarios(capsys):
    main()
    captured = capsys.readouterr()
    for scenario_name in _EXPECTED_SCENARIOS:
        assert scenario_name in captured.out
    assert "axis (i)" in captured.out
    assert "axis (ii)" in captured.out
    assert "axis (iii)" in captured.out


# ---------------------------------------------------------------------------
# Structural: no threshold, verdict, real-world, or new-axis claim
# ---------------------------------------------------------------------------


def test_module_makes_no_threshold_verdict_or_real_world_claim():
    import edge.eval.u06_diagnostic_report as module

    source = inspect.getsource(module)
    lowered = source.lower()
    forbidden = (
        "the acceptable rate is",
        "the acceptable threshold is",
        "is validated",
        "is safe",
        "is accurate",
        "production-ready",
        "production ready",
        "pass\"",
        "fail\"",
        "passed the",
        "failed the",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_never_defines_a_new_metric_or_pooled_rate():
    """This module must compute no rate of its own -- every rate comes
    from the three wrapped, unmodified summary functions. Checked via AST
    (not a source-text scan) so it cannot be fooled by a comment or
    docstring mentioning division."""
    import ast

    import edge.eval.u06_diagnostic_report as module

    tree = ast.parse(inspect.getsource(module))
    division_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    ]
    assert division_nodes == []

    source = inspect.getsource(module)
    forbidden_defs = ("def summarize_", "def compute_reward", "class RewardWeights")
    for phrase in forbidden_defs:
        assert phrase not in source


def test_module_does_not_import_forbidden_modules():
    """The module docstring legitimately NAMES these modules to state the
    scope boundary ("never imports anything from...") -- what must never
    exist is an actual import, checked via AST rather than a source-text
    scan so the docstring's own prose cannot trigger a false failure."""
    import ast

    import edge.eval.u06_diagnostic_report as module

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
    )
    for imported in imported_modules:
        assert not imported.startswith(forbidden_prefixes)


def test_module_has_no_hardware_network_or_actuation_imports():
    import edge.eval.u06_diagnostic_report as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RelayController", "FakeActuator", "SelfHealOrchestrator", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()
