"""Tests for edge/pipeline/self_heal.py (P3 · D016-D020 orchestration).

``DIVERGENCE_THRESHOLD_FIXTURE`` and ``SUBSTITUTION_MAX_SECONDS_FIXTURE``
below are TEST FIXTURES -- neither is presented as the project's resolved
divergence_threshold value (still data-gated/open, U05) or as a new
substitution-bound spec (a fixture copy of the already-approved D018
default). ``uncertainty_cap``/the elapsed-time scaling formula are NOT
fixtures here: they are the real, D020-approved values
(``UNCERTAINTY_CAP_D020`` / ``linear_scaling``), imported directly rather
than re-derived, to avoid a local copy drifting from the approved one.

The TwinReconstructor stub below is a fixture ONLY: edge/models/twin.py
ships no production implementation (per explicit implementation-approval
constraint), so every test here must supply one.
"""

from __future__ import annotations

import pytest
from app.schemas.contracts import CHANNELS

from edge.actuation.relay import FakeActuator, RelayController, RelayState
from edge.anomaly.preprocess import Window
from edge.pipeline.divergence import DivergenceScorer
from edge.pipeline.self_heal import (
    SUBSTITUTION_MAX_SECONDS_DEFAULT,
    UNCERTAINTY_CAP_D020,
    EscalationReason,
    SelfHealOrchestrator,
)
from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy, linear_scaling
from edge.trust.beta import TRUSTED_MIN

# ---------------------------------------------------------------------------
# Fixtures -- TEST FIXTURES ONLY, never project specification values.
# ---------------------------------------------------------------------------

DIVERGENCE_THRESHOLD_FIXTURE = 3.0
SUBSTITUTION_MAX_SECONDS_FIXTURE = 60.0


class _FixedReconstructionTwinFixture:
    """TEST FIXTURE ONLY -- not a production TwinReconstructor
    implementation (edge/models/twin.py ships none by design). Always
    reconstructs to a caller-supplied constant, regardless of window."""

    def __init__(self, value: float) -> None:
        self._value = value

    def reconstruct(self, window: Window, missing_channel: str) -> float:
        return self._value


def _empty_window() -> Window:
    return Window(start_index=0, end_index=1, features={ch: (0.0,) for ch in CHANNELS})


