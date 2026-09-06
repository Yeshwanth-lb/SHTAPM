"""Tests for edge/eval/u06_tracker_agreement.py (axis (ii) coarse,
presence-only tracker-vs-injection agreement -- pure, additive, opt-in).
No channel matching, no axis (iii), no threshold, no verdict, no
real-world claim exists here -- see the module's own docstring.

Two kinds of fixtures are used deliberately (same convention as
edge/tests/test_u06_rate_summary.py):
  - real episodes (run_baseline_policy_episode/run_pure_fallback_episode on
    committed scenarios) for the "known hand-computed counts" and
    "no mutation" tests, anchored to real, already-committed behavior;
  - directly-constructed minimal TransitionRecord/EpisodeRecord fixtures
    (via the _transition()/_episode() helpers below) for the four-way
    classification, exclusion, and breakdown boundary cases --
    summarize_tracker_agreement() is a PURE function over these
    dataclasses, so exercising its exact branch logic directly is the
    precise way to test it.
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
from edge.eval.u06_tracker_agreement import (
    TrackerAgreementSummary,
    summarize_tracker_agreement,
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
# Four-way classification
# ---------------------------------------------------------------------------


def test_active_injection_with_isolation_active_is_agreement_active():
    transitions = [
        _transition(safety_status="isolation_active", active_injection_labels=("spike",))
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.total_observations == 1
    assert summary.agreement_active_count == 1
    assert summary.tracker_missed_injection_count == 0
    assert summary.agreement_nominal_count == 0
    assert summary.tracker_flagged_without_injection_count == 0


def test_active_injection_without_isolation_active_is_tracker_missed():
    transitions = [_transition(safety_status="nominal", active_injection_labels=("drift",))]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.tracker_missed_injection_count == 1
    assert summary.agreement_active_count == 0


def test_no_injection_with_nominal_status_is_agreement_nominal():
    transitions = [_transition(safety_status="nominal", active_injection_labels=())]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.agreement_nominal_count == 1
    assert summary.tracker_flagged_without_injection_count == 0


def test_no_injection_with_isolation_active_is_tracker_flagged_without_injection():
    transitions = [
        _transition(safety_status="isolation_active", active_injection_labels=())
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.tracker_flagged_without_injection_count == 1
    assert summary.agreement_nominal_count == 0


def test_four_way_classification_is_exhaustive_and_mutually_exclusive():
    transitions = [
        _transition(safety_status="isolation_active", active_injection_labels=("spike",)),
        _transition(safety_status="nominal", active_injection_labels=("drift",)),
        _transition(safety_status="nominal", active_injection_labels=()),
        _transition(safety_status="isolation_active", active_injection_labels=()),
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    total_classified = (
        summary.agreement_active_count
        + summary.agreement_nominal_count
        + summary.tracker_missed_injection_count
        + summary.tracker_flagged_without_injection_count
    )
    assert total_classified == summary.total_observations == 4


# ---------------------------------------------------------------------------
# Exclusion: transition_consumed=False (safe_stop no-op steps)
# ---------------------------------------------------------------------------


def test_safe_stop_no_op_transitions_are_excluded():
    transitions = [
        _transition(safety_status="nominal", active_injection_labels=(), transition_consumed=True),
        _transition(
            safety_status="nominal",
            active_injection_labels=(),
            transition_consumed=False,
            safe_stop_terminated_without_transition=True,
            requested_action=RLAction.safe_stop.value,
            approved_action=RLAction.safe_stop.value,
        ),
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.total_observations == 1
    assert summary.agreement_nominal_count == 1


def test_duplicated_sample_seq_on_excluded_safe_stop_step_does_not_double_count():
    """A real step and a subsequent safe_stop no-op step can expose the
    SAME sample_seq (see edge/rl/environment.py's own documented behavior)
    -- since active_injection_labels/safety_status would be identical for
    both, including the no-op step would double-count one observation as
    two. Excluding transition_consumed=False steps prevents this without
    needing an explicit sample_seq deduplication pass (deliberately
    deferred -- see module docstring)."""
    transitions = [
        _transition(
            safety_status="isolation_active",
            active_injection_labels=("spike",),
            transition_consumed=True,
        ),
        # Same ground truth/tracker state repeated, as a real safe_stop
        # no-op step would expose (same underlying frame, no new outcome).
        _transition(
            safety_status="isolation_active",
            active_injection_labels=("spike",),
            transition_consumed=False,
            safe_stop_terminated_without_transition=True,
            requested_action=RLAction.safe_stop.value,
            approved_action=RLAction.safe_stop.value,
        ),
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.total_observations == 1
    assert summary.agreement_active_count == 1


# ---------------------------------------------------------------------------
# Per-injection-type breakdown
# ---------------------------------------------------------------------------


def test_per_injection_type_breakdown_is_scoped_to_that_type():
    transitions = [
        _transition(safety_status="isolation_active", active_injection_labels=("spike",)),
        _transition(safety_status="nominal", active_injection_labels=("spike",)),
        _transition(safety_status="isolation_active", active_injection_labels=("drift",)),
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    spike = summary.per_injection_type["spike"]
    assert spike.observation_count == 2
    assert spike.agreement_active_count == 1
    assert spike.tracker_missed_count == 1
    assert spike.agreement_rate == 0.5

    drift = summary.per_injection_type["drift"]
    assert drift.observation_count == 1
    assert drift.agreement_active_count == 1
    assert drift.tracker_missed_count == 0
    assert drift.agreement_rate == 1.0


def test_multi_injection_observation_is_attributed_to_each_active_type():
    """An observation naming more than one active injection type
    contributes to EACH type's own breakdown -- see module docstring's
    PER-INJECTION-TYPE ATTRIBUTION section. Per-type counts can therefore
    sum to more than total_observations."""
    transitions = [
        _transition(
            safety_status="isolation_active", active_injection_labels=("spike", "drift")
        )
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.total_observations == 1
    assert summary.per_injection_type["spike"].observation_count == 1
    assert summary.per_injection_type["drift"].observation_count == 1
    assert summary.per_injection_type["spike"].agreement_active_count == 1
    assert summary.per_injection_type["drift"].agreement_active_count == 1


def test_no_injection_types_pooled_together():
    """Two distinct injection types must never be merged into one pooled
    breakdown -- each keeps its own count/rate."""
    transitions = [
        _transition(safety_status="isolation_active", active_injection_labels=("spike",)),
        _transition(safety_status="nominal", active_injection_labels=("adaptive_stealth_fdi",)),
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert set(summary.per_injection_type.keys()) == {"spike", "adaptive_stealth_fdi"}
    assert summary.per_injection_type["spike"].agreement_rate == 1.0
    assert summary.per_injection_type["adaptive_stealth_fdi"].agreement_rate == 0.0


# ---------------------------------------------------------------------------
# Clean / no-injection breakdown
# ---------------------------------------------------------------------------


def test_no_injection_breakdown_is_reported_separately():
    transitions = [
        _transition(safety_status="nominal", active_injection_labels=()),
        _transition(safety_status="isolation_active", active_injection_labels=()),
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.no_injection.observation_count == 2
    assert summary.no_injection.agreement_nominal_count == 1
    assert summary.no_injection.tracker_flagged_without_injection_count == 1
    assert summary.no_injection.agreement_rate == 0.5
    assert summary.per_injection_type == {}


# ---------------------------------------------------------------------------
# Zero-observation / zero-denominator behavior: None, never 0%
# ---------------------------------------------------------------------------


def test_zero_observations_returns_none_agreement_rate():
    transitions = [
        _transition(transition_consumed=False, safe_stop_terminated_without_transition=True)
    ]
    summary = summarize_tracker_agreement(_episode(transitions))

    assert summary.total_observations == 0
    assert summary.agreement_rate is None
    assert summary.no_injection.observation_count == 0
    assert summary.no_injection.agreement_rate is None


# ---------------------------------------------------------------------------
# Known hand-computed counts on committed scenarios
# ---------------------------------------------------------------------------


def test_known_counts_on_injected_current_spike_scenario():
    """Empirically verified (this increment's own sanity check): the
    tracker never reaches isolation_active during this scenario's 5-step
    spike window on `current` -- a diagnostic observation about THIS
    pipeline/scenario combination, not a real-world detector-accuracy
    claim (see module docstring)."""
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    summary = summarize_tracker_agreement(record)

    assert summary.total_observations == 9
    assert summary.per_injection_type["spike"].observation_count == 5
    assert summary.no_injection.observation_count == 4


def test_known_counts_on_clean_degradation_scenario():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_tracker_agreement(record)

    assert summary.total_observations == 9
    assert summary.per_injection_type == {}
    assert summary.no_injection.observation_count == 9


# ---------------------------------------------------------------------------
# Scenario identity preservation
# ---------------------------------------------------------------------------


def test_scenario_and_baseline_identity_are_preserved():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    summary = summarize_tracker_agreement(record)
    assert summary.scenario_name == record.scenario_name
    assert summary.baseline_name == record.baseline_name


# ---------------------------------------------------------------------------
# No mutation of the input EpisodeRecord/transitions
# ---------------------------------------------------------------------------


def test_summarize_does_not_mutate_the_input_episode_record():
    record = run_pure_fallback_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    transitions_before = record.transitions
    reward_before = record.cumulative_reward

    summarize_tracker_agreement(record)

    assert record.transitions is transitions_before
    assert record.cumulative_reward == reward_before

    summary = summarize_tracker_agreement(record)
    assert not isinstance(summary, EpisodeRecord)
    assert isinstance(summary, TrackerAgreementSummary)


# ---------------------------------------------------------------------------
# Structural: coarse axis (ii) only -- no channel matching, no threshold
# ---------------------------------------------------------------------------


def test_module_does_not_widen_labels_or_add_channel_matching():
    """The module docstring legitimately DISCUSSES tracked-channel data and
    channel-matching as an explicitly-out-of-scope future extension (naming
    the relevant field to explain why it is unused) -- what must never
    exist is any actual field or functional use of that data, checked
    directly against the dataclasses' own field sets."""
    import dataclasses

    from edge.eval.u06_tracker_agreement import InjectionTypeBreakdown, TrackerAgreementSummary

    summary_fields = {f.name for f in dataclasses.fields(TrackerAgreementSummary)}
    breakdown_fields = {f.name for f in dataclasses.fields(InjectionTypeBreakdown)}
    for fields in (summary_fields, breakdown_fields):
        assert not any("channel" in name for name in fields)


def test_module_makes_no_threshold_verdict_or_real_world_claim():
    import edge.eval.u06_tracker_agreement as module

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
        "proves detector failure",
        "is a detector failure",
        "real-world agreement rate",
        "real-world accuracy",
    )
    for phrase in forbidden:
        assert phrase not in lowered


def test_module_has_no_hardware_network_or_actuation_imports():
    import edge.eval.u06_tracker_agreement as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RelayController", "FakeActuator", "SelfHealOrchestrator", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()
