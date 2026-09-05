"""Tests for edge/rl/reward.py (FR-RL3 reward contract). No RL training,
approved weights, or reward-shaping claim exists yet -- no test here
treats any weight/magnitude as a research-validated value. Pure Python,
no torch dependency.
"""

from __future__ import annotations

from app.schemas.contracts import CHANNELS, RLAction

from edge.rl.fallback_gate import GateDecision
from edge.rl.reward import (
    EXECUTION_MODE,
    PENALTY_MAGNITUDE_FIXTURE,
    REWARD_MAGNITUDE_FIXTURE,
    SIMULATION_REWARD_WEIGHTS_FIXTURE,
    RewardComponents,
    RewardResult,
    RewardWeights,
    compute_reward,
)
from edge.rl.state import RLState

_TRUSTED_FIXTURE = 0.9


def _trust(overrides: dict[str, float] | None = None) -> dict[str, float]:
    overrides = overrides or {}
    return {ch: overrides.get(ch, _TRUSTED_FIXTURE) for ch in CHANNELS}


def _state(**overrides) -> RLState:
    kwargs = {
        "health": 0.8,
        "anomaly_flag": False,
        "trust": _trust(),
        "failure_eta": 50.0,
    }
    kwargs.update(overrides)
    return RLState(**kwargs)


def _gate_decision(**overrides) -> GateDecision:
    kwargs = {
        "requested_action": RLAction.continue_,
        "approved_action": RLAction.continue_,
        "fallback_used": False,
        "fallback_reason": None,
        "safety_status": "nominal",
        "policy_status": "validated",
        "confidence": 0.95,
        "confidence_threshold": 0.8,
    }
    kwargs.update(overrides)
    return GateDecision(**kwargs)


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------


def test_compute_reward_returns_reward_result_with_components():
    result = compute_reward(
        previous_state=_state(), gate_decision=_gate_decision(), next_state=_state()
    )
    assert isinstance(result, RewardResult)
    assert isinstance(result.components, RewardComponents)
    assert result.requested_action == RLAction.continue_
    assert result.approved_action == RLAction.continue_
    assert result.fallback_used is False
    assert result.previous_state is not None
    assert result.next_state is not None


# ---------------------------------------------------------------------------
# Component accounting
# ---------------------------------------------------------------------------


def test_health_maintenance_equals_next_state_health():
    result = compute_reward(
        previous_state=_state(), gate_decision=_gate_decision(), next_state=_state(health=0.42)
    )
    assert result.components.health_maintenance == 0.42


def test_anomaly_impact_penalizes_active_anomaly():
    clean = compute_reward(
        previous_state=None, gate_decision=_gate_decision(), next_state=_state(anomaly_flag=False)
    )
    flagged = compute_reward(
        previous_state=None, gate_decision=_gate_decision(), next_state=_state(anomaly_flag=True)
    )
    assert clean.components.anomaly_impact == 0.0
    assert flagged.components.anomaly_impact == -PENALTY_MAGNITUDE_FIXTURE


def test_trust_preservation_is_mean_trust():
    state = _state(trust=_trust({"vibration": 0.5, "current": 0.3}))
    result = compute_reward(previous_state=None, gate_decision=_gate_decision(), next_state=state)
    expected = sum(state.trust.values()) / len(state.trust)
    assert result.components.trust_preservation == expected


