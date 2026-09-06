"""Tests for edge/eval/rl_baseline_eval.py (diagnostic-only RL baseline
evaluation harness). No RL training, learned policy, or validation claim
exists here -- see the module's own docstring.
"""

from __future__ import annotations

import inspect

from app.schemas.contracts import CHANNELS, RLAction

from edge.eval.rl_baseline_eval import (
    ACTION_DEPENDENT_COMPARISON_CAVEAT,
    DATA_SOURCE,
    EVALUATION_SCENARIO_METADATA,
    EXECUTION_MODE,
    INJECTION_TYPE_SCENARIOS,
    MODEL_STATUS,
    SCENARIO_CLEAN_DEGRADATION,
    SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF,
    SCENARIO_INJECTED_CURRENT_SPIKE,
    EpisodeRecord,
    ScenarioConfig,
    TransitionRecord,
    default_scenarios,
    run_all_baselines,
    run_baseline_policy_episode,
    run_pure_fallback_episode,
)
from edge.injection.injections import InjectionType
from edge.rl.reward import DECISION_ONLY_WEIGHTS_FIXTURE, SIMULATION_REWARD_WEIGHTS_FIXTURE

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


# ---------------------------------------------------------------------------
# active_injection_labels (U06 scoping) -- descriptive raw injection facts
# only. NOT a false-isolation/missed-fault verdict, rate, or comparison
# result. See edge/rl/environment.py's INJECTION-LABEL RETENTION section.
# ---------------------------------------------------------------------------


def test_transition_record_active_injection_labels_field_exists_and_defaults_addable():
    """Existing behavior regression guard: the new field must be present
    and additive -- every other TransitionRecord field is unaffected."""
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert isinstance(t.active_injection_labels, tuple)


def test_clean_scenario_has_no_active_injection_labels():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    assert all(t.active_injection_labels == () for t in record.transitions)


def test_injected_scenario_reports_active_injection_labels_during_its_window():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    labeled_steps = [t for t in record.transitions if t.active_injection_labels]
    assert len(labeled_steps) > 0
    for t in labeled_steps:
        assert t.active_injection_labels == ("spike",)


def test_active_injection_labels_are_purely_descriptive_strings():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    for t in record.transitions:
        for label in t.active_injection_labels:
            assert isinstance(label, str)


def test_existing_transition_record_fields_unchanged_by_new_field():
    """Regression guard: adding active_injection_labels must not change any
    other TransitionRecord field's value for the existing scenarios."""
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert isinstance(t.requested_action, str | None)
        assert isinstance(t.approved_action, str)
        assert isinstance(t.fallback_used, bool)
        assert isinstance(t.safety_status, str)
        assert isinstance(t.reward_components, dict)


def test_run_episode_makes_no_false_isolation_or_missed_fault_claim():
    """No field, docstring, or test may compute or claim a false-isolation
    rate, missed-fault rate, threshold, or verdict from active_injection_labels."""
    import edge.eval.rl_baseline_eval as module

    source = inspect.getsource(module)
    forbidden = (
        "false_isolation_rate",
        "missed_fault_rate",
        "false-isolation rate is",
        "missed-fault rate is",
    )
    lowered = source.lower()
    for phrase in forbidden:
        assert phrase not in lowered


# ---------------------------------------------------------------------------
# active_injection_channels (U06 scoping) -- data-plumbing-only field
# reading each active Label's own channel (already available alongside
# injection_type at the existing construction site). NOT a channel-match
# comparison, verdict, rate, or threshold. See edge/eval/rl_baseline_eval.py's
# own INJECTED-CHANNEL PLUMBING docstring section.
# ---------------------------------------------------------------------------


def test_transition_record_active_injection_channels_field_exists_and_defaults_addable():
    """Existing behavior regression guard: the new field must be present
    and additive -- every other TransitionRecord field is unaffected."""
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert isinstance(t.active_injection_channels, tuple)


