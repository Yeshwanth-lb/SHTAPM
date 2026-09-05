"""Tests for edge/eval/rl_baseline_eval.py (diagnostic-only RL baseline
evaluation harness). No RL training, learned policy, or validation claim
exists here -- see the module's own docstring.
"""

from __future__ import annotations

from app.schemas.contracts import RLAction

from edge.eval.rl_baseline_eval import (
    ACTION_DEPENDENT_COMPARISON_CAVEAT,
    DATA_SOURCE,
    EXECUTION_MODE,
    MODEL_STATUS,
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_SPIKE,
    EpisodeRecord,
    ScenarioConfig,
    TransitionRecord,
    default_scenarios,
    run_all_baselines,
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)

SCENARIO = SCENARIO_CLEAN_DEGRADATION


# ---------------------------------------------------------------------------
# Both baselines run successfully and produce episode records
# ---------------------------------------------------------------------------


def test_baseline_policy_episode_runs_and_returns_episode_record():
    record = run_baseline_policy_episode(SCENARIO)
    assert isinstance(record, EpisodeRecord)
    assert record.step_count > 0


def test_pure_fallback_episode_runs_and_returns_episode_record():
    record = run_pure_fallback_episode(SCENARIO)
    assert isinstance(record, EpisodeRecord)
    assert record.step_count > 0


def test_both_baselines_use_the_same_scenario_definition():
    baseline_record = run_baseline_policy_episode(SCENARIO)
    fallback_record = run_pure_fallback_episode(SCENARIO)
    assert baseline_record.scenario_name == fallback_record.scenario_name == SCENARIO.name
    assert baseline_record.scenario_config == fallback_record.scenario_config == SCENARIO


def test_run_all_baselines_covers_every_default_scenario_and_both_baselines():
    records = run_all_baselines()
    scenario_names = {r.scenario_name for r in records}
    baseline_names = {r.baseline_name for r in records}
    assert scenario_names == {s.name for s in default_scenarios()}
    assert baseline_names == {"baseline_policy", "pure_fallback"}
    assert len(records) == len(default_scenarios()) * 2


# ---------------------------------------------------------------------------
# BaselinePolicy path uses the existing policy
# ---------------------------------------------------------------------------


def test_baseline_policy_path_reports_policy_available_true():
    record = run_baseline_policy_episode(SCENARIO)
    # BaselinePolicy always reports policy_available=True (see edge/rl/policy.py) --
    # so the gate's policy_status is never "unavailable" for this baseline.
    assert all(t.policy_status != "unavailable" for t in record.transitions)


def test_baseline_policy_path_is_named_correctly():
    record = run_baseline_policy_episode(SCENARIO)
    assert record.baseline_name == "baseline_policy"


# ---------------------------------------------------------------------------
# Pure-fallback path sets policy_available=False
# ---------------------------------------------------------------------------


def test_pure_fallback_path_reports_policy_unavailable_every_step():
    record = run_pure_fallback_episode(SCENARIO)
    assert all(t.policy_status == "unavailable" for t in record.transitions)


def test_pure_fallback_path_requests_no_action():
    record = run_pure_fallback_episode(SCENARIO)
    assert all(t.requested_action is None for t in record.transitions)


def test_pure_fallback_path_is_named_correctly():
    record = run_pure_fallback_episode(SCENARIO)
    assert record.baseline_name == "pure_fallback"


# ---------------------------------------------------------------------------
# Every step passes through the fallback gate; requested/approved recorded
# separately
# ---------------------------------------------------------------------------


def test_every_transition_carries_full_gate_fields():
    for record in (run_baseline_policy_episode(SCENARIO), run_pure_fallback_episode(SCENARIO)):
        for t in record.transitions:
            assert isinstance(t, TransitionRecord)
            assert isinstance(t.fallback_used, bool)
            assert t.safety_status in ("nominal", "isolation_active", "safe_stop_active")
            assert t.policy_status in (
                "unavailable",
                "unvalidated",
                "validated_low_confidence",
                "validated",
            )
            assert t.approved_action in {a.value for a in RLAction}


def test_requested_and_approved_actions_are_separate_fields():
    record = run_baseline_policy_episode(SCENARIO)
    # BaselinePolicy always reports policy_validated=False -> the gate must
    # override every non-safe_stop request, so requested != approved for at
    # least one transition (proves the two fields are genuinely independent).
    assert any(t.requested_action != t.approved_action for t in record.transitions)


# ---------------------------------------------------------------------------
# Reward totals are scalar (fixture weights explicitly supplied)
# ---------------------------------------------------------------------------


def test_every_transition_has_a_scalar_reward_total():
    for record in (run_baseline_policy_episode(SCENARIO), run_pure_fallback_episode(SCENARIO)):
        for t in record.transitions:
            assert isinstance(t.total_reward, float)


def test_episode_reward_policy_status_is_simulation_fixture_weighted():
    record = run_baseline_policy_episode(SCENARIO)
    assert record.reward_policy_status == "simulation_fixture_weighted"


# ---------------------------------------------------------------------------
# Fallback rate and action histograms are correct
# ---------------------------------------------------------------------------


def test_fallback_rate_matches_manual_computation():
    record = run_baseline_policy_episode(SCENARIO)
    manual_count = sum(1 for t in record.transitions if t.fallback_used)
    assert record.fallback_count == manual_count
    assert record.fallback_rate == manual_count / record.step_count


