"""Tests for edge/eval/u06_dqn_augmented_diagnostic_report.py (U06
DQN-augmented aggregate diagnostic report). No real-world accuracy,
safety, effectiveness, validation, or production-readiness claim exists
here, no reward-weight decision is made here, no existing report module
is modified, and no checkpoint file is created -- see the module's own
docstring.

Unlike edge/tests/test_u06_dqn_evaluation_report.py, this test file is
NOT guarded by pytest.importorskip("torch") -- the whole point of this
module is to behave correctly whether or not torch is available, so both
code paths must be exercised regardless of what happens to be installed
in the current environment. The torch-unavailable path is exercised via
monkeypatching this module's own TORCH_AVAILABLE flag, not by requiring an
actually torch-free environment.
"""

from __future__ import annotations

import inspect

import pytest

from edge.eval.u06_diagnostic_report import ScenarioBaselineResult
from edge.eval.u06_dqn_augmented_diagnostic_report import (
    TORCH_AVAILABLE,
    TORCH_UNAVAILABLE_REASON,
    DQNAugmentedDiagnosticReport,
    build_dqn_augmented_diagnostic_report,
    main,
)

_EXPECTED_SCENARIOS = {
    "clean_degradation",
    "injected_current_spike",
    "injected_temperature_drift",
    "injected_pressure_stuck_at",
    "injected_humidity_bias_fdi",
    "injected_gas_ramp_fdi",
    "injected_vibration_replay",
    "injected_current_constant_spoof",
    "injected_temperature_adaptive_stealth_fdi",
}


# ---------------------------------------------------------------------------
# Importing this module never requires torch
# ---------------------------------------------------------------------------


def test_module_does_not_import_torch_or_rl_training_at_module_scope():
    """Structural guard: merely importing this module must never require
    torch -- edge.eval.u06_dqn_evaluation_report is imported only inside
    build_dqn_augmented_diagnostic_report(), deferred, after confirming
    TORCH_AVAILABLE."""
    import ast

    import edge.eval.u06_dqn_augmented_diagnostic_report as module

    tree = ast.parse(inspect.getsource(module))
    module_level_imports: set[str] = set()
    for node in tree.body:  # module.body only -- top level, not nested in functions
        if isinstance(node, ast.Import):
            module_level_imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_level_imports.add(node.module)

    assert "torch" not in module_level_imports
    assert not any(m.startswith("edge.eval.rl_training") for m in module_level_imports)
    assert not any(
        m.startswith("edge.eval.u06_dqn_evaluation_report") for m in module_level_imports
    )


# ---------------------------------------------------------------------------
# Baseline results are always populated, unchanged from the existing
# aggregate diagnostic report
# ---------------------------------------------------------------------------


def test_baseline_results_are_always_populated_regardless_of_torch():
    report = build_dqn_augmented_diagnostic_report()
    assert len(report.baseline_results) == 18
    for result in report.baseline_results:
        assert isinstance(result, ScenarioBaselineResult)


def test_baseline_results_match_the_existing_unmodified_aggregate_report():
    """Regression guard: this module must not change
    edge.eval.u06_diagnostic_report.build_diagnostic_report()'s own
    output in any way."""
    from edge.eval.u06_diagnostic_report import build_diagnostic_report

    direct_report = build_diagnostic_report()
    augmented_report = build_dqn_augmented_diagnostic_report()
    assert augmented_report.baseline_results == direct_report.results


def test_baseline_results_carry_confidence_interval_fields():
    report = build_dqn_augmented_diagnostic_report()
    for result in report.baseline_results:
        assert hasattr(result, "channel_agreement_interval")
        assert hasattr(result, "axis_i_false_isolation_interval")