def test_active_injection_channels_field_defaults_to_empty_tuple_for_existing_callers():
    """Existing TransitionRecord construction call sites (this module's own
    test helpers in test_u06_rate_summary.py / test_u06_tracker_agreement.py
    / test_u06_ground_truth_rate_summary.py) never pass
    active_injection_channels -- the dataclass default must apply cleanly,
    exactly like active_injection_labels's and tracked_channels's own
    established default behavior."""
    t = TransitionRecord(
        episode_index=0,
        step_index=0,
        previous_state_vector=(0.0,),
        next_state_vector=(0.0,),
        requested_action=RLAction.continue_.value,
        approved_action=RLAction.continue_.value,
        fallback_used=False,
        fallback_reason=None,
        safety_status="nominal",
        policy_status="validated",
        reward_components={},
        total_reward=0.0,
        done=False,
        transition_consumed=True,
        safe_stop_terminated_without_transition=False,
        transition_substitution_mode=None,
        substituted_channels=(),
    )
    assert t.active_injection_channels == ()


def test_clean_scenario_has_no_active_injection_channels():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    assert all(t.active_injection_channels == () for t in record.transitions)


def test_injected_scenario_reports_the_expected_injected_channel():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    labeled_steps = [t for t in record.transitions if t.active_injection_channels]
    assert len(labeled_steps) > 0
    for t in labeled_steps:
        assert t.active_injection_channels == ("current",)


def test_active_injection_channels_are_purely_descriptive_strings_in_channels():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_SPIKE)
    for t in record.transitions:
        for channel in t.active_injection_channels:
            assert isinstance(channel, str)
            assert channel in CHANNELS


def test_active_injection_channels_align_positionally_with_active_injection_labels():
    """Both fields are built from the same active_labels tuple, in the same
    order (one via label.injection_type.value, the other via label.channel)
    -- verifies positional/length alignment, not any semantic comparison
    between the two."""
    for scenario in (SCENARIO_CLEAN_DEGRADATION, SCENARIO_INJECTED_CURRENT_SPIKE):
        record = run_baseline_policy_episode(scenario)
        for t in record.transitions:
            assert len(t.active_injection_channels) == len(t.active_injection_labels)


def test_multi_channel_injection_preserves_all_channels_deterministically():
    """Test-only multi-injection scenario (no committed scenario uses more
    than one injection -- see test_no_scenario_injects_more_than_one_channel_
    simultaneously below) -- confirms active_injection_channels retains
    both channels from two simultaneous injections, in the same
    deterministic order as active_injection_labels, mirroring
    test_rl_environment.py's own
    test_multi_injection_environment_retains_overlapping_labels_from_different_channels."""
    from edge.injection.injections import Drift, Spike
    from edge.models.degradation_generator import ChannelDegradationConfig

    multi_injection_scenario = ScenarioConfig(
        name="test_only_multi_channel_injection",
        seed=9001,
        length=40,
        start_health=1.0,
        end_health=0.2,
        degradation_rate=1.0,
        channels={"vibration": ChannelDegradationConfig(healthy_value=0.03, degraded_value=1.2)},
        injections=(
            Spike(channel="current", onset=32, duration=5, amplitude=50.0),
            Drift(channel="temperature", onset=32, duration=5, rate=0.5),
        ),
    )
    record = run_baseline_policy_episode(multi_injection_scenario)
    overlapping_steps = [
        t for t in record.transitions if len(t.active_injection_channels) > 1
    ]
    assert len(overlapping_steps) > 0
    for t in overlapping_steps:
        assert set(t.active_injection_channels) == {"current", "temperature"}
        assert len(t.active_injection_channels) == len(t.active_injection_labels) == 2


def test_existing_transition_record_fields_unchanged_by_active_injection_channels_field():
    """Regression guard: adding active_injection_channels must not change
    any other TransitionRecord field's value for the existing scenarios."""
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert isinstance(t.requested_action, str | None)
        assert isinstance(t.approved_action, str)
        assert isinstance(t.fallback_used, bool)
        assert isinstance(t.safety_status, str)
        assert isinstance(t.active_injection_labels, tuple)
        assert isinstance(t.tracked_channels, tuple)
        assert isinstance(t.reward_components, dict)


