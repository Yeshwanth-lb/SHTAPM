"""Tests for edge/eval/u06_rate_summary.py (axis (i) proxy-based U06 rate
summary -- pure, additive, opt-in). No axis (ii)/(iii), no threshold, no
verdict, no real-world claim exists here -- see the module's own docstring.

Two kinds of fixtures are used deliberately:
  - real episodes (run_baseline_policy_episode/run_pure_fallback_episode on
    committed scenarios) for the "known hand-computed counts" and
    "no mutation" tests, so the numbers are anchored to real, already-
    committed system behavior;
  - directly-constructed minimal TransitionRecord/EpisodeRecord fixtures
    (via the _transition()/_episode() helpers below) for the boundary
    cases (safe_stop, world-inert, zero-denominator, mixed policy_status)
    -- summarize_episode_rates() is a PURE function over these dataclasses,
    so exercising its exact branch logic directly, independent of the real
    trust engine's incidental behavior on any particular scenario, is the
    precise way to test it.
"""

from __future__ import annotations

import inspect

from app.schemas.contracts import RLAction

from edge.eval.rl_baseline_eval import (
    SCENARIO_CLEAN_DEGRADATION,
    EpisodeRecord,
    TransitionRecord,
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)
from edge.eval.u06_rate_summary import EpisodeRateSummary, summarize_episode_rates


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
# Known hand-computed counts on a committed scenario
# ---------------------------------------------------------------------------


def test_known_hand_computed_counts_on_baseline_policy_clean_scenario():
    """BaselinePolicy requests reduce_weight on every step of this clean
    scenario (persistent "suspicious" trust banding in a short, cold-start
    episode -- see this increment's own sanity check), always overridden by
    the fallback gate to "continue" since BaselinePolicy is unvalidated.
    safety_status stays "nominal" throughout (no channel ever tracked as
    malicious). Hand-verified: 9 steps, all nominal, all reduce_weight
    requests -> false_isolation is 9/9. This is a faithful consequence of
    axis (i)'s own proxy definition on this specific scenario, not a
    real-world false-isolation claim -- see module docstring."""
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_episode_rates(record)

    assert summary.step_count == 9
    assert summary.false_isolation_denominator == 9
    assert summary.false_isolation_numerator == 9
    assert summary.false_isolation_rate == 1.0
    assert summary.missed_fault_denominator == 0
    assert summary.missed_fault_numerator == 0
    assert summary.missed_fault_rate is None
    assert summary.safe_stop_request_count == 0
    assert summary.policy_status_breakdown == {"unvalidated": 9}
    assert summary.world_inert_approved_action_count_in_false_isolation_denominator == 9
    assert summary.world_inert_approved_action_count_in_missed_fault_denominator == 0


def test_pure_fallback_episode_has_zero_false_isolation_denominator():
    """pure_fallback always requests None -> requested_action is not None
    is never true -> false-isolation denominator is structurally 0 on every
    scenario, regardless of safety_status."""
    record = run_pure_fallback_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_episode_rates(record)

    assert summary.false_isolation_denominator == 0
    assert summary.false_isolation_rate is None
    assert summary.missed_fault_denominator == 0
    assert summary.missed_fault_rate is None
    assert summary.policy_status_breakdown == {"unavailable": 9}


# ---------------------------------------------------------------------------
# Zero-denominator behavior: None, never 0%
# ---------------------------------------------------------------------------


def test_zero_denominator_on_both_axes_returns_none_not_zero():
    transitions = [
        _transition(safety_status="safe_stop_active", requested_action=RLAction.safe_stop.value)
    ]
    summary = summarize_episode_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 0
    assert summary.false_isolation_rate is None
    assert summary.missed_fault_denominator == 0
    assert summary.missed_fault_rate is None


# ---------------------------------------------------------------------------
# safe_stop requests: counted separately, never pollute the numerator
# ---------------------------------------------------------------------------


def test_safe_stop_requests_are_counted_separately_and_reduce_rate_toward_zero():
    """A policy that always safe-stops on nominal steps must show a
    DEFINED (not None) false-isolation rate of 0.0, with
    safe_stop_request_count reported alongside so the 0.0 is not read as
    "never false-isolated" without context -- see module docstring's
    NOT EXCLUDED, ONLY SEPARATELY REPORTED section."""
    transitions = [
        _transition(
            safety_status="nominal",
            requested_action=RLAction.safe_stop.value,
            approved_action=RLAction.safe_stop.value,
        )
        for _ in range(3)
    ]
    summary = summarize_episode_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 3
    assert summary.false_isolation_numerator == 0
    assert summary.false_isolation_rate == 0.0
    assert summary.safe_stop_request_count == 3