# ---------------------------------------------------------------------------
# Torch-available behavior
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch is not installed in this environment")
def test_dqn_results_are_populated_when_torch_is_available():
    report = build_dqn_augmented_diagnostic_report()
    assert report.dqn_evaluation_skipped_reason is None
    assert report.dqn_results is not None
    assert len(report.dqn_results) == 9
    scenario_names = {r.scenario_name for r in report.dqn_results}
    assert scenario_names == _EXPECTED_SCENARIOS


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch is not installed in this environment")
def test_dqn_results_report_dqn_policy_baseline_name():
    report = build_dqn_augmented_diagnostic_report()
    for result in report.dqn_results:
        assert result.baseline_name == "dqn_policy"


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch is not installed in this environment")
def test_dqn_diagnostic_metadata_is_documented_when_available():
    from edge.eval.u06_dqn_evaluation_report import (
        REWARD_WEIGHTS_FIXTURE_NAME,
        U06_DQN_DIAGNOSTIC_SEED,
    )

    report = build_dqn_augmented_diagnostic_report()
    assert report.dqn_diagnostic_seed == U06_DQN_DIAGNOSTIC_SEED
    assert report.dqn_reward_weights_fixture_name == REWARD_WEIGHTS_FIXTURE_NAME


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch is not installed in this environment")
def test_dqn_results_have_no_confidence_interval_fields_in_this_increment():
    """Architectural confirmation: DQNScenarioResult is used completely
    unmodified here -- confidence-interval wiring was explicitly scoped to
    the aggregate/seed-repetition reports only, not to the DQN module."""
    report = build_dqn_augmented_diagnostic_report()
    for result in report.dqn_results:
        assert not hasattr(result, "channel_agreement_interval")


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch is not installed in this environment")
def test_dqn_integration_does_not_change_the_standalone_dqn_module_output():
    """Regression guard: this integration module must not change
    edge.eval.u06_dqn_evaluation_report.build_dqn_diagnostic_report()'s
    own output."""
    from edge.eval.u06_dqn_evaluation_report import build_dqn_diagnostic_report

    direct_report = build_dqn_diagnostic_report()
    augmented_report = build_dqn_augmented_diagnostic_report()
    assert augmented_report.dqn_results == direct_report.results


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch is not installed in this environment")
def test_deterministic_dqn_integration_across_independent_builds():
    first = build_dqn_augmented_diagnostic_report()
    second = build_dqn_augmented_diagnostic_report()
    assert first.dqn_results == second.dqn_results
    assert first.baseline_results == second.baseline_results


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch is not installed in this environment")
def test_no_checkpoint_file_is_created_by_the_integration_layer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    build_dqn_augmented_diagnostic_report()
    created_files = list(tmp_path.rglob("*"))
    assert not any(f.suffix in (".pt", ".pth", ".ckpt") for f in created_files if f.is_file())


# ---------------------------------------------------------------------------
# Torch-unavailable behavior -- simulated via monkeypatching, documented
# clearly (this is the ONLY condition that skips DQN evaluation)
# ---------------------------------------------------------------------------


def test_dqn_evaluation_is_skipped_with_a_documented_reason_when_torch_unavailable(monkeypatch):
    import edge.eval.u06_dqn_augmented_diagnostic_report as module

    monkeypatch.setattr(module, "TORCH_AVAILABLE", False)
    report = module.build_dqn_augmented_diagnostic_report()
    assert report.dqn_results is None
    assert report.dqn_evaluation_skipped_reason == TORCH_UNAVAILABLE_REASON
    assert report.dqn_diagnostic_seed is None
    assert report.dqn_reward_weights_fixture_name is None


def test_baseline_results_remain_populated_when_torch_unavailable(monkeypatch):
    """DQN evaluation is a strictly additive extension -- its absence must
    never affect the two deterministic baselines' own results."""
    import edge.eval.u06_dqn_augmented_diagnostic_report as module

    monkeypatch.setattr(module, "TORCH_AVAILABLE", False)
    report = module.build_dqn_augmented_diagnostic_report()
    assert len(report.baseline_results) == 18


def test_skip_reason_is_the_only_documented_skip_condition():
    """Structural guard: TORCH_UNAVAILABLE_REASON must be the sole
    documented skip reason string in this module -- no other silent-skip
    condition exists."""
    import edge.eval.u06_dqn_augmented_diagnostic_report as module

    source = inspect.getsource(module)
    assert source.count("_skipped_reason=") <= 2  # the two constructor call sites only
    assert "except Exception" not in source
    assert "except ImportError" not in source or "TORCH_AVAILABLE" in source


# ---------------------------------------------------------------------------
# No new methodology, no pooling, no threshold/verdict/reward-selection/
# real-world claim
# ---------------------------------------------------------------------------


def test_report_dataclass_has_no_pooled_or_cross_seed_field():
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(DQNAugmentedDiagnosticReport)}
    assert not any(
        "pooled" in name or "mean" in name or "stdev" in name or "variance" in name
        for name in field_names
    )


def test_module_makes_no_threshold_verdict_reward_selection_or_real_world_claim():
    import edge.eval.u06_dqn_augmented_diagnostic_report as module

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
        "preferred reward",
        "best reward",
        "optimal reward",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_does_not_modify_either_wrapped_module():
    import edge.eval.u06_dqn_augmented_diagnostic_report as module

    source = inspect.getsource(module)
    assert "def build_diagnostic_report(" not in source
    assert "def build_dqn_diagnostic_report(" not in source
    assert "class ScenarioBaselineResult" not in source
    assert "class DQNScenarioResult" not in source


# ---------------------------------------------------------------------------
# Full regression coverage for existing reports and axes
# ---------------------------------------------------------------------------


def test_seed_repetition_reports_are_unaffected():
    from edge.eval.u06_seed_repetition_report import build_seed_repetition_report

    report = build_seed_repetition_report()
    assert len(report.results) == 10


def test_main_runs_without_raising(capsys):
    main()
    captured = capsys.readouterr()
    assert "torch available" in captured.out
    if TORCH_AVAILABLE:
        assert "not an approved U06 reward-weight decision" in captured.out