def test_pure_fallback_rate_is_always_one():
    record = run_pure_fallback_episode(SCENARIO)
    assert record.fallback_rate == 1.0
    assert record.fallback_count == record.step_count


def test_action_histograms_match_manual_computation():
    record = run_baseline_policy_episode(SCENARIO)
    manual_requested: dict[str, int] = {}
    manual_approved: dict[str, int] = {}
    for t in record.transitions:
        key = t.requested_action or "none"
        manual_requested[key] = manual_requested.get(key, 0) + 1
        manual_approved[t.approved_action] = manual_approved.get(t.approved_action, 0) + 1
    assert record.requested_action_histogram == manual_requested
    assert record.approved_action_histogram == manual_approved
    assert sum(record.approved_action_histogram.values()) == record.step_count


# ---------------------------------------------------------------------------
# Termination causes are recorded
# ---------------------------------------------------------------------------


def test_termination_cause_is_a_known_value():
    for record in (run_baseline_policy_episode(SCENARIO), run_pure_fallback_episode(SCENARIO)):
        assert record.termination_cause in ("trajectory_exhausted", "safe_stop")


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_repeated_baseline_policy_runs_are_identical():
    first = run_baseline_policy_episode(SCENARIO)
    second = run_baseline_policy_episode(SCENARIO)
    assert first == second


def test_repeated_pure_fallback_runs_are_identical():
    first = run_pure_fallback_episode(SCENARIO)
    second = run_pure_fallback_episode(SCENARIO)
    assert first == second


def test_different_scenarios_are_independent_and_reproducible():
    a1 = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    a2 = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    assert a1 == a2
    assert a1.scenario_name == "injected_current_spike"


# ---------------------------------------------------------------------------
# Simulation metadata
# ---------------------------------------------------------------------------


def test_episode_record_carries_simulation_metadata():
    record = run_baseline_policy_episode(SCENARIO)
    assert record.execution_mode == "simulation"
    assert record.data_source == "synthetic"
    assert record.model_status == "diagnostic_unvalidated"
    assert (EXECUTION_MODE, DATA_SOURCE, MODEL_STATUS) == (
        "simulation",
        "synthetic",
        "diagnostic_unvalidated",
    )


def test_transition_record_carries_simulation_metadata():
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert t.execution_mode == "simulation"
        assert t.data_source == "synthetic"
        assert t.model_status == "diagnostic_unvalidated"


# ---------------------------------------------------------------------------
# Action-dependent transition info is recorded (edge/rl/environment.py's
# ACTION-DEPENDENT TRANSITION -- this harness only records it, never
# duplicates the underlying logic)
# ---------------------------------------------------------------------------


def test_transition_record_carries_substitution_fields():
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert isinstance(t.transition_consumed, bool)
        assert isinstance(t.safe_stop_terminated_without_transition, bool)
        assert isinstance(t.substituted_channels, tuple)
        assert t.transition_substitution_mode in (None, "hold_last_value")


def test_no_substitution_occurs_on_clean_untracked_data():
    """Neither baseline should have anything to substitute on this
    scenario -- no injections, no forced tracking."""
    for record in (run_baseline_policy_episode(SCENARIO), run_pure_fallback_episode(SCENARIO)):
        assert all(t.substituted_channels == () for t in record.transitions)
        assert all(t.transition_substitution_mode is None for t in record.transitions)


def test_transition_consumed_is_false_only_when_safe_stop_terminates_without_transition():
    for record in (run_baseline_policy_episode(SCENARIO), run_pure_fallback_episode(SCENARIO)):
        for t in record.transitions:
            assert t.transition_consumed != t.safe_stop_terminated_without_transition


def test_episode_record_carries_the_comparison_caveat():
    record = run_baseline_policy_episode(SCENARIO)
    assert record.comparison_caveat == ACTION_DEPENDENT_COMPARISON_CAVEAT
    assert "decision quality" in record.comparison_caveat


def test_scenario_config_is_explicit_and_reproducible():
    assert isinstance(SCENARIO, ScenarioConfig)
    assert SCENARIO.seed is not None
    assert SCENARIO.length > 0
    assert 0.0 <= SCENARIO.end_health < SCENARIO.start_health <= 1.0
    assert SCENARIO.channels  # at least one channel explicitly configured


def test_no_prognosis_failure_eta_is_always_none():
    """This harness wires no PrognosisRuntime (see module docstring) --
    every recorded failure_eta must honestly be None, never fabricated."""
    record = run_baseline_policy_episode(SCENARIO)
    assert record.final_failure_eta is None


# ---------------------------------------------------------------------------
# No hardware or external side effects; no over-claimed validation
# ---------------------------------------------------------------------------


def test_module_has_no_hardware_network_or_actuation_imports():
    import edge.eval.rl_baseline_eval as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in (
        "RelayController",
        "FakeActuator",
        "SelfHealOrchestrator",
        "process_isolated_channels",
        "paho",
    ):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


def test_module_never_claims_validation_or_production_readiness():
    import edge.eval.rl_baseline_eval as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "hardware-validated" not in content
    assert "validated for production" not in content
    assert "this baseline is validated" not in content