# ---------------------------------------------------------------------------
# world-inert approved actions: counted within the opportunity denominator
# ---------------------------------------------------------------------------


def test_world_inert_approved_action_is_counted_within_the_denominator():
    transitions = [
        _transition(
            safety_status="nominal",
            requested_action=RLAction.reduce_weight.value,
            approved_action=RLAction.continue_.value,  # fallback-overridden, world-inert
        )
    ]
    summary = summarize_episode_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 1
    assert summary.false_isolation_numerator == 1
    assert summary.world_inert_approved_action_count_in_false_isolation_denominator == 1


# ---------------------------------------------------------------------------
# fallback/unvalidated policy_status: NOT excluded, only broken out
# ---------------------------------------------------------------------------


def test_unvalidated_policy_status_steps_still_count_toward_the_rate():
    transitions = [
        _transition(
            safety_status="nominal",
            requested_action=RLAction.isolate.value,
            policy_status="unvalidated",
        ),
        _transition(
            safety_status="nominal",
            requested_action=RLAction.continue_.value,
            policy_status="validated",
        ),
    ]
    summary = summarize_episode_rates(_episode(transitions))

    assert summary.false_isolation_denominator == 2
    assert summary.false_isolation_numerator == 1
    assert summary.false_isolation_rate == 0.5
    assert summary.policy_status_breakdown == {"unvalidated": 1, "validated": 1}


# ---------------------------------------------------------------------------
# missed-fault numerator/denominator
# ---------------------------------------------------------------------------


def test_missed_fault_numerator_and_denominator():
    transitions = [
        _transition(safety_status="isolation_active", requested_action=RLAction.continue_.value),
        _transition(safety_status="isolation_active", requested_action=RLAction.isolate.value),
    ]
    summary = summarize_episode_rates(_episode(transitions))

    assert summary.missed_fault_denominator == 2
    assert summary.missed_fault_numerator == 1
    assert summary.missed_fault_rate == 0.5
    assert summary.false_isolation_denominator == 0  # neither step is "nominal"
    assert summary.false_isolation_rate is None


# ---------------------------------------------------------------------------
# Scenario identity preserved
# ---------------------------------------------------------------------------


def test_scenario_and_baseline_identity_are_preserved():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_episode_rates(record)
    assert summary.scenario_name == record.scenario_name
    assert summary.baseline_name == record.baseline_name
    assert summary.step_count == record.step_count
    assert summary.termination_cause == record.termination_cause


# ---------------------------------------------------------------------------
# No mutation of the input EpisodeRecord/transitions
# ---------------------------------------------------------------------------


def test_summarize_does_not_mutate_the_input_episode_record():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    transitions_before = record.transitions
    reward_before = record.cumulative_reward

    summarize_episode_rates(record)

    assert record.transitions is transitions_before
    assert record.cumulative_reward == reward_before
    # Frozen dataclasses guarantee this structurally, but assert explicitly
    # that summarize_episode_rates() returns a NEW object, not the input.
    summary = summarize_episode_rates(record)
    assert not isinstance(summary, EpisodeRecord)
    assert isinstance(summary, EpisodeRateSummary)


# ---------------------------------------------------------------------------
# Structural: axis (i) only -- no labels, no threshold, no verdict
# ---------------------------------------------------------------------------


def test_module_never_reads_injection_labels_or_widens_them():
    import edge.eval.u06_rate_summary as module

    source = inspect.getsource(module)
    assert "active_injection_labels" not in source
    assert "edge.injection" not in source
    assert "Label" not in source


def test_module_makes_no_threshold_verdict_or_real_world_claim():
    import edge.eval.u06_rate_summary as module

    source = inspect.getsource(module)
    lowered = source.lower()
    forbidden = (
        "acceptable rate",
        "acceptable threshold",
        "is validated",
        "is safe",
        "is accurate",
        "production-ready",
        "production ready",
        "real-world false-isolation rate",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_has_no_hardware_network_or_actuation_imports():
    import edge.eval.u06_rate_summary as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RelayController", "FakeActuator", "SelfHealOrchestrator", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()