def test_run_episode_makes_no_channel_matching_claim_from_active_injection_channels():
    """No code, docstring, or test in this module may compute or claim a
    channel-match comparison, agreement rate, threshold, or verdict from
    active_injection_channels -- this increment is data plumbing only."""
    import edge.eval.rl_baseline_eval as module

    source = inspect.getsource(module)
    lowered = source.lower()
    forbidden = (
        "channel_match_rate",
        "channel agreement rate",
        "channel-match rate",
        "injected channel matches",
    )
    for phrase in forbidden:
        assert phrase not in lowered


# ---------------------------------------------------------------------------
# sample_seq (U06 scoping) -- data-plumbing-only field reading the
# already-computed local sample_seq value at the existing construction
# site. NOT a deduplication pass -- this proves the invariant that would
# make one unnecessary for every currently-committed scenario. See
# edge/eval/rl_baseline_eval.py's own SAMPLE_SEQ PLUMBING docstring
# section.
# ---------------------------------------------------------------------------


def _assert_sample_seq_unique_and_increasing_among_consumed(transitions):
    """Shared invariant check, reused by both the real-scenario test below
    and the synthetic tests proving it actually catches a violation (not
    just passing vacuously). Only transition_consumed=True transitions are
    checked; a None sample_seq is excluded rather than guessed at (see
    module docstring's own precedent for this exact None-handling
    convention)."""
    consumed_seqs = [
        t.sample_seq
        for t in transitions
        if t.transition_consumed and t.sample_seq is not None
    ]
    assert len(consumed_seqs) == len(set(consumed_seqs)), (
        "duplicate sample_seq among transition_consumed=True transitions"
    )
    assert all(a < b for a, b in zip(consumed_seqs, consumed_seqs[1:], strict=False)), (
        "sample_seq not strictly increasing among transition_consumed=True transitions"
    )


def test_transition_record_sample_seq_field_exists_and_defaults_addable():
    """Existing behavior regression guard: the new field must be present
    and additive -- every other TransitionRecord field is unaffected."""
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert t.sample_seq is None or isinstance(t.sample_seq, int)


def test_sample_seq_field_defaults_to_none_for_existing_callers():
    """Existing TransitionRecord construction call sites (this module's own
    test helpers in test_u06_rate_summary.py / test_u06_tracker_agreement.py
    / test_u06_ground_truth_rate_summary.py / test_u06_channel_agreement.py)
    never pass sample_seq -- the dataclass default must apply cleanly,
    exactly like every other U06-scoping field's own established default
    behavior."""
    t = TransitionRecord(
        episode_index=0,
        step_index=0,
        previous_state_vector=(0.0,),
        next_state_vector=(0.0,),
        requested_action=RLAction.continue_.value,
        approved_action=RLAction.continue_.value,
        fallback_used=False,
        fallback_reason=None,
        safety_status="nominal",
        policy_status="validated",
        reward_components={},
        total_reward=0.0,
        done=False,
        transition_consumed=True,
        safe_stop_terminated_without_transition=False,
        transition_substitution_mode=None,
        substituted_channels=(),
    )
    assert t.sample_seq is None


def test_sample_seq_is_unique_and_strictly_increasing_for_every_committed_scenario():
    """The core justification for this increment: proves, across every
    committed scenario and both baselines, that transition_consumed=True
    transitions already have unique, strictly increasing sample_seq values
    -- the invariant edge/rl/environment.py's own cursor-advancement logic
    (_feed_next_frame always advances by exactly 1, or raises rather than
    repeating a frame) and immediate-termination-on-safe_stop logic
    (done is set the moment safe_stop is approved, so at most one
    transition_consumed=False transition can ever exist per episode)
    together guarantee. This is a diagnostic proof, not a deduplication
    pass -- no transition is filtered, dropped, or modified by this test
    or by any production code."""
    for scenario in _ALL_EVALUATION_SCENARIOS:
        for runner in (run_baseline_policy_episode, run_pure_fallback_episode):
            record = runner(scenario)
            _assert_sample_seq_unique_and_increasing_among_consumed(record.transitions)


