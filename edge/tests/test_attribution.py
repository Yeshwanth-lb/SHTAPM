"""P2 tests — attribution-engine branch logic (interface only).

Validate ONLY the documented none/fault/attack branch structure wired around an
injected physics rule. The physics itself is a test stub; these tests make NO
claim that any real physics rule or P2 attribution acceptance gate is satisfied.
"""

import pytest
from app.schemas.contracts import CHANNELS, Attribution

from edge.anomaly.attribution import (
    REASON_ATTACK_FALLBACK,
    REASON_FAULT,
    AttributionEngine,
    PhysicsCheck,
    PhysicsRule,
)
from edge.anomaly.preprocess import Window


# --- test-only stub physics rules (NOT real physics) ------------------------
class StubPhysicsRule:
    """Returns a fixed PhysicsCheck regardless of the window."""

    def __init__(self, violated: bool, suspect_channel=None, reason: str = "") -> None:
        self._result = PhysicsCheck(
            violated=violated, suspect_channel=suspect_channel, reason=reason
        )
        self.calls = 0

    def check(self, window: Window) -> PhysicsCheck:
        self.calls += 1
        return self._result


def _window() -> Window:
    return Window(start_index=0, end_index=1, features={ch: (0.0,) for ch in CHANNELS})


def _flags(**overrides) -> dict[str, bool]:
    flags = {ch: False for ch in CHANNELS}
    flags.update(overrides)
    return flags


# --- no anomaly --------------------------------------------------------------


def test_no_anomaly_is_none_everywhere():
    eng = AttributionEngine(StubPhysicsRule(violated=False))
    out = eng.attribute(_flags(), _window())
    assert all(r.attribution is Attribution.none for r in out.values())
    assert all(r.reason == "" for r in out.values())


def test_rule_not_consulted_when_no_flags():
    rule = StubPhysicsRule(violated=True, suspect_channel="pressure")
    AttributionEngine(rule).attribute(_flags(), _window())
    assert rule.calls == 0  # physics only checked when something is flagged


# --- anomaly + consistent physics -> fault ----------------------------------


def test_anomaly_with_consistent_physics_is_fault():
    eng = AttributionEngine(StubPhysicsRule(violated=False))
    out = eng.attribute(_flags(vibration=True), _window())
    assert out["vibration"].attribution is Attribution.fault
    assert out["vibration"].reason == REASON_FAULT
    # unflagged channels remain none
    assert out["temperature"].attribution is Attribution.none


# --- anomaly + violation -> attack ------------------------------------------


def test_anomaly_with_violation_on_suspect_is_attack():
    rule = StubPhysicsRule(
        violated=True,
        suspect_channel="pressure",
        reason="physics violation: pressure vs current",  # template via the rule
    )
    out = AttributionEngine(rule).attribute(_flags(pressure=True), _window())
    assert out["pressure"].attribution is Attribution.attack
    assert out["pressure"].reason == "physics violation: pressure vs current"


def test_attack_reason_falls_back_when_rule_gives_empty():
    rule = StubPhysicsRule(violated=True, suspect_channel="pressure", reason="")
    out = AttributionEngine(rule).attribute(_flags(pressure=True), _window())
    assert out["pressure"].reason == REASON_ATTACK_FALLBACK


def test_flagged_non_suspect_channel_is_fault_even_under_violation():
    # Violation blames pressure; gas is also anomalous but not the suspect.
    rule = StubPhysicsRule(violated=True, suspect_channel="pressure", reason="x")
    out = AttributionEngine(rule).attribute(_flags(pressure=True, gas=True), _window())
    assert out["pressure"].attribution is Attribution.attack
    assert out["gas"].attribution is Attribution.fault


def test_violation_without_flagged_suspect_yields_only_faults():
    # Suspect isn't flagged; the flagged channel gets fault, suspect stays none.
    rule = StubPhysicsRule(violated=True, suspect_channel="current")
    out = AttributionEngine(rule).attribute(_flags(vibration=True), _window())
    assert out["vibration"].attribution is Attribution.fault
    assert out["current"].attribution is Attribution.none


# --- per-channel independence (simultaneous fault + attack) -----------------


def test_simultaneous_fault_and_attack_independent():
    rule = StubPhysicsRule(violated=True, suspect_channel="pressure", reason="r")
    out = AttributionEngine(rule).attribute(_flags(pressure=True, temperature=True), _window())
    assert out["pressure"].attribution is Attribution.attack  # the liar
    assert out["temperature"].attribution is Attribution.fault  # genuine fault
    assert out["humidity"].attribution is Attribution.none


# --- stub-rule behaviour -----------------------------------------------------


def test_stub_rule_satisfies_protocol():
    assert isinstance(StubPhysicsRule(violated=False), PhysicsRule)


def test_rule_consulted_once_per_window():
    rule = StubPhysicsRule(violated=True, suspect_channel="pressure")
    AttributionEngine(rule).attribute(_flags(pressure=True, gas=True), _window())
    assert rule.calls == 1  # single cross-sensor check, not per channel


# --- validation --------------------------------------------------------------


def test_unknown_flag_channel_rejected():
    eng = AttributionEngine(StubPhysicsRule(violated=False))
    with pytest.raises(ValueError):
        eng.attribute({"flow": True}, _window())


def test_physics_check_rejects_unknown_suspect():
    with pytest.raises(ValueError):
        PhysicsCheck(violated=True, suspect_channel="flow", reason="x")


def test_physics_check_allows_none_suspect():
    pc = PhysicsCheck(violated=False, suspect_channel=None, reason="")
    assert pc.suspect_channel is None
