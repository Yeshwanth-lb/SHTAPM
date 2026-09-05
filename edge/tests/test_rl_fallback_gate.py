"""Tests for edge/rl/fallback_gate.py (FR-RL4 safety gate). No RL policy,
training, or reward weights exist yet -- every "requested_action"/
"confidence" below is a test-supplied stand-in, never a real trained
policy output. Pure Python, no torch dependency.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS, RLAction

from edge.pipeline.isolation_tracker import IsolationTrackerResult
from edge.rl.fallback_gate import (
    EXECUTION_MODE,
    RL_CONFIDENCE_THRESHOLD_FIXTURE,
    GateDecision,
    evaluate_rl_action,
)
from edge.rl.state import RLState

_DEFAULT_TRUST_FIXTURE = 0.9


def _trust_values(overrides: dict[str, float] | None = None) -> dict[str, float]:
    overrides = overrides or {}
    return {ch: overrides.get(ch, _DEFAULT_TRUST_FIXTURE) for ch in CHANNELS}


def _state() -> RLState:
    return RLState(health=0.9, anomaly_flag=False, trust=_trust_values(), failure_eta=10.0)


def _no_isolation() -> IsolationTrackerResult:
    return IsolationTrackerResult(
        candidates_this_cycle=frozenset(), tracked_channels=frozenset(), reasons={}
    )


def _isolation_active(channel: str = "vibration") -> IsolationTrackerResult:
    return IsolationTrackerResult(
        candidates_this_cycle=frozenset({channel}),
        tracked_channels=frozenset({channel}),
        reasons={channel: "still malicious this cycle: fixture"},
    )


def _evaluate(**overrides):
    kwargs = {
        "requested_action": RLAction.continue_,
        "state": _state(),
        "isolation_status": _no_isolation(),
        "policy_available": True,
        "policy_validated": True,
        "confidence_threshold": RL_CONFIDENCE_THRESHOLD_FIXTURE,
        "confidence": 0.95,
        "already_safe_stopped": False,
    }
    kwargs.update(overrides)
    return evaluate_rl_action(**kwargs)


# ---------------------------------------------------------------------------
# Happy path: everything valid -> RL's own action is approved
# ---------------------------------------------------------------------------


def test_valid_confident_validated_action_is_approved():
    decision = _evaluate()
    assert isinstance(decision, GateDecision)
    assert decision.approved_action == RLAction.continue_
    assert decision.fallback_used is False
    assert decision.fallback_reason is None
    assert decision.policy_status == "validated"
    assert decision.safety_status == "nominal"


def test_approved_decision_carries_execution_mode():
    decision = _evaluate()
    assert decision.execution_mode == "simulation"
    assert EXECUTION_MODE == "simulation"


# ---------------------------------------------------------------------------
# Invalid / missing requested action
# ---------------------------------------------------------------------------


def test_none_requested_action_falls_back():
    decision = _evaluate(requested_action=None)
    assert decision.fallback_used is True
    assert "no RL action" in decision.fallback_reason


def test_non_rlaction_requested_action_falls_back():
    decision = _evaluate(requested_action="isolate")  # a string, not the enum
    assert decision.fallback_used is True
    assert "not a valid RLAction" in decision.fallback_reason


# ---------------------------------------------------------------------------
# Policy availability / validation
# ---------------------------------------------------------------------------


def test_policy_unavailable_falls_back():
    decision = _evaluate(policy_available=False)
    assert decision.fallback_used is True
    assert decision.policy_status == "unavailable"
    assert "unavailable" in decision.fallback_reason


def test_policy_unvalidated_falls_back():
    decision = _evaluate(policy_validated=False)
    assert decision.fallback_used is True
    assert decision.policy_status == "unvalidated"
    assert "not been validated" in decision.fallback_reason


def test_unavailable_takes_precedence_over_unvalidated_status():
    decision = _evaluate(policy_available=False, policy_validated=False)
    assert decision.policy_status == "unavailable"


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------


def test_missing_confidence_on_validated_policy_falls_back():
    decision = _evaluate(confidence=None)
    assert decision.fallback_used is True
    assert "confidence score" in decision.fallback_reason


def test_confidence_below_threshold_falls_back():
    decision = _evaluate(confidence=0.5, confidence_threshold=0.8)
    assert decision.fallback_used is True
    assert decision.policy_status == "validated_low_confidence"
    assert "below the required threshold" in decision.fallback_reason


def test_confidence_exactly_at_threshold_is_accepted():
    decision = _evaluate(confidence=0.8, confidence_threshold=0.8)
    assert decision.fallback_used is False


def test_confidence_threshold_is_required_argument():
    with pytest.raises(TypeError):
        evaluate_rl_action(
            requested_action=RLAction.continue_,
            state=_state(),
            isolation_status=_no_isolation(),
            policy_available=True,
            policy_validated=True,
            confidence=0.9,
        )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# State unavailable / invalid
# ---------------------------------------------------------------------------


def test_missing_state_falls_back():
    decision = _evaluate(state=None)
    assert decision.fallback_used is True
    assert "state is unavailable" in decision.fallback_reason


# ---------------------------------------------------------------------------
# Safe-stop: never overridden, in either direction
# ---------------------------------------------------------------------------


def test_already_safe_stopped_forces_safe_stop_regardless_of_request():
    decision = _evaluate(requested_action=RLAction.continue_, already_safe_stopped=True)
    assert decision.approved_action == RLAction.safe_stop
    assert decision.fallback_used is True
    assert decision.safety_status == "safe_stop_active"


def test_already_safe_stopped_ignores_policy_unavailability():
    decision = _evaluate(already_safe_stopped=True, policy_available=False, state=None)
    assert decision.approved_action == RLAction.safe_stop
    assert decision.fallback_used is True


def test_requested_safe_stop_is_approved_even_with_unavailable_policy():
    decision = _evaluate(requested_action=RLAction.safe_stop, policy_available=False)
    assert decision.approved_action == RLAction.safe_stop
    assert decision.fallback_used is False


def test_requested_safe_stop_is_approved_even_with_low_confidence():
    decision = _evaluate(requested_action=RLAction.safe_stop, confidence=0.0)
    assert decision.approved_action == RLAction.safe_stop
    assert decision.fallback_used is False


def test_requested_safe_stop_is_approved_even_with_missing_state():
    decision = _evaluate(requested_action=RLAction.safe_stop, state=None)
    assert decision.approved_action == RLAction.safe_stop
    assert decision.fallback_used is False


# ---------------------------------------------------------------------------
# Deterministic safety-constraint violation: resuming a tracked channel
# ---------------------------------------------------------------------------


def test_continue_while_channel_tracked_as_isolated_falls_back():
    decision = _evaluate(requested_action=RLAction.continue_, isolation_status=_isolation_active())
    assert decision.fallback_used is True
    assert decision.safety_status == "isolation_active"
    assert "tracked isolation" in decision.fallback_reason


def test_isolate_while_channel_tracked_as_isolated_is_approved():
    decision = _evaluate(requested_action=RLAction.isolate, isolation_status=_isolation_active())
    assert decision.fallback_used is False
    assert decision.approved_action == RLAction.isolate


# ---------------------------------------------------------------------------
# Deterministic fallback action selection
# ---------------------------------------------------------------------------


def test_fallback_action_is_continue_when_nothing_tracked():
    decision = _evaluate(policy_available=False, isolation_status=_no_isolation())
    assert decision.approved_action == RLAction.continue_


def test_fallback_action_is_isolate_when_a_channel_is_tracked():
    decision = _evaluate(policy_available=False, isolation_status=_isolation_active())
    assert decision.approved_action == RLAction.isolate


# ---------------------------------------------------------------------------
# Structural isolation: no actuator/GPIO/network coupling
# ---------------------------------------------------------------------------


def test_module_has_no_actuator_gpio_or_network_imports():
    import edge.rl.fallback_gate as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    for forbidden in ("RelayController", "FakeActuator", "SelfHealOrchestrator", "paho"):
        assert forbidden not in content
    assert "GPIO" not in content.upper()
    assert "MQTT" not in content.upper()


def test_module_never_claims_production_validation():
    import edge.rl.fallback_gate as module

    with open(module.__file__, encoding="utf-8") as f:
        content = f.read()
    assert "production-ready" not in content
    assert "hardware-validated" not in content