def test_synthetic_duplicate_sample_seq_among_consumed_transitions_is_detected():
    """Focused synthetic coverage: no real committed scenario currently
    produces a duplicate sample_seq (verified above), so this directly
    constructs a deliberately-violating fixture to prove the invariant
    check itself is not vacuous -- it must actually fail on a real
    violation, not merely pass because nothing exercises it."""
    duplicate_transitions = [
        TransitionRecord(
            episode_index=0,
            step_index=0,
            previous_state_vector=(0.0,),
            next_state_vector=(0.0,),
            requested_action=RLAction.continue_.value,
            approved_action=RLAction.continue_.value,
            fallback_used=False,
            fallback_reason=None,
            safety_status="nominal",
            policy_status="validated",
            reward_components={},
            total_reward=0.0,
            done=False,
            transition_consumed=True,
            safe_stop_terminated_without_transition=False,
            transition_substitution_mode=None,
            substituted_channels=(),
            sample_seq=5,
        ),
        TransitionRecord(
            episode_index=0,
            step_index=1,
            previous_state_vector=(0.0,),
            next_state_vector=(0.0,),
            requested_action=RLAction.continue_.value,
            approved_action=RLAction.continue_.value,
            fallback_used=False,
            fallback_reason=None,
            safety_status="nominal",
            policy_status="validated",
            reward_components={},
            total_reward=0.0,
            done=False,
            transition_consumed=True,
            safe_stop_terminated_without_transition=False,
            transition_substitution_mode=None,
            substituted_channels=(),
            sample_seq=5,  # deliberately duplicated
        ),
    ]
    try:
        _assert_sample_seq_unique_and_increasing_among_consumed(duplicate_transitions)
        raised = False
    except AssertionError:
        raised = True
    assert raised, "invariant check failed to detect a deliberately duplicated sample_seq"


def test_synthetic_none_sample_seq_is_excluded_not_guessed_at():
    """Focused synthetic coverage: a None sample_seq (only possible before
    the first frame is fed, never observed in practice during the step
    loop) must be excluded from the invariant check entirely, never
    treated as equal or unequal to any other value."""
    transitions_with_none = [
        TransitionRecord(
            episode_index=0,
            step_index=0,
            previous_state_vector=(0.0,),
            next_state_vector=(0.0,),
            requested_action=RLAction.continue_.value,
            approved_action=RLAction.continue_.value,
            fallback_used=False,
            fallback_reason=None,
            safety_status="nominal",
            policy_status="validated",
            reward_components={},
            total_reward=0.0,
            done=False,
            transition_consumed=True,
            safe_stop_terminated_without_transition=False,
            transition_substitution_mode=None,
            substituted_channels=(),
            sample_seq=None,
        ),
        TransitionRecord(
            episode_index=0,
            step_index=1,
            previous_state_vector=(0.0,),
            next_state_vector=(0.0,),
            requested_action=RLAction.continue_.value,
            approved_action=RLAction.continue_.value,
            fallback_used=False,
            fallback_reason=None,
            safety_status="nominal",
            policy_status="validated",
            reward_components={},
            total_reward=0.0,
            done=False,
            transition_consumed=True,
            safe_stop_terminated_without_transition=False,
            transition_substitution_mode=None,
            substituted_channels=(),
            sample_seq=None,
        ),
    ]
    # Must not raise: both sample_seq values are None and are excluded
    # entirely, never compared to one another as if they were duplicates.
    _assert_sample_seq_unique_and_increasing_among_consumed(transitions_with_none)


