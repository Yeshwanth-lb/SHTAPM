"""Tests for edge/eval/u06_ground_truth_rate_summary.py (axis (iii)
coarse, ground-truth-anchored decision-quality rate summary -- pure,
additive, opt-in). No channel matching, no threshold, no verdict, no
real-world claim exists here -- see the module's own docstring.

Two kinds of fixtures are used deliberately (same convention as
edge/tests/test_u06_rate_summary.py and
edge/tests/test_u06_tracker_agreement.py):
  - real episodes (run_baseline_policy_episode/run_pure_fallback_episode on
    committed scenarios) for the "known hand-computed counts" and
    "no mutation" tests;
  - directly-constructed minimal TransitionRecord/EpisodeRecord fixtures
    (via the _transition()/_episode() helpers below) for the definition,
    exclusion, and breakdown boundary cases.
"""

from __future__ import annotations

import inspect

from app.schemas.contracts import RLAction

from edge.eval.rl_baseline_eval import (
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_SPIKE,
    EpisodeRecord,
    TransitionRecord,
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)
from edge.eval.u06_ground_truth_rate_summary import (
    GroundTruthRateSummary,
    summarize_ground_truth_rates,
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
# Ground-truth missed fault
# ---------------------------------------------------------------------------


def test_injected_step_with_continue_is_ground_truth_missed_fault():
    transitions = [
        _transition(
            requested_action=RLAction.continue_.value, active_injection_labels=("spike",)
        )
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.missed_fault_denominator == 1
    assert summary.missed_fault_numerator == 1
    assert summary.missed_fault_rate == 1.0


def test_injected_step_with_isolate_or_reduce_weight_is_not_missed():
    transitions = [
        _transition(
            requested_action=RLAction.isolate.value, active_injection_labels=("drift",)
        ),
        _transition(
            requested_action=RLAction.reduce_weight.value, active_injection_labels=("drift",)
        ),
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.missed_fault_denominator == 2
    assert summary.missed_fault_numerator == 0
    assert summary.missed_fault_rate == 0.0


# ---------------------------------------------------------------------------
# Ground-truth false isolation
# ---------------------------------------------------------------------------


def test_clean_step_with_isolate_or_reduce_weight_is_ground_truth_false_isolation():
    transitions = [
        _transition(requested_action=RLAction.isolate.value, active_injection_labels=()),
        _transition(requested_action=RLAction.reduce_weight.value, active_injection_labels=()),
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 2
    assert summary.false_isolation_numerator == 2
    assert summary.false_isolation_rate == 1.0


def test_clean_step_with_continue_is_not_false_isolation():
    transitions = [
        _transition(requested_action=RLAction.continue_.value, active_injection_labels=())
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 1
    assert summary.false_isolation_numerator == 0
    assert summary.false_isolation_rate == 0.0


# ---------------------------------------------------------------------------
# safe_stop: remains in denominators, cannot trigger either numerator
# ---------------------------------------------------------------------------


def test_safe_stop_request_on_clean_step_counts_toward_false_isolation_denominator_only():
    transitions = [
        _transition(
            requested_action=RLAction.safe_stop.value,
            approved_action=RLAction.safe_stop.value,
            active_injection_labels=(),
            transition_consumed=False,
            safe_stop_terminated_without_transition=True,
        )
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 1
    assert summary.false_isolation_numerator == 0
    assert summary.safe_stop_request_count == 1
    assert summary.missed_fault_denominator == 0


def test_safe_stop_request_on_injected_step_counts_toward_missed_fault_denominator_only():
    transitions = [
        _transition(
            requested_action=RLAction.safe_stop.value,
            approved_action=RLAction.safe_stop.value,
            active_injection_labels=("spike",),
            transition_consumed=False,
            safe_stop_terminated_without_transition=True,
        )
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.missed_fault_denominator == 1
    assert summary.missed_fault_numerator == 0
    assert summary.safe_stop_request_count == 1
    assert summary.false_isolation_denominator == 0


def test_safe_stop_cannot_trigger_either_numerator_regardless_of_injection_state():
    for injected in ((), ("spike",)):
        transitions = [
            _transition(
                requested_action=RLAction.safe_stop.value,
                approved_action=RLAction.safe_stop.value,
                active_injection_labels=injected,
                transition_consumed=False,
            )
        ]
        summary = summarize_ground_truth_rates(_episode(transitions))
        assert summary.false_isolation_numerator == 0
        assert summary.missed_fault_numerator == 0


# ---------------------------------------------------------------------------
# No transition_consumed filtering (unlike axis (ii))
# ---------------------------------------------------------------------------


def test_transition_consumed_false_steps_are_still_counted():
    """Axis (iii) evaluates decisions, not distinct newly observed frames
    -- a safe_stop no-op step is still a genuine, distinct policy decision
    and must be counted (see module docstring's UNIT OF COMPARISON
    section), unlike axis (ii)'s transition_consumed=True filter."""
    transitions = [
        _transition(
            requested_action=RLAction.continue_.value,
            active_injection_labels=("spike",),
            transition_consumed=True,
        ),
        _transition(
            requested_action=RLAction.safe_stop.value,
            approved_action=RLAction.safe_stop.value,
            active_injection_labels=("spike",),
            transition_consumed=False,
            safe_stop_terminated_without_transition=True,
        ),
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    # Both steps are genuine decisions and must both appear in the
    # denominator, regardless of transition_consumed.
    assert summary.missed_fault_denominator == 2
    assert summary.missed_fault_numerator == 1  # only the continue_ step
    assert summary.safe_stop_request_count == 1


# ---------------------------------------------------------------------------
# Per-injection-type breakdown, no pooling
# ---------------------------------------------------------------------------


def test_per_injection_type_breakdown_is_scoped_and_not_pooled():
    transitions = [
        _transition(
            requested_action=RLAction.continue_.value, active_injection_labels=("spike",)
        ),
        _transition(
            requested_action=RLAction.isolate.value, active_injection_labels=("spike",)
        ),
        _transition(
            requested_action=RLAction.continue_.value, active_injection_labels=("drift",)
        ),
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    spike = summary.per_injection_type["spike"]
    assert spike.observation_count == 2
    assert spike.missed_fault_count == 1
    assert spike.missed_fault_rate == 0.5

    drift = summary.per_injection_type["drift"]
    assert drift.observation_count == 1
    assert drift.missed_fault_count == 1
    assert drift.missed_fault_rate == 1.0

    # Aggregate must not be a naive average of the two types' own rates.
    assert summary.missed_fault_denominator == 3
    assert summary.missed_fault_numerator == 2


def test_multi_injection_observation_is_attributed_to_each_active_type():
    transitions = [
        _transition(
            requested_action=RLAction.continue_.value,
            active_injection_labels=("spike", "drift"),
        )
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.missed_fault_denominator == 1
    assert summary.per_injection_type["spike"].observation_count == 1
    assert summary.per_injection_type["drift"].observation_count == 1
    assert summary.per_injection_type["spike"].missed_fault_count == 1
    assert summary.per_injection_type["drift"].missed_fault_count == 1


def test_adaptive_stealth_fdi_gets_its_own_unpooled_breakdown():
    transitions = [
        _transition(
            requested_action=RLAction.continue_.value,
            active_injection_labels=("adaptive_stealth_fdi",),
        ),
        _transition(
            requested_action=RLAction.continue_.value, active_injection_labels=("spike",)
        ),
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert set(summary.per_injection_type.keys()) == {"adaptive_stealth_fdi", "spike"}
    assert summary.per_injection_type["adaptive_stealth_fdi"].missed_fault_rate == 1.0
    assert summary.per_injection_type["spike"].missed_fault_rate == 1.0


# ---------------------------------------------------------------------------
# Clean / no-injection breakdown
# ---------------------------------------------------------------------------


def test_no_injection_breakdown_mirrors_top_level_false_isolation_fields():
    transitions = [
        _transition(requested_action=RLAction.isolate.value, active_injection_labels=()),
        _transition(requested_action=RLAction.continue_.value, active_injection_labels=()),
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.no_injection.observation_count == summary.false_isolation_denominator
    assert summary.no_injection.false_isolation_count == summary.false_isolation_numerator
    assert summary.no_injection.false_isolation_rate == summary.false_isolation_rate
    assert summary.per_injection_type == {}


# ---------------------------------------------------------------------------
# Zero-denominator behavior: None, never 0.0
# ---------------------------------------------------------------------------


def test_zero_denominators_return_none_not_zero():
    # No transitions with a non-None requested action while uninjected, and
    # no injected transitions at all.
    transitions = [
        _transition(requested_action=None, active_injection_labels=())
    ]
    summary = summarize_ground_truth_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 0
    assert summary.false_isolation_rate is None
    assert summary.missed_fault_denominator == 0
    assert summary.missed_fault_rate is None
    assert summary.no_injection.false_isolation_rate is None


# ---------------------------------------------------------------------------
# Known hand-computed counts on committed scenarios
# ---------------------------------------------------------------------------


def test_known_counts_on_injected_current_spike_scenario():
    """Empirically verified (this increment's own sanity check): the
    BaselinePolicy requests reduce_weight throughout this scenario's 4
    non-injected steps (ground-truth false isolation, since no injection
    is active there) and never requests continue_ during the 5-step spike
    window (ground-truth missed-fault rate 0.0 for this run) -- a
    diagnostic observation about THIS pipeline/scenario/policy
    combination, not a real-world accuracy or policy-failure claim (see
    module docstring's REQUIRED METHODOLOGICAL DISCLAIMERS)."""
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    summary = summarize_ground_truth_rates(record)

    assert summary.false_isolation_denominator == 4
    assert summary.false_isolation_numerator == 4
    assert summary.missed_fault_denominator == 5
    assert summary.per_injection_type["spike"].observation_count == 5


def test_known_counts_on_clean_degradation_scenario():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_ground_truth_rates(record)

    assert summary.missed_fault_denominator == 0
    assert summary.missed_fault_rate is None
    assert summary.per_injection_type == {}
    assert summary.no_injection.observation_count == 9


# ---------------------------------------------------------------------------
# Scenario identity preservation
# ---------------------------------------------------------------------------


def test_scenario_and_baseline_identity_are_preserved():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_ground_truth_rates(record)
    assert summary.scenario_name == record.scenario_name
    assert summary.baseline_name == record.baseline_name


# ---------------------------------------------------------------------------
# No mutation of the input EpisodeRecord/transitions
# ---------------------------------------------------------------------------


def test_summarize_does_not_mutate_the_input_episode_record():
    record = run_pure_fallback_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    transitions_before = record.transitions
    reward_before = record.cumulative_reward

    summarize_ground_truth_rates(record)

    assert record.transitions is transitions_before
    assert record.cumulative_reward == reward_before

    summary = summarize_ground_truth_rates(record)
    assert not isinstance(summary, EpisodeRecord)
    assert isinstance(summary, GroundTruthRateSummary)


# ---------------------------------------------------------------------------
# Structural: required disclaimers, no threshold/verdict/real-world claim
# ---------------------------------------------------------------------------


def test_module_documents_the_required_disclaimers():
    import edge.eval.u06_ground_truth_rate_summary as module

    source = inspect.getsource(module).lower()
    assert "attempted" in source
    assert "not necessarily" in source or "does not mean" in source
    assert "rlstate" in source
    assert "not proof of" in source or "not proof" in source
    assert "adaptivestealthfdi" in source


def test_module_makes_no_threshold_verdict_or_real_world_claim():
    import edge.eval.u06_ground_truth_rate_summary as module

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
        "proves policy failure",
        "is a policy failure",
        "real-world accuracy claim",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_does_not_widen_labels_or_add_channel_matching():
    import dataclasses

    from edge.eval.u06_ground_truth_rate_summary import (
        GroundTruthRateSummary as Summary,
    )
    from edge.eval.u06_ground_truth_rate_summary import (
        InjectionTypeMissedFaultBreakdown,
        NoInjectionFalseIsolationBreakdown,
    )

    for cls in (Summary, InjectionTypeMissedFaultBreakdown, NoInjectionFalseIsolationBreakdown):
        fields = {f.name for f in dataclasses.fields(cls)}
        assert not any("channel" in name for name in fields)


def test_module_has_no_hardware_network_or_actuation_imports():
    import edge.eval.u06_ground_truth_rate_summary as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RelayController", "FakeActuator", "SelfHealOrchestrator", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()
