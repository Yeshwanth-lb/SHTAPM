"""Tests for edge/eval/u06_channel_agreement.py (channel-matched U06
tracker-vs-injection agreement -- pure, additive, opt-in). No axis (i),
no axis (iii), no sample_seq deduplication, no threshold, no verdict, no
real-world claim exists here -- see the module's own docstring.

Two kinds of fixtures are used deliberately (same convention as
edge/tests/test_u06_tracker_agreement.py):
  - real episodes (run_baseline_policy_episode on committed scenarios) for
    the "known real mismatch" and "no mutation" tests, anchored to real,
    already-committed behavior;
  - directly-constructed minimal TransitionRecord/EpisodeRecord fixtures
    (via the _transition()/_episode() helpers below) for the match/
    mismatch/descriptive-only/no-observation boundary cases --
    summarize_channel_agreement() is a PURE function over these
    dataclasses, so exercising its exact branch logic directly is the
    precise way to test it.
"""

from __future__ import annotations

import inspect

from app.schemas.contracts import RLAction

from edge.eval.rl_baseline_eval import (
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF,
    SCENARIO_INJECTED_CURRENT_SPIKE,
    EpisodeRecord,
    TransitionRecord,
    run_baseline_policy_episode,
)
from edge.eval.u06_channel_agreement import (
    ChannelAgreementSummary,
    summarize_channel_agreement,
)


def _transition(**overrides) -> TransitionRecord:
    defaults = {
        "episode_index": 0,
        "step_index": 0,
        "previous_state_vector": (0.0,),
        "next_state_vector": (0.0,),
        "requested_action": RLAction.continue_.value,
        "approved_action": RLAction.continue_.value,
        "fallback_used": False,
        "fallback_reason": None,
        "safety_status": "nominal",
        "policy_status": "validated",
        "reward_components": {},
        "total_reward": 0.0,
        "done": False,
        "transition_consumed": True,
        "safe_stop_terminated_without_transition": False,
        "transition_substitution_mode": None,
        "substituted_channels": (),
        "active_injection_labels": (),
        "active_injection_channels": (),
        "tracked_channels": (),
    }
    defaults.update(overrides)
    return TransitionRecord(**defaults)


def _episode(transitions, **overrides) -> EpisodeRecord:
    transitions = tuple(transitions)
    defaults = {
        "baseline_name": "test_baseline",
        "scenario_name": "test_scenario",
        "scenario_config": SCENARIO_CLEAN_DEGRADATION,
        "cumulative_reward": 0.0,
        "step_count": len(transitions),
        "termination_cause": "trajectory_exhausted",
        "fallback_count": 0,
        "fallback_rate": 0.0,
        "requested_action_histogram": {},
        "approved_action_histogram": {},
        "final_health": 1.0,
        "final_failure_eta": None,
        "reward_policy_status": "unweighted",
        "transitions": transitions,
    }
    defaults.update(overrides)
    return EpisodeRecord(**defaults)


# ---------------------------------------------------------------------------
# Single-channel match / mismatch (approved rules 1, 2a, 2b)
# ---------------------------------------------------------------------------


def test_identical_single_channel_sets_are_a_match():
    transitions = [
        _transition(active_injection_channels=("current",), tracked_channels=("current",))
    ]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 1
    assert summary.channel_match_count == 1
    assert summary.channel_mismatch_count == 0
    assert summary.channel_match_rate == 1.0


def test_different_single_channel_sets_are_a_mismatch():
    transitions = [
        _transition(active_injection_channels=("current",), tracked_channels=("voltage",))
    ]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 1
    assert summary.channel_match_count == 0
    assert summary.channel_mismatch_count == 1
    assert summary.channel_match_rate == 0.0


# ---------------------------------------------------------------------------
# No-observation cases (approved rules 2c, 5a, 5c)
# ---------------------------------------------------------------------------


def test_injection_with_no_tracked_channels_is_not_a_channel_match_observation():
    """approved rule 2c / 5c: axis (ii) owns this case entirely -- this
    module must not count it as a match, a mismatch, or any observation."""
    transitions = [_transition(active_injection_channels=("current",), tracked_channels=())]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 0
    assert summary.channel_match_count == 0
    assert summary.channel_mismatch_count == 0
    assert summary.channel_match_rate is None
    assert summary.tracked_without_injection_observation_count == 0


def test_no_injection_and_no_tracked_channels_is_not_reported_anywhere():
    """approved rule 5a: nothing to describe or compare."""
    transitions = [_transition(active_injection_channels=(), tracked_channels=())]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 0
    assert summary.tracked_without_injection_observation_count == 0
    assert summary.tracked_without_injection_channels_seen == ()