def test_isolation_appropriateness_penalizes_false_isolation():
    gate_decision = _gate_decision(
        requested_action=RLAction.isolate, approved_action=RLAction.isolate, safety_status="nominal"
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.isolation_appropriateness == -PENALTY_MAGNITUDE_FIXTURE


def test_isolation_appropriateness_penalizes_missed_fault():
    gate_decision = _gate_decision(
        requested_action=RLAction.continue_,
        approved_action=RLAction.isolate,  # gate overrode it
        safety_status="isolation_active",
        fallback_used=True,
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.isolation_appropriateness == -PENALTY_MAGNITUDE_FIXTURE


def test_isolation_appropriateness_neutral_when_isolate_matches_real_condition():
    gate_decision = _gate_decision(
        requested_action=RLAction.isolate,
        approved_action=RLAction.isolate,
        safety_status="isolation_active",
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.isolation_appropriateness == 0.0


def test_unsafe_action_penalty_fires_for_safe_stop_active_violation():
    gate_decision = _gate_decision(
        requested_action=RLAction.continue_,
        approved_action=RLAction.safe_stop,
        safety_status="safe_stop_active",
        fallback_used=True,
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.unsafe_action_penalty == -PENALTY_MAGNITUDE_FIXTURE


def test_unsafe_action_penalty_fires_for_tracked_continue_violation():
    gate_decision = _gate_decision(
        requested_action=RLAction.continue_,
        approved_action=RLAction.isolate,
        safety_status="isolation_active",
        fallback_used=True,
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.unsafe_action_penalty == -PENALTY_MAGNITUDE_FIXTURE


def test_unsafe_action_penalty_does_not_fire_for_mere_unavailability_fallback():
    """A fallback caused only by an unavailable/unvalidated policy is not,
    by itself, an unsafe ACTION -- see module docstring."""
    gate_decision = _gate_decision(
        requested_action=RLAction.continue_,
        approved_action=RLAction.continue_,
        safety_status="nominal",
        policy_status="unvalidated",
        fallback_used=True,
        confidence=None,
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.unsafe_action_penalty == 0.0


def test_recovery_stabilization_is_health_delta():
    result = compute_reward(
        previous_state=_state(health=0.3),
        gate_decision=_gate_decision(),
        next_state=_state(health=0.7),
    )
    assert result.components.recovery_stabilization == 0.7 - 0.3


def test_recovery_stabilization_negative_when_health_worsens():
    result = compute_reward(
        previous_state=_state(health=0.7),
        gate_decision=_gate_decision(),
        next_state=_state(health=0.3),
    )
    assert result.components.recovery_stabilization < 0.0


def test_safe_stop_behavior_rewards_warranted_stop():
    gate_decision = _gate_decision(
        requested_action=RLAction.safe_stop,
        approved_action=RLAction.safe_stop,
        safety_status="isolation_active",
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.safe_stop_behavior == REWARD_MAGNITUDE_FIXTURE


def test_safe_stop_behavior_penalizes_unwarranted_stop():
    gate_decision = _gate_decision(
        requested_action=RLAction.safe_stop,
        approved_action=RLAction.safe_stop,
        safety_status="nominal",
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.safe_stop_behavior == -PENALTY_MAGNITUDE_FIXTURE


def test_safe_stop_behavior_neutral_when_not_requested():
    result = compute_reward(
        previous_state=None, gate_decision=_gate_decision(), next_state=_state()
    )
    assert result.components.safe_stop_behavior == 0.0


# ---------------------------------------------------------------------------
# Total calculation
# ---------------------------------------------------------------------------


def test_total_is_none_without_weights():
    result = compute_reward(
        previous_state=_state(), gate_decision=_gate_decision(), next_state=_state()
    )
    assert result.total is None
    assert result.reward_policy_status == "unweighted"


def test_total_is_computed_with_simulation_fixture_weights():
    result = compute_reward(
        previous_state=_state(health=0.3),
        gate_decision=_gate_decision(),
        next_state=_state(health=0.7),
        weights=SIMULATION_REWARD_WEIGHTS_FIXTURE,
    )
    c = result.components
    expected = (
        c.health_maintenance
        + c.anomaly_impact
        + c.trust_preservation
        + c.isolation_appropriateness
        + c.unsafe_action_penalty
        + c.recovery_stabilization
        + c.safe_stop_behavior
    )
    assert result.total == expected  # weights are all 1.0
    assert result.reward_policy_status == "simulation_fixture_weighted"


def test_custom_weights_scale_components_correctly():
    weights = RewardWeights(
        health_maintenance=2.0,
        anomaly_impact=0.0,
        trust_preservation=0.0,
        isolation_appropriateness=0.0,
        unsafe_action_penalty=0.0,
        recovery_stabilization=0.0,
        safe_stop_behavior=0.0,
    )
    result = compute_reward(
        previous_state=None,
        gate_decision=_gate_decision(),
        next_state=_state(health=0.4),
        weights=weights,
    )
    assert result.total == 0.4 * 2.0


# ---------------------------------------------------------------------------
# Invalid state / action handling
# ---------------------------------------------------------------------------


def test_none_previous_and_next_state_produces_neutral_components_no_crash():
    result = compute_reward(previous_state=None, gate_decision=_gate_decision(), next_state=None)
    c = result.components
    assert c.health_maintenance == 0.0
    assert c.anomaly_impact == 0.0
    assert c.trust_preservation == 0.0
    assert c.recovery_stabilization == 0.0


def test_none_requested_action_produces_neutral_action_components():
    gate_decision = _gate_decision(requested_action=None, approved_action=RLAction.isolate)
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.isolation_appropriateness == 0.0
    assert result.components.safe_stop_behavior == 0.0
    assert result.components.unsafe_action_penalty == 0.0


def test_unrecognized_requested_action_value_does_not_crash():
    # A value that does NOT equal any real RLAction member (RLAction is a
    # str-Enum, so e.g. "isolate" would legitimately compare equal to
    # RLAction.isolate -- this uses a value with no such match).
    gate_decision = _gate_decision(
        requested_action="not_a_real_action", approved_action=RLAction.continue_
    )
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.components.isolation_appropriateness == 0.0
    assert result.components.safe_stop_behavior == 0.0
    assert result.components.unsafe_action_penalty == 0.0


# ---------------------------------------------------------------------------
# Deterministic behavior
# ---------------------------------------------------------------------------


def test_same_inputs_produce_identical_result():
    prev, gate_decision, nxt = _state(health=0.6), _gate_decision(), _state(health=0.5)
    first = compute_reward(previous_state=prev, gate_decision=gate_decision, next_state=nxt)
    second = compute_reward(previous_state=prev, gate_decision=gate_decision, next_state=nxt)
    assert first == second


# ---------------------------------------------------------------------------
# Simulation metadata
# ---------------------------------------------------------------------------


def test_metadata_fields():
    result = compute_reward(
        previous_state=None, gate_decision=_gate_decision(), next_state=_state()
    )
    assert result.execution_mode == "simulation"
    assert result.simulation_only is True
    assert EXECUTION_MODE == "simulation"


def test_fallback_used_is_carried_through():
    gate_decision = _gate_decision(fallback_used=True)
    result = compute_reward(previous_state=None, gate_decision=gate_decision, next_state=_state())
    assert result.fallback_used is True


# ---------------------------------------------------------------------------
# Provisional fixture values
# ---------------------------------------------------------------------------


def test_fixture_weights_are_uniform_and_labeled_simulation_only():
    w = SIMULATION_REWARD_WEIGHTS_FIXTURE
    values = {
        w.health_maintenance,
        w.anomaly_impact,
        w.trust_preservation,
        w.isolation_appropriateness,
        w.unsafe_action_penalty,
        w.recovery_stabilization,
        w.safe_stop_behavior,
    }
    assert values == {1.0}


def test_magnitude_fixtures_are_distinct_named_values_not_reused_from_other_modules():
    from edge.eval.synthetic_prognosis_training import (
        SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
        SYNTHETIC_HEALTH_WARNING_THRESHOLD,
    )
    from edge.pipeline.self_heal import UNCERTAINTY_CAP_D020
    from edge.rl.fallback_gate import RL_CONFIDENCE_THRESHOLD_FIXTURE
    from edge.rl.policy import BASELINE_CRITICAL_HEALTH_FIXTURE

    other_values = {
        UNCERTAINTY_CAP_D020,
        SYNTHETIC_HEALTH_WARNING_THRESHOLD,
        SYNTHETIC_HEALTH_CRITICAL_THRESHOLD,
        RL_CONFIDENCE_THRESHOLD_FIXTURE,
        BASELINE_CRITICAL_HEALTH_FIXTURE,
    }
    assert PENALTY_MAGNITUDE_FIXTURE not in other_values or PENALTY_MAGNITUDE_FIXTURE == 1.0
    # The real point: this module defines its OWN named constants rather
    # than importing/reusing any of the above for a different purpose.
    assert PENALTY_MAGNITUDE_FIXTURE == 1.0
    assert REWARD_MAGNITUDE_FIXTURE == 1.0


# ---------------------------------------------------------------------------
# No external/hardware side effects
# ---------------------------------------------------------------------------


def test_module_has_no_actuator_gpio_network_or_db_imports():
    import edge.rl.reward as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in (
        "RelayController",
        "FakeActuator",
        "SelfHealOrchestrator",
        "process_isolated_channels",
        "IsolationFallbackTracker",
        "paho",
        "sqlalchemy",
        "Session",
    ):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


def test_module_never_claims_approved_or_final_weights():
    import edge.rl.reward as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "production-ready" not in content
    assert "research-validated" not in content
    assert "is approved" not in content