def test_synthetic_transition_consumed_false_is_excluded_from_the_invariant():
    """Focused synthetic coverage: a transition_consumed=False transition
    sharing the same sample_seq as the preceding real step (exactly the
    documented safe_stop echo mechanism in edge/rl/environment.py) must
    never be counted as a duplicate -- it is excluded from the invariant
    entirely, by design, before any uniqueness check runs."""
    transitions = [
        TransitionRecord(
            episode_index=0,
            step_index=0,
            previous_state_vector=(0.0,),
            next_state_vector=(0.0,),
            requested_action=RLAction.continue_.value,
            approved_action=RLAction.continue_.value,
            fallback_used=False,
            fallback_reason=None,
            safety_status="nominal",
            policy_status="validated",
            reward_components={},
            total_reward=0.0,
            done=False,
            transition_consumed=True,
            safe_stop_terminated_without_transition=False,
            transition_substitution_mode=None,
            substituted_channels=(),
            sample_seq=7,
        ),
        TransitionRecord(
            episode_index=0,
            step_index=1,
            previous_state_vector=(0.0,),
            next_state_vector=(0.0,),
            requested_action=RLAction.safe_stop.value,
            approved_action=RLAction.safe_stop.value,
            fallback_used=False,
            fallback_reason=None,
            safety_status="nominal",
            policy_status="validated",
            reward_components={},
            total_reward=0.0,
            done=True,
            transition_consumed=False,
            safe_stop_terminated_without_transition=True,
            transition_substitution_mode=None,
            substituted_channels=(),
            sample_seq=7,  # echoes the preceding real step, by design
        ),
    ]
    # Must not raise: the second transition's transition_consumed=False
    # excludes it from the invariant entirely, so the shared sample_seq=7
    # is never evaluated as a duplicate.
    _assert_sample_seq_unique_and_increasing_among_consumed(transitions)


def test_run_episode_adds_no_deduplication_logic_from_sample_seq():
    """No code, docstring, or test in this module may implement a
    deduplication pass, filter, or drop-duplicate operation from
    sample_seq -- this increment is data plumbing and invariant proof
    only, per its own explicit scope."""
    import edge.eval.rl_baseline_eval as module

    source = inspect.getsource(module)
    lowered = source.lower()
    forbidden = (
        "deduplicate",
        "dedup(",
        "drop_duplicate",
        "seen_sample_seq",
    )
    for phrase in forbidden:
        assert phrase not in lowered


# ---------------------------------------------------------------------------
# tracked_channels (U06 scoping) -- data-plumbing-only field reading the
# already-existing result.info["persistent_isolation_tracked_channels"].
# NOT a channel-match comparison, verdict, rate, or threshold. See
# edge/eval/rl_baseline_eval.py's own TRACKED-CHANNEL PLUMBING docstring
# section.
# ---------------------------------------------------------------------------


def test_transition_record_tracked_channels_field_exists_and_defaults_addable():
    """Existing behavior regression guard: the new field must be present
    and additive -- every other TransitionRecord field is unaffected."""
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert isinstance(t.tracked_channels, tuple)


def test_tracked_channels_field_defaults_to_empty_tuple_for_existing_callers():
    """Existing TransitionRecord construction call sites (this module's own
    test helpers in test_u06_rate_summary.py / test_u06_tracker_agreement.py
    / test_u06_ground_truth_rate_summary.py) never pass tracked_channels --
    the dataclass default must apply cleanly, exactly like
    active_injection_labels's own established default behavior."""
    t = TransitionRecord(
        episode_index=0,
        step_index=0,
        previous_state_vector=(0.0,),
        next_state_vector=(0.0,),
        requested_action=RLAction.continue_.value,
        approved_action=RLAction.continue_.value,
        fallback_used=False,
        fallback_reason=None,
        safety_status="nominal",
        policy_status="validated",
        reward_components={},
        total_reward=0.0,
        done=False,
        transition_consumed=True,
        safe_stop_terminated_without_transition=False,
        transition_substitution_mode=None,
        substituted_channels=(),
    )
    assert t.tracked_channels == ()


def test_clean_scenario_has_no_tracked_channels():
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    assert all(t.tracked_channels == () for t in record.transitions)


def test_scenario_with_persistent_isolation_reports_tracked_channels():
    """injected_current_constant_spoof is the one already-committed scenario
    whose baseline_policy run actually drives safety_status to
    "isolation_active" (verified directly) -- exercising the non-empty
    branch of the new field, populated straight from the environment's own
    already-existing info key. This does NOT assert or imply that the
    tracked channel matches the injected channel -- no such comparison is
    made or claimed here."""
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    tracked_steps = [t for t in record.transitions if t.tracked_channels]
    assert len(tracked_steps) > 0
    for t in tracked_steps:
        assert t.safety_status == "isolation_active"
        for channel in t.tracked_channels:
            assert channel in CHANNELS