# ---------------------------------------------------------------------------
# Descriptive-only: tracked without injection (approved rule 5b)
# ---------------------------------------------------------------------------


def test_tracked_channel_with_no_injection_is_descriptive_only_not_a_verdict():
    transitions = [_transition(active_injection_channels=(), tracked_channels=("vibration",))]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 0
    assert summary.channel_match_count == 0
    assert summary.channel_mismatch_count == 0
    assert summary.channel_match_rate is None
    assert summary.tracked_without_injection_observation_count == 1
    assert summary.tracked_without_injection_channels_seen == ("vibration",)


def test_tracked_without_injection_channels_seen_is_deduplicated_and_sorted():
    transitions = [
        _transition(active_injection_channels=(), tracked_channels=("vibration",)),
        _transition(active_injection_channels=(), tracked_channels=("current",)),
        _transition(active_injection_channels=(), tracked_channels=("vibration",)),
    ]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.tracked_without_injection_observation_count == 3
    assert summary.tracked_without_injection_channels_seen == ("current", "vibration")


# ---------------------------------------------------------------------------
# Multi-channel: complete-set comparison, no partial credit, no per-channel
# rows (approved rule 3), extra tracked channel forces mismatch (rule 4)
# ---------------------------------------------------------------------------


def test_identical_multi_channel_sets_are_a_match():
    transitions = [
        _transition(
            active_injection_channels=("current", "temperature"),
            tracked_channels=("temperature", "current"),
        )
    ]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 1
    assert summary.channel_match_count == 1
    assert summary.channel_mismatch_count == 0


def test_missing_one_of_two_injected_channels_is_a_mismatch_not_partial():
    transitions = [
        _transition(
            active_injection_channels=("current", "temperature"),
            tracked_channels=("current",),
        )
    ]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 1
    assert summary.channel_match_count == 0
    assert summary.channel_mismatch_count == 1


def test_extra_tracked_channel_beyond_injected_set_is_a_mismatch():
    """approved rule 4: any extra tracked channel makes the complete-set
    comparison a mismatch, even if every injected channel is also tracked."""
    transitions = [
        _transition(
            active_injection_channels=("current",),
            tracked_channels=("current", "vibration"),
        )
    ]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 1
    assert summary.channel_match_count == 0
    assert summary.channel_mismatch_count == 1


def test_no_per_channel_breakdown_field_exists():
    """Structural guard for approved rule 3: this module must never produce
    per-channel rows or counts that could exceed the observation total --
    verified by asserting the dataclass carries no such field at all."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ChannelAgreementSummary)}
    assert not any("per_channel" in name or "per_injection" in name for name in field_names)


# ---------------------------------------------------------------------------
# transition_consumed filtering (observation unit)
# ---------------------------------------------------------------------------


def test_transition_not_consumed_is_excluded_from_observations():
    transitions = [
        _transition(
            active_injection_channels=("current",),
            tracked_channels=("current",),
            transition_consumed=False,
        )
    ]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_observation_count == 0
    assert summary.channel_match_rate is None


# ---------------------------------------------------------------------------
# Zero-opportunity handling (approved rule 6)
# ---------------------------------------------------------------------------


def test_zero_channel_match_opportunities_reports_none_never_zero():
    transitions = [_transition(active_injection_channels=(), tracked_channels=())]
    summary = summarize_channel_agreement(_episode(transitions))
    assert summary.channel_match_rate is None
    assert summary.channel_match_rate != 0.0


def test_report_is_never_a_zero_rate_when_denominator_is_zero():
    """Regression guard distinguishing 'no opportunity' from 'always
    mismatched' -- both could otherwise look like 0.0 if coded carelessly."""
    empty_episode = _episode([_transition()])
    summary = summarize_channel_agreement(empty_episode)
    assert summary.channel_match_observation_count == 0
    assert summary.channel_match_rate is None


# ---------------------------------------------------------------------------
# Real, already-committed scenarios: known mismatch and known no-opportunity
# ---------------------------------------------------------------------------


def test_clean_scenario_has_zero_channel_match_opportunities():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_channel_agreement(record)
    assert summary.channel_match_observation_count == 0
    assert summary.channel_match_rate is None


def test_injected_current_spike_has_zero_channel_match_opportunities():
    """Verified directly: this scenario's short episode never reaches
    safety_status == "isolation_active", so tracked_channels is always
    empty -- no channel-match opportunity ever occurs."""
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    summary = summarize_channel_agreement(record)
    assert summary.channel_match_observation_count == 0
    assert summary.channel_match_rate is None