class ManualClock:
    """Deterministic clock, same pattern as edge/tests/test_watchdog.py."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _make_orchestrator(
    *,
    clock: ManualClock,
    divergence_threshold: float = DIVERGENCE_THRESHOLD_FIXTURE,
    uncertainty_cap: float = UNCERTAINTY_CAP_D020,
    substitution_max_seconds: float = SUBSTITUTION_MAX_SECONDS_FIXTURE,
    safe_stop=None,
    twin_value: float = 0.0,
):
    twin = _FixedReconstructionTwinFixture(twin_value)
    divergence_scorer = DivergenceScorer()
    # Tight residual spread around 0.0 so a raw_value far from twin_value
    # (residual far from 0) produces a large, easily-distinguishable z-score.
    # Both channels fit identically so multi-channel tests can reason about
    # either one predictably.
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1], "current": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)

    calls = {"n": 0}
    if safe_stop is None:

        def safe_stop():
            calls["n"] += 1

    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=divergence_threshold,
        uncertainty_cap=uncertainty_cap,
        safe_stop=safe_stop,
        substitution_max_seconds=substitution_max_seconds,
        clock=clock,
    )
    return orchestrator, calls


# ---------------------------------------------------------------------------
# Recovery (D018 pt.2)
# ---------------------------------------------------------------------------


def test_trust_at_or_above_trusted_min_is_not_substituted():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=TRUSTED_MIN
    )
    assert outcome.substituted is False
    assert outcome.escalated is False
    assert outcome.reconstructed_value is None
    assert outcome.divergence is None
    assert outcome.uncertainty is None
    assert calls["n"] == 0


def test_low_trust_starts_substitution():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.substituted is True
    assert outcome.escalated is False
    assert outcome.reconstructed_value == pytest.approx(0.0)
    assert outcome.divergence is not None
    assert outcome.uncertainty is not None
    assert outcome.alert is None
    assert calls["n"] == 0


def test_unknown_channel_raises():
    clock = ManualClock()
    orchestrator, _ = _make_orchestrator(clock=clock)
    with pytest.raises(ValueError):
        orchestrator.process_isolated_channel(
            "not_a_channel", _empty_window(), raw_value=0.0, trust=0.2
        )


# ---------------------------------------------------------------------------
# Divergence backstop (D018 pt.1, P3-HEAL-S1)
# ---------------------------------------------------------------------------


def test_large_divergence_escalates_and_calls_safe_stop():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    # twin_value=0.0, residual fit tight around 0.0; raw_value far from 0.0
    # forces a large residual -> large z-score -> exceeds the fixture threshold.
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.DIVERGENCE_EXCEEDED
    assert outcome.substituted is False
    assert calls["n"] == 1


def test_small_divergence_does_not_escalate():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.escalated is False
    assert calls["n"] == 0


def test_divergence_escalation_clears_episode():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert calls["n"] == 1
    clock.advance(5.0)
    # A fresh call after escalation starts a NEW episode (elapsed resets to
    # ~0 again) rather than continuing accumulated elapsed time.
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.uncertainty == pytest.approx(0.0)


def test_divergence_exactly_at_threshold_escalates():
    """Boundary check: divergence == divergence_threshold must escalate,
    proving the documented >= (inclusive) semantics at exact equality.

    The threshold is set to the SAME instance/inputs' computed divergence
    (rather than an independently hand-derived number) so the comparison is
    exact, not merely close under floating-point rounding.
    """
    clock = ManualClock()
    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    raw_value = -1.0
    reconstructed_value = 0.0
    residual = reconstructed_value - raw_value
    exact_divergence = divergence_scorer.score("temperature", residual)

    twin = _FixedReconstructionTwinFixture(reconstructed_value)
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    calls = {"n": 0}
    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=exact_divergence,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=lambda: calls.__setitem__("n", calls["n"] + 1),
        substitution_max_seconds=SUBSTITUTION_MAX_SECONDS_FIXTURE,
        clock=clock,
    )
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=raw_value, trust=0.2
    )
    assert outcome.divergence == exact_divergence
    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.DIVERGENCE_EXCEEDED
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# 60-second substitution expiry (D018 pt.3)
# ---------------------------------------------------------------------------


def test_expiry_without_recovery_escalates():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(SUBSTITUTION_MAX_SECONDS_FIXTURE)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.SUBSTITUTION_EXPIRED
    assert calls["n"] == 1


def test_recovery_before_expiry_avoids_escalation():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(SUBSTITUTION_MAX_SECONDS_FIXTURE - 1.0)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=TRUSTED_MIN
    )
    assert outcome.substituted is False
    assert outcome.escalated is False
    assert calls["n"] == 0


def test_default_substitution_max_seconds_matches_doc05():
    assert SUBSTITUTION_MAX_SECONDS_DEFAULT == 60.0
    clock = ManualClock()
    twin = _FixedReconstructionTwinFixture(0.0)
    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    calls = {"n": 0}
    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=lambda: calls.__setitem__("n", calls["n"] + 1),
        # substitution_max_seconds intentionally omitted -- exercises the
        # default, which must equal the Doc05-documented value.
        clock=clock,
    )
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(59.0)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.escalated is False
    clock.advance(1.0)  # now at 60.0
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.SUBSTITUTION_EXPIRED


def test_rejects_non_positive_substitution_max_seconds():
    clock = ManualClock()
    twin = _FixedReconstructionTwinFixture(0.0)
    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [0.0]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    with pytest.raises(ValueError):
        SelfHealOrchestrator(
            twin=twin,
            divergence_scorer=divergence_scorer,
            uncertainty_proxy=uncertainty_proxy,
            divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
            uncertainty_cap=UNCERTAINTY_CAP_D020,
            safe_stop=lambda: None,
            substitution_max_seconds=0.0,
            clock=clock,
        )


# ---------------------------------------------------------------------------
# Uncertainty-cap alert (D019, P3-HEAL-E1) -- independent of expiry/divergence
# ---------------------------------------------------------------------------


def test_uncertainty_cap_alert_without_escalation():
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    # Linear scaling fixture: fraction = elapsed / max. At elapsed=50/60,
    # uncertainty = 0.833 >= UNCERTAINTY_CAP_D020 (0.8), while still well
    # under the 60s expiry and with a small (non-escalating) divergence.
    clock.advance(50.0)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.escalated is False
    assert outcome.substituted is True
    assert outcome.alert is not None
    assert outcome.alert.message == "Uncertainty flagged high (nearing cap); alert raised"
    assert calls["n"] == 0


def test_uncertainty_below_cap_has_no_alert():
    clock = ManualClock()
    orchestrator, _ = _make_orchestrator(clock=clock)
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(10.0)  # fraction = 10/60 = 0.167, well under 0.8 cap
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.alert is None


def test_uncertainty_exactly_at_cap_raises_alert():
    """Boundary check: uncertainty == uncertainty_cap must raise the alert,
    proving the documented >= (inclusive) semantics at exact equality.

    uncertainty_cap is set to the SAME proxy/inputs' computed uncertainty
    (rather than an independently hand-derived number) so the comparison is
    exact, not merely close under floating-point rounding.
    """
    clock = ManualClock()
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    elapsed_probe = 30.0
    exact_uncertainty = uncertainty_proxy.uncertainty(
        elapsed_probe, SUBSTITUTION_MAX_SECONDS_FIXTURE
    )

    orchestrator, calls = _make_orchestrator(clock=clock, uncertainty_cap=exact_uncertainty)
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(elapsed_probe)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome.uncertainty == exact_uncertainty
    assert outcome.alert is not None
    assert outcome.escalated is False
    assert calls["n"] == 0


# ---------------------------------------------------------------------------
# Independence of the three signals (explicit instruction)
# ---------------------------------------------------------------------------


def test_uncertainty_cap_independent_of_divergence_value():
    """A large divergence_threshold (so divergence never escalates) must not
    suppress the independently-computed uncertainty-cap alert."""
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock, divergence_threshold=10_000.0)
    orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    clock.advance(50.0)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome.escalated is False  # divergence threshold never crossed
    assert outcome.divergence is not None and outcome.divergence > 0
    assert outcome.alert is not None  # uncertainty-cap check still fired


def test_divergence_escalation_independent_of_uncertainty_cap():
    """A very high uncertainty_cap (so the cap is never reached) must not
    suppress the independently-computed divergence escalation."""
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock, uncertainty_cap=10_000.0)
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.DIVERGENCE_EXCEEDED
    assert outcome.alert is None  # cap fixture set unreachably high
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# D019 reset semantics: new episode after recovery starts elapsed at zero
# ---------------------------------------------------------------------------


def test_new_episode_after_recovery_resets_elapsed():
    clock = ManualClock()
    orchestrator, _ = _make_orchestrator(clock=clock)
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(40.0)
    recovered = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=TRUSTED_MIN
    )
    assert recovered.substituted is False
    clock.advance(1.0)
    fresh = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert fresh.uncertainty == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Simultaneous conditions
# ---------------------------------------------------------------------------


def test_simultaneous_divergence_and_expiry_calls_safe_stop_once():
    """Both divergence-exceeded and expiry conditions true in the same call:
    safe_stop must fire exactly once (the code returns after the first
    branch, so it can never double-call safe_stop for one outcome)."""
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(SUBSTITUTION_MAX_SECONDS_FIXTURE)  # elapsed >= max: expiry condition true
    # raw_value=100.0 also forces divergence >= threshold: both conditions
    # are true on this single call.
    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.DIVERGENCE_EXCEEDED
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Repeated escalation
# ---------------------------------------------------------------------------


def test_repeated_escalation_after_reset():
    """After an escalation clears the episode, a fresh isolation of the same
    channel must be able to escalate again -- escalation must not leave any
    stuck/latched state that would suppress a second, independent
    escalation."""
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)
    outcome1 = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome1.escalated is True
    assert calls["n"] == 1

    clock.advance(5.0)
    outcome2 = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome2.escalated is True
    assert outcome2.escalation_reason == EscalationReason.DIVERGENCE_EXCEEDED
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Multi-channel isolation
# ---------------------------------------------------------------------------


def test_two_channels_processed_independently_in_same_orchestrator():
    """Two different channels isolated at different times in the same
    orchestrator must not share or corrupt each other's episode/divergence
    state."""
    clock = ManualClock()
    orchestrator, calls = _make_orchestrator(clock=clock)

    orchestrator.process_isolated_channel("temperature", _empty_window(), raw_value=0.0, trust=0.2)
    clock.advance(10.0)
    orchestrator.process_isolated_channel("current", _empty_window(), raw_value=0.0, trust=0.2)

    # 20s elapsed total: "temperature" has been isolated 20s, "current" only
    # 10s -- independent per-channel timers, not a shared clock/episode.
    clock.advance(10.0)
    outcome_temp = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=0.0, trust=0.2
    )
    outcome_current = orchestrator.process_isolated_channel(
        "current", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome_temp.uncertainty == pytest.approx(20.0 / SUBSTITUTION_MAX_SECONDS_FIXTURE)
    assert outcome_current.uncertainty == pytest.approx(10.0 / SUBSTITUTION_MAX_SECONDS_FIXTURE)

    # Escalate "temperature" via large divergence; "current" must remain
    # unaffected -- own episode intact, not escalated.
    outcome_temp2 = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome_temp2.escalated is True
    assert calls["n"] == 1

    outcome_current2 = orchestrator.process_isolated_channel(
        "current", _empty_window(), raw_value=0.0, trust=0.2
    )
    assert outcome_current2.escalated is False
    assert outcome_current2.substituted is True
    assert calls["n"] == 1  # unchanged -- "current"'s own call did not escalate


# ---------------------------------------------------------------------------
# Real Safe Pump-Stop integration (existing edge/actuation/relay.py, untouched)
# ---------------------------------------------------------------------------


def test_safe_stop_wired_to_real_relay_controller():
    clock = ManualClock()
    controller = RelayController(FakeActuator())
    controller.on()
    assert controller.state is RelayState.ON

    twin = _FixedReconstructionTwinFixture(0.0)
    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=controller.safe_off,
        substitution_max_seconds=SUBSTITUTION_MAX_SECONDS_FIXTURE,
        clock=clock,
    )

    outcome = orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=100.0, trust=0.2
    )
    assert outcome.escalated is True
    assert controller.state is RelayState.OFF
    assert controller.is_on() is False


# ---------------------------------------------------------------------------
# FR-M3: no channel/state beyond the divergence path retains the raw value
# ---------------------------------------------------------------------------


def test_episode_state_stores_no_raw_value():
    """Structural check: the only per-channel state the orchestrator retains
    across cycles is the episode start time -- raw_value is a local argument
    to process_isolated_channel, never persisted (FR-M3: isolated raw value
    is monitoring-only, never fed back beyond the divergence check)."""
    clock = ManualClock()
    orchestrator, _ = _make_orchestrator(clock=clock)
    # raw_value chosen small enough (relative to the fixture residual fit)
    # to stay below DIVERGENCE_THRESHOLD_FIXTURE, so the episode is not
    # cleared by an escalation before this check runs.
    distinctive_raw_value = 0.2
    orchestrator.process_isolated_channel(
        "temperature", _empty_window(), raw_value=distinctive_raw_value, trust=0.2
    )
    episode = orchestrator._episodes["temperature"]
    stored_values = vars(episode).values()
    assert distinctive_raw_value not in stored_values