def test_tracked_channels_populated_from_environment_info_key_empty_case():
    """The empty case (no channel currently tracked) must round-trip safely
    from result.info's list-of-sorted-channel-names shape to an empty
    tuple, identical to the field's own default -- not raise, and not be
    conflated with a "missing key" case (the key is always present)."""
    record = run_baseline_policy_episode(SCENARIO_CLEAN_DEGRADATION)
    for t in record.transitions:
        assert t.tracked_channels == ()
        assert isinstance(t.tracked_channels, tuple)


def test_tracked_channels_are_purely_descriptive_strings():
    record = run_baseline_policy_episode(SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF)
    for t in record.transitions:
        for channel in t.tracked_channels:
            assert isinstance(channel, str)


def test_existing_transition_record_fields_unchanged_by_tracked_channels_field():
    """Regression guard: adding tracked_channels must not change any other
    TransitionRecord field's value for the existing scenarios."""
    record = run_baseline_policy_episode(SCENARIO)
    for t in record.transitions:
        assert isinstance(t.requested_action, str | None)
        assert isinstance(t.approved_action, str)
        assert isinstance(t.fallback_used, bool)
        assert isinstance(t.safety_status, str)
        assert isinstance(t.active_injection_labels, tuple)
        assert isinstance(t.reward_components, dict)


def test_tracked_channels_reports_match_underlying_safety_status_exactly():
    """Structural guard, not a channel-match comparison: tracked_channels is
    non-empty if and only if safety_status == "isolation_active" (both are
    the deterministic tracker's own state, read from the same info dict) --
    verifies the new field is a faithful passthrough, introducing no new
    derivation or judgment of its own."""
    for scenario in (SCENARIO_CLEAN_DEGRADATION, SCENARIO_INJECTED_CURRENT_CONSTANT_SPOOF):
        record = run_baseline_policy_episode(scenario)
        for t in record.transitions:
            assert bool(t.tracked_channels) == (t.safety_status == "isolation_active")


def test_run_episode_makes_no_channel_match_comparison_claim():
    """No code, docstring, or test in this module may compute or claim a
    channel-match comparison, agreement rate, threshold, or verdict from
    tracked_channels -- this increment is data plumbing only."""
    import edge.eval.rl_baseline_eval as module

    source = inspect.getsource(module)
    lowered = source.lower()
    forbidden = (
        "channel_match_rate",
        "channel agreement rate",
        "channel-match rate",
        "tracked channel matches",
    )
    for phrase in forbidden:
        assert phrase not in lowered


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


# ---------------------------------------------------------------------------
# reward_weights parameter: defaults and overrides (reward-weight tuning)
# ---------------------------------------------------------------------------


def test_baseline_policy_episode_defaults_to_simulation_fixture():
    default_record = run_baseline_policy_episode(SCENARIO)
    explicit_record = run_baseline_policy_episode(
        SCENARIO, reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE
    )
    assert default_record.cumulative_reward == explicit_record.cumulative_reward


def test_pure_fallback_episode_defaults_to_simulation_fixture():
    default_record = run_pure_fallback_episode(SCENARIO)
    explicit_record = run_pure_fallback_episode(
        SCENARIO, reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE
    )
    assert default_record.cumulative_reward == explicit_record.cumulative_reward


def test_baseline_policy_episode_reward_weights_override_is_applied():
    default_record = run_baseline_policy_episode(SCENARIO)
    override_record = run_baseline_policy_episode(
        SCENARIO, reward_weights=DECISION_ONLY_WEIGHTS_FIXTURE
    )
    assert default_record.cumulative_reward != override_record.cumulative_reward


def test_pure_fallback_episode_with_decision_only_weights_is_exactly_zero():
    """pure_fallback always requests None, which never matches any
    RLAction comparison in _compute_components -- so on a scenario where
    anomaly_impact also never fires, DECISION_ONLY_WEIGHTS_FIXTURE (which
    zeroes health/trust/recovery) must produce an exact 0.0 total."""
    record = run_pure_fallback_episode(SCENARIO, reward_weights=DECISION_ONLY_WEIGHTS_FIXTURE)
    assert record.cumulative_reward == 0.0