def test_constant_spoof_scenario_reports_the_known_real_mismatch():
    """Verified directly (already documented in the tracked-channel
    plumbing increment): injected_current_constant_spoof injects "current"
    but the tracker holds "vibration" -- a real, already-observed channel
    mismatch, not a synthetic test case."""
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    summary = summarize_channel_agreement(record)
    assert summary.channel_match_observation_count > 0
    assert summary.channel_match_count == 0
    assert summary.channel_mismatch_count == summary.channel_match_observation_count
    assert summary.channel_match_rate == 0.0
    assert summary.tracked_without_injection_channels_seen == ("vibration",)


# ---------------------------------------------------------------------------
# Scenario/baseline identity
# ---------------------------------------------------------------------------


def test_scenario_and_baseline_identity_are_reported():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    summary = summarize_channel_agreement(record)
    assert summary.scenario_name == "injected_current_constant_spoof"
    assert summary.baseline_name == "baseline_policy"


# ---------------------------------------------------------------------------
# Never pooled: no cross-episode/cross-seed statistic exists
# ---------------------------------------------------------------------------


def test_summary_has_no_pooled_or_cross_seed_statistic_field():
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(ChannelAgreementSummary)}
    assert field_names == {
        "scenario_name",
        "baseline_name",
        "channel_match_observation_count",
        "channel_match_count",
        "channel_mismatch_count",
        "channel_match_rate",
        "tracked_without_injection_observation_count",
        "tracked_without_injection_channels_seen",
        "execution_mode",
        "data_source",
        "model_status",
    }


def test_module_never_computes_a_statistic_beyond_its_own_single_rate():
    """AST-based check (not a source-text scan): the module must contain no
    arithmetic Div beyond the one documented rate computation, and no
    builtin min/max/sum/statistics call anywhere in its own code."""
    import ast

    import edge.eval.u06_channel_agreement as module

    tree = ast.parse(inspect.getsource(module))

    division_nodes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
    ]
    assert len(division_nodes) == 1

    forbidden_call_names = {"min", "max", "sum", "mean", "median", "stdev", "variance"}
    call_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert call_names.isdisjoint(forbidden_call_names)


# ---------------------------------------------------------------------------
# No mutation of underlying data
# ---------------------------------------------------------------------------


def test_summarize_channel_agreement_does_not_mutate_the_record():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    transitions_before = record.transitions
    summarize_channel_agreement(record)
    assert record.transitions is transitions_before


def test_summarize_channel_agreement_is_repeatable():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    first = summarize_channel_agreement(record)
    second = summarize_channel_agreement(record)
    assert first == second


# ---------------------------------------------------------------------------
# Structural: no threshold, verdict, real-world, or forbidden-module claim
# ---------------------------------------------------------------------------


def test_module_makes_no_threshold_verdict_or_real_world_claim():
    import edge.eval.u06_channel_agreement as module

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

    import edge.eval.u06_channel_agreement as module

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
        "edge.eval.u06_ground_truth_rate_summary",
        "edge.eval.u06_tracker_agreement",
    )
    for imported in imported_modules:
        assert not imported.startswith(forbidden_prefixes)


def test_module_does_not_modify_axis_ii_module():
    """This module must exist alongside u06_tracker_agreement.py, never
    replacing, importing from, or modifying its output. The module
    docstring legitimately NAMES TrackerAgreementSummary/agreement_rate/
    total_observations to state the scope boundary -- what must never
    exist is an actual import (already confirmed via AST in
    test_module_does_not_import_forbidden_modules above)."""
    import edge.eval.u06_channel_agreement as module

    source = inspect.getsource(module)
    assert "from edge.eval.u06_tracker_agreement import" not in source


def test_module_has_no_hardware_network_or_actuation_imports():
    import edge.eval.u06_channel_agreement as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RelayController", "FakeActuator", "SelfHealOrchestrator", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


# ---------------------------------------------------------------------------
# Regression: axis (ii) is unaffected by this module's existence
# ---------------------------------------------------------------------------


def test_axis_ii_output_is_unaffected_by_this_module():
    from edge.eval.u06_tracker_agreement import summarize_tracker_agreement

    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    axis_ii_before = summarize_tracker_agreement(record)
    summarize_channel_agreement(record)
    axis_ii_after = summarize_tracker_agreement(record)
    assert axis_ii_before == axis_ii_after


# ---------------------------------------------------------------------------
# main() is a simple, working printer
# ---------------------------------------------------------------------------


def test_main_runs_without_raising_and_prints_expected_sections(capsys):
    from edge.eval.u06_channel_agreement import main

    main()
    captured = capsys.readouterr()
    assert "channel_match_rate" in captured.out
    assert "tracked_without_injection_observations" in captured.out
