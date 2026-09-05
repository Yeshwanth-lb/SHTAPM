"""Tests for edge/rl/policy.py (RL policy interface + simulation baseline).
No training, learning, or reward weights exist yet -- no test here claims
learned intelligence or research validity. Pure Python, no torch
dependency.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS, RLAction

from edge.pipeline.isolation_tracker import IsolationTrackerResult
from edge.rl.fallback_gate import RL_CONFIDENCE_THRESHOLD_FIXTURE, evaluate_rl_action
from edge.rl.policy import (
    BASELINE_CRITICAL_HEALTH_FIXTURE,
    BASELINE_POLICY_NAME,
    BASELINE_POLICY_VERSION,
    EXECUTION_MODE,
    BaselinePolicy,
    Policy,
    PolicyDecision,
)
from edge.rl.state import RLState

_TRUSTED_FIXTURE = 0.9
_SUSPICIOUS_FIXTURE = 0.5
_MALICIOUS_FIXTURE = 0.1


def _trust(overrides: dict[str, float] | None = None) -> dict[str, float]:
    overrides = overrides or {}
    return {ch: overrides.get(ch, _TRUSTED_FIXTURE) for ch in CHANNELS}


def _state(**overrides) -> RLState:
    kwargs = {
        "health": 0.9,
        "anomaly_flag": False,
        "trust": _trust(),
        "failure_eta": 100.0,
    }
    kwargs.update(overrides)
    return RLState(**kwargs)


def _policy() -> BaselinePolicy:
    return BaselinePolicy(critical_health_threshold=BASELINE_CRITICAL_HEALTH_FIXTURE)


def _no_isolation() -> IsolationTrackerResult:
    return IsolationTrackerResult(
        candidates_this_cycle=frozenset(), tracked_channels=frozenset(), reasons={}
    )


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_baseline_policy_satisfies_the_policy_protocol():
    assert isinstance(_policy(), Policy)


# ---------------------------------------------------------------------------
# Valid state -> a valid RLAction
# ---------------------------------------------------------------------------


def test_nominal_state_produces_continue():
    decision = _policy().propose(_state())
    assert isinstance(decision, PolicyDecision)
    assert decision.proposed_action == RLAction.continue_
    assert isinstance(decision.proposed_action, RLAction)


def test_suspicious_channel_produces_reduce_weight():
    state = _state(trust=_trust({"vibration": _SUSPICIOUS_FIXTURE}))
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.reduce_weight
    assert "vibration" in decision.reason


def test_malicious_channel_produces_isolate():
    state = _state(trust=_trust({"current": _MALICIOUS_FIXTURE}))
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.isolate
    assert "current" in decision.reason


def test_malicious_takes_precedence_over_suspicious():
    state = _state(trust=_trust({"current": _MALICIOUS_FIXTURE, "vibration": _SUSPICIOUS_FIXTURE}))
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.isolate


def test_anomaly_with_no_degraded_channel_produces_alert():
    state = _state(anomaly_flag=True)
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.alert


def test_anomaly_with_malicious_channel_still_produces_isolate():
    state = _state(anomaly_flag=True, trust=_trust({"gas": _MALICIOUS_FIXTURE}))
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.isolate


# ---------------------------------------------------------------------------
# Invalid state / unsafe condition -> safe_stop
# ---------------------------------------------------------------------------


def test_none_state_produces_safe_stop():
    decision = _policy().propose(None)
    assert decision.proposed_action == RLAction.safe_stop
    assert "unavailable" in decision.reason


def test_health_at_or_below_critical_threshold_produces_safe_stop():
    state = _state(health=BASELINE_CRITICAL_HEALTH_FIXTURE)
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.safe_stop


def test_health_just_above_critical_threshold_does_not_force_safe_stop():
    state = _state(health=BASELINE_CRITICAL_HEALTH_FIXTURE + 0.01)
    decision = _policy().propose(state)
    assert decision.proposed_action != RLAction.safe_stop


def test_critical_health_overrides_malicious_channel_rule():
    state = _state(health=0.0, trust=_trust({"current": _MALICIOUS_FIXTURE}))
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.safe_stop


def test_missing_health_does_not_by_itself_force_safe_stop():
    state = _state(health=None, failure_eta=None)
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.continue_


def test_constructor_rejects_out_of_range_threshold():
    with pytest.raises(ValueError):
        BaselinePolicy(critical_health_threshold=1.5)
    with pytest.raises(ValueError):
        BaselinePolicy(critical_health_threshold=-0.1)


# ---------------------------------------------------------------------------
# Deterministic behavior
# ---------------------------------------------------------------------------


def test_same_state_produces_identical_decision_repeatedly():
    policy = _policy()
    state = _state(trust=_trust({"pressure": _SUSPICIOUS_FIXTURE}))
    first = policy.propose(state)
    second = policy.propose(state)
    assert first == second


# ---------------------------------------------------------------------------
# Metadata / explicit simulation-baseline status
# ---------------------------------------------------------------------------


def test_metadata_fields_present_and_correct():
    decision = _policy().propose(_state())
    assert decision.execution_mode == "simulation"
    assert decision.policy_name == BASELINE_POLICY_NAME
    assert decision.policy_version == BASELINE_POLICY_VERSION
    assert EXECUTION_MODE == "simulation"


def test_baseline_always_reports_available_and_unvalidated():
    for state in (_state(), None, _state(health=0.0)):
        decision = _policy().propose(state)
        assert decision.policy_available is True
        assert decision.policy_validated is False


def test_baseline_confidence_is_always_none():
    for state in (_state(), None, _state(trust=_trust({"humidity": _MALICIOUS_FIXTURE}))):
        decision = _policy().propose(state)
        assert decision.confidence is None


def test_policy_version_string_is_explicitly_marked_unvalidated():
    assert "unvalidated" in BASELINE_POLICY_VERSION


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


def test_module_has_no_actuator_gpio_network_or_isolation_side_effects():
    import edge.rl.policy as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in (
        "RelayController",
        "FakeActuator",
        "SelfHealOrchestrator",
        "process_isolated_channels",
        "IsolationFallbackTracker",
        "paho",
    ):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


def test_module_never_claims_learned_intelligence_or_validation():
    import edge.rl.policy as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "production-ready" not in content
    assert "hardware-validated" not in content
    assert "is research-validated" not in content


# ---------------------------------------------------------------------------
# Compatibility with the existing fallback gate
# ---------------------------------------------------------------------------


def test_baseline_proposal_is_always_overridden_by_the_gate_except_safe_stop():
    """BaselinePolicy always reports policy_validated=False, so the gate's
    own existing rules must replace every non-safe_stop proposal with its
    own deterministic fallback -- proving the two modules compose exactly
    as the module docstring describes."""
    state = _state(trust=_trust({"current": _MALICIOUS_FIXTURE}))  # baseline proposes isolate
    decision = _policy().propose(state)
    assert decision.proposed_action == RLAction.isolate

    gate_decision = evaluate_rl_action(
        requested_action=decision.proposed_action,
        state=state,
        isolation_status=_no_isolation(),
        policy_available=decision.policy_available,
        policy_validated=decision.policy_validated,
        confidence_threshold=RL_CONFIDENCE_THRESHOLD_FIXTURE,
        confidence=decision.confidence,
    )
    assert gate_decision.fallback_used is True
    assert gate_decision.policy_status == "unvalidated"


def test_baseline_safe_stop_proposal_passes_the_gate_unconditionally():
    decision = _policy().propose(None)  # baseline proposes safe_stop
    assert decision.proposed_action == RLAction.safe_stop

    gate_decision = evaluate_rl_action(
        requested_action=decision.proposed_action,
        state=None,
        isolation_status=_no_isolation(),
        policy_available=decision.policy_available,
        policy_validated=decision.policy_validated,
        confidence_threshold=RL_CONFIDENCE_THRESHOLD_FIXTURE,
        confidence=decision.confidence,
    )
    assert gate_decision.approved_action == RLAction.safe_stop
    assert gate_decision.fallback_used is False