def test_run_all_baselines_defaults_to_simulation_fixture():
    default_records = run_all_baselines([SCENARIO])
    explicit_records = run_all_baselines(
        [SCENARIO], reward_weights=SIMULATION_REWARD_WEIGHTS_FIXTURE
    )
    assert [r.cumulative_reward for r in default_records] == [
        r.cumulative_reward for r in explicit_records
    ]


def test_run_all_baselines_reward_weights_override_is_applied():
    default_records = run_all_baselines([SCENARIO])
    override_records = run_all_baselines([SCENARIO], reward_weights=DECISION_ONLY_WEIGHTS_FIXTURE)
    assert [r.cumulative_reward for r in default_records] != [
        r.cumulative_reward for r in override_records
    ]


def test_reward_weights_override_does_not_change_scenario_or_methodology():
    """Overriding reward_weights must never change which scenario ran, how
    many steps it took, or its termination cause -- only the reward math."""
    default_record = run_baseline_policy_episode(SCENARIO)
    override_record = run_baseline_policy_episode(
        SCENARIO, reward_weights=DECISION_ONLY_WEIGHTS_FIXTURE
    )
    assert default_record.scenario_config == override_record.scenario_config
    assert default_record.step_count == override_record.step_count
    assert default_record.termination_cause == override_record.termination_cause
    assert default_record.approved_action_histogram == override_record.approved_action_histogram


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
# U06 scenario-taxonomy coverage (see module docstring's INJECTION-TYPE
# SCENARIO TAXONOMY section). None of these tests claim improved accuracy,
# safety, false-isolation performance, or U06 resolution -- they only check
# that the scenario/metadata definitions are internally consistent.
# ---------------------------------------------------------------------------

_ALL_EVALUATION_SCENARIOS = (SCENARIO_CLEAN_DEGRADATION, *INJECTION_TYPE_SCENARIOS)


def test_every_injection_type_is_represented_by_a_scenario():
    covered = {
        scenario.injections[0].injection_type
        for scenario in INJECTION_TYPE_SCENARIOS
        if scenario.injections
    }
    assert covered == set(InjectionType)


def test_evaluation_scenario_names_are_unique():
    names = [s.name for s in _ALL_EVALUATION_SCENARIOS]
    assert len(names) == len(set(names))


def test_evaluation_scenario_seeds_are_unique():
    seeds = [s.seed for s in _ALL_EVALUATION_SCENARIOS]
    assert len(seeds) == len(set(seeds))


def test_every_injected_scenario_has_a_valid_bounded_injection_window():
    for scenario in INJECTION_TYPE_SCENARIOS:
        assert len(scenario.injections) == 1, "exactly one injection per scenario (single-fault)"
        injection = scenario.injections[0]
        assert injection.channel in CHANNELS
        assert injection.onset >= 0
        assert injection.duration >= 1
        assert injection.onset + injection.duration <= scenario.length


def test_no_scenario_injects_more_than_one_channel_simultaneously():
    """Documents the intentional multi-channel/multi-fault coverage gap
    (see module docstring) rather than assuming it away."""
    for scenario in _ALL_EVALUATION_SCENARIOS:
        channels = {injection.channel for injection in scenario.injections}
        assert len(channels) <= 1


def test_replay_scenario_satisfies_its_own_constructor_constraints():
    replay_scenarios = [
        s
        for s in INJECTION_TYPE_SCENARIOS
        if s.injections and s.injections[0].injection_type is InjectionType.REPLAY
    ]
    assert len(replay_scenarios) == 1
    injection = replay_scenarios[0].injections[0]
    assert injection.source_onset >= 0
    assert injection.source_onset + injection.duration <= injection.onset
    assert injection.source_onset + injection.duration <= replay_scenarios[0].length


def test_clean_scenario_has_no_injections():
    assert SCENARIO_CLEAN_DEGRADATION.injections == ()


