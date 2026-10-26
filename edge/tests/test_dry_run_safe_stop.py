"""Tests for the O7 dry-run Safe Pump-Stop demo (edge/scripts/dry_run_safe_stop.py).

The demo drives the real SelfHealOrchestrator against a FakeActuator relay;
these tests pin that the escalation path genuinely fires (and only when it
should), without touching any GPIO.
"""

from __future__ import annotations

import math

from edge.actuation.relay import RelayState
from edge.pipeline.self_heal import EscalationReason
from edge.scripts import dry_run_safe_stop as demo


def _quiet(_: str) -> None:
    pass


def test_demo_threshold_is_a_finite_fixture_not_production_inf() -> None:
    assert math.isfinite(demo.DEMO_DIVERGENCE_THRESHOLD)


def test_divergence_path_escalates_and_calls_safe_off_exactly_once() -> None:
    result = demo.run_divergence_scenario(log=_quiet)

    escalated = [o for o in result.outcomes if o.escalated]
    assert len(escalated) == 1
    assert escalated[0].escalation_reason == EscalationReason.DIVERGENCE_EXCEEDED
    assert escalated[0].divergence >= demo.DEMO_DIVERGENCE_THRESHOLD
    assert result.safe_off_calls == 1
    assert result.final_relay_state is RelayState.OFF
    # Pump was running before the stop, then forced off.
    assert RelayState.ON in result.relay_history
    assert result.relay_history[-1] is RelayState.OFF


def test_no_escalation_while_divergence_below_threshold() -> None:
    result = demo.run_divergence_scenario(log=_quiet)

    before = result.outcomes[:-1]
    assert before, "demo should substitute for at least one cycle before escalating"
    for outcome in before:
        assert outcome.substituted
        assert not outcome.escalated
        assert outcome.divergence < demo.DEMO_DIVERGENCE_THRESHOLD


def test_expiry_path_escalates_at_substitution_limit() -> None:
    result = demo.run_expiry_scenario(log=_quiet)

    escalated = [o for o in result.outcomes if o.escalated]
    assert len(escalated) == 1
    assert escalated[0].escalation_reason == EscalationReason.SUBSTITUTION_EXPIRED
    assert escalated[0].divergence < demo.DEMO_DIVERGENCE_THRESHOLD
    assert result.safe_off_calls == 1
    assert result.final_relay_state is RelayState.OFF


def test_recovery_prevents_escalation() -> None:
    result = demo.run_recovery_scenario(log=_quiet)

    assert result.safe_off_calls == 0
    assert not any(o.escalated for o in result.outcomes)
    assert result.final_relay_state is RelayState.ON
    last = result.outcomes[-1]
    assert not last.substituted  # trust recovered -> real sensor re-admitted


def test_main_runs_end_to_end(capsys) -> None:
    assert demo.main() == 0
    out = capsys.readouterr().out
    assert "safe_off() INVOKED [DRY RUN" in out
    assert "TEST FIXTURE" in out