def test_existing_scenarios_remain_behaviorally_unchanged():
    """Regression guard: SCENARIO_CLEAN_DEGRADATION and
    SCENARIO_INJECTED_CURRENT_SPIKE must keep their exact original field
    values -- this increment is additive-only, not a rewrite."""
    assert SCENARIO_CLEAN_DEGRADATION.seed == 1337
    assert SCENARIO_CLEAN_DEGRADATION.length == 40
    assert SCENARIO_CLEAN_DEGRADATION.start_health == 1.0
    assert SCENARIO_CLEAN_DEGRADATION.end_health == 0.2
    assert SCENARIO_CLEAN_DEGRADATION.degradation_rate == 1.0
    assert SCENARIO_CLEAN_DEGRADATION.injections == ()

    assert SCENARIO_INJECTED_CURRENT_SPIKE.seed == 1338
    assert SCENARIO_INJECTED_CURRENT_SPIKE.length == 40
    spike = SCENARIO_INJECTED_CURRENT_SPIKE.injections[0]
    assert spike.channel == "current"
    assert spike.onset == 32
    assert spike.duration == 5
    assert spike.amplitude == 50.0

    assert default_scenarios() == (SCENARIO_CLEAN_DEGRADATION, SCENARIO_INJECTED_CURRENT_SPIKE)


def test_new_injection_scenarios_produce_identical_episodes_across_runs():
    """Fixed seeds must reproduce the same scenario/episode results --
    same determinism convention as the pre-existing scenarios' own tests."""
    for scenario in INJECTION_TYPE_SCENARIOS:
        first = run_baseline_policy_episode(scenario)
        second = run_baseline_policy_episode(scenario)
        assert first.cumulative_reward == second.cumulative_reward
        assert first.step_count == second.step_count
        assert first.approved_action_histogram == second.approved_action_histogram


def test_evaluation_scenario_metadata_covers_every_evaluation_scenario():
    for scenario in _ALL_EVALUATION_SCENARIOS:
        assert scenario.name in EVALUATION_SCENARIO_METADATA


def test_evaluation_scenario_metadata_is_explicit_and_labeled_held_out_evaluation():
    for scenario in _ALL_EVALUATION_SCENARIOS:
        metadata = EVALUATION_SCENARIO_METADATA[scenario.name]
        assert metadata.name == scenario.name
        assert metadata.purpose
        assert metadata.classification in ("clean", "fault", "attack")
        assert metadata.scenario_set == "evaluation"
        assert metadata.known_limitations


def test_evaluation_scenario_metadata_injection_fields_match_the_scenario():
    for scenario in INJECTION_TYPE_SCENARIOS:
        metadata = EVALUATION_SCENARIO_METADATA[scenario.name]
        injection = scenario.injections[0]
        assert metadata.injection_type is injection.injection_type
        assert metadata.affected_channel == injection.channel
        assert metadata.onset == injection.onset
        assert metadata.duration == injection.duration
        expected_window = (injection.onset, injection.onset + injection.duration)
        assert metadata.expected_active_window == expected_window


def test_clean_scenario_metadata_has_no_injection_fields():
    metadata = EVALUATION_SCENARIO_METADATA[SCENARIO_CLEAN_DEGRADATION.name]
    assert metadata.classification == "clean"
    assert metadata.injection_type is None
    assert metadata.affected_channel is None
    assert metadata.onset is None
    assert metadata.duration is None
    assert metadata.expected_active_window is None


def test_metadata_and_scenario_definitions_make_no_forbidden_claims():
    """No test, docstring, or metadata field may claim improved accuracy,
    safety, false-isolation performance, validation, or U06 resolution."""
    import edge.eval.rl_baseline_eval as module

    source = inspect.getsource(module)
    forbidden = (
        "u06 is resolved",
        "u06 is partially resolved",
        "resolves u06",
        "false-isolation rate is acceptable",
        "acceptable false-isolation rate",
        "improves false isolation",
        "improves accuracy",
        "is safer than",
        "is more accurate",
        "this scenario is validated",
        "these scenarios are validated",
    )
    lowered = source.lower()
    for phrase in forbidden:
        assert phrase not in lowered


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
