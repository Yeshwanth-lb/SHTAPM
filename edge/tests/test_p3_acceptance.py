"""P3 formal acceptance tests (PRD acceptance-criteria table, P3-HEAL/
PRED/RL/SAFE).

Mirrors edge/tests/test_p2_acceptance.py's honesty convention: names every
P3-* criterion, marks each ATTEMPTED (mechanism-level, against literal
Doc06/PRD wording) or NOT ATTEMPTED (with the exact blocking reason).
Nothing here manufactures a pass for functionality that does not exist.

ATTEMPTED (mechanism-level only -- see each test's own docstring for
exactly what is, and is not, proven):
    P3-HEAL-E1, P3-HEAL-S1, P3-HEAL-S2

NOT ATTEMPTED:
    P3-HEAL-H1 -- "Isolate spoofed sensor" requires a real isolation
        trigger, which requires the RL agent or its deterministic fallback
        (FR-RL2/FR-RL4) -- neither exists in this repo. "prediction
        continuous" requires prognosis (FR-M1/M2) -- does not exist.
        Attempting even the "substitution active" half alone would require
        inventing an isolation rule, which this project has repeatedly and
        deliberately declined to do without a real decision source.
    P3-PRED-H1/E1/S1 -- prognosis (FR-M1/M2) does not exist; blocked on an
        unspecified degradation-trajectory data source (DECISIONS.md D017).
    P3-RL-H1/H2/E1/S1/S2 -- no RL agent or deterministic fallback exists
        anywhere in this repo (FR-RL1-4); U06 (reward shaping) is fully
        open/undecided.
    P3-SAFE-H1/S1 -- dry-run detection is not implemented; the underlying
        acceptance claim ("relay stops pump", "current-based cross-check
        triggers stop") also requires physical hardware validation
        regardless of software state.

`DIVERGENCE_THRESHOLD_FIXTURE`/`SUBSTITUTION_MAX_SECONDS_FIXTURE`/
`HIDDEN_SIZE_FIXTURE` below are TEST FIXTURES ONLY, explicitly labelled
`*_FIXTURE` -- `divergence_threshold` remains the project's one genuinely
unresolved U05 value (data-gated); these tests prove the MECHANISM behaves
as Doc06/PRD describe when GIVEN some threshold, not a real-world
validation of what that threshold should be. `uncertainty_cap`/the
elapsed-time scaling formula are deliberately NOT fixtures here: they are
the real, D020-approved values (`UNCERTAINTY_CAP_D020` / `linear_scaling`),
imported directly -- these tests exercise the actual approved policy, not
a stand-in for it. None of this is a claim of digital-twin reconstruction
accuracy.

Skipped entirely when torch is unavailable -- same skip-pattern as
edge/tests/test_lstm_twin.py.
"""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

from app.schemas.contracts import CHANNELS  # noqa: E402

from edge.actuation.relay import FakeActuator, RelayController, RelayState  # noqa: E402
from edge.anomaly.preprocess import Window  # noqa: E402
from edge.models.lstm_twin import LSTMTwinReconstructor, _LSTMTwinNet  # noqa: E402
from edge.pipeline.divergence import DivergenceScorer  # noqa: E402
from edge.pipeline.self_heal import (  # noqa: E402
    UNCERTAINTY_CAP_D020,
    EscalationReason,
    SelfHealOrchestrator,
)
from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy, linear_scaling  # noqa: E402

# ---- TEST FIXTURES ONLY -- not project specification values ---------------
DIVERGENCE_THRESHOLD_FIXTURE = 3.0
SUBSTITUTION_MAX_SECONDS_FIXTURE = 60.0
HIDDEN_SIZE_FIXTURE = 4
# uncertainty_cap/the scaling formula are NOT fixtures -- see module
# docstring; UNCERTAINTY_CAP_D020/linear_scaling are imported above.


class ManualClock:
    """Deterministic clock, same pattern as edge/tests/test_self_heal.py."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _window() -> Window:
    return Window(start_index=0, end_index=30, features={ch: (0.0,) * 30 for ch in CHANNELS})


def _make_orchestrator(clock: ManualClock, safe_stop=None):
    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    twin = LSTMTwinReconstructor(network)
    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    calls = {"n": 0}

    if safe_stop is None:

        def safe_stop():
            calls["n"] += 1

    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=safe_stop,
        substitution_max_seconds=SUBSTITUTION_MAX_SECONDS_FIXTURE,
        clock=clock,
    )
    return orchestrator, calls


# ===========================================================================
# P3-HEAL-E1 -- Edge: Substitution near uncertainty cap -> alert raised
# ===========================================================================


def test_p3_heal_e1_substitution_near_uncertainty_cap_raises_alert():
    """Doc06/PRD wording (D019-clarified): "Uncertainty flagged high
    (nearing cap); alert raised". Uses the REAL, D020-approved
    `UNCERTAINTY_CAP_D020` (0.8) -- this is a MECHANISM test, not a
    real-world validation claim, but the cap value itself is no longer a
    placeholder (D020 resolved it as a policy decision)."""
    clock = ManualClock()
    window = _window()

    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    twin = LSTMTwinReconstructor(network)
    # Track the (untrained, arbitrarily-initialized) twin's own
    # reconstruction so raw_value keeps divergence near 0 throughout --
    # isolates the uncertainty-cap mechanism from the independent
    # divergence mechanism (the three signals are independent by design;
    # see edge/pipeline/self_heal.py).
    tracked_value = twin.reconstruct(window, "temperature")

    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    calls = {"n": 0}

    def safe_stop():
        calls["n"] += 1

    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=safe_stop,
        substitution_max_seconds=SUBSTITUTION_MAX_SECONDS_FIXTURE,
        clock=clock,
    )

    orchestrator.process_isolated_channel("temperature", window, raw_value=tracked_value, trust=0.2)
    clock.advance(50.0)  # fraction = 50/60 = 0.833 >= UNCERTAINTY_CAP_D020 (0.8)
    outcome = orchestrator.process_isolated_channel(
        "temperature", window, raw_value=tracked_value, trust=0.2
    )

    assert outcome.alert is not None
    assert outcome.alert.message == "Uncertainty flagged high (nearing cap); alert raised"
    assert outcome.escalated is False
    assert calls["n"] == 0


# ===========================================================================
# P3-HEAL-S1 -- Sad: Real state diverges from twin beyond threshold ->
#                     Escalates to Safe Pump-Stop
# ===========================================================================


def test_p3_heal_s1_divergence_beyond_threshold_escalates_to_safe_pump_stop():
    """Doc06/PRD wording: "Escalates to Safe Pump-Stop (no limping on
    fantasy)". MECHANISM test with a fixture threshold and the REAL
    RelayController (not a bare mock) -- the real divergence_threshold
    value remains unresolved and data-gated (U05); this proves exceeding
    SOME threshold correctly reaches a real Safe Pump-Stop action, not
    what that threshold's real value should be."""
    clock = ManualClock()
    controller = RelayController(FakeActuator())
    controller.on()
    orchestrator, _calls = _make_orchestrator(clock, safe_stop=controller.safe_off)
    window = _window()

    outcome = orchestrator.process_isolated_channel(
        "temperature", window, raw_value=100.0, trust=0.2
    )

    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.DIVERGENCE_EXCEEDED
    assert controller.state is RelayState.OFF


# ===========================================================================
# P3-HEAL-S2 -- Sad: Attacker controls isolated channel's substitute
#                     expectation -> bounded window + divergence check
#                     prevent indefinite trust
# ===========================================================================


def test_p3_heal_s2_bounded_window_prevents_indefinite_trust_despite_low_divergence():
    """Doc06/PRD wording: "Bounded window + divergence check prevents
    indefinite trust." MECHANISM test only -- simulates an attacker who
    successfully keeps divergence low (raw_value tracks the twin's
    reconstruction) for the entire substitution episode, proving the 60s
    bound ALONE -- independent of divergence ever firing -- still forces
    escalation. Uses a fixture `divergence_threshold` (still U05,
    data-gated) and the real, D020-approved `uncertainty_cap`/scaling
    formula; not a real attack-injection scenario."""
    clock = ManualClock()
    window = _window()

    network = _LSTMTwinNet(hidden_size=HIDDEN_SIZE_FIXTURE)
    twin = LSTMTwinReconstructor(network)
    # Query the (untrained, arbitrarily-initialized) twin's own
    # reconstruction directly, then use that EXACT value as raw_value for
    # every cycle below -- guarantees residual == 0 (divergence == 0)
    # regardless of this random initialization's actual output, modeling
    # an attacker who perfectly tracks the twin's expectation every cycle.
    tracked_value = twin.reconstruct(window, "temperature")

    divergence_scorer = DivergenceScorer()
    divergence_scorer.fit({"temperature": [-0.1, 0.0, 0.1]})
    uncertainty_proxy = ElapsedTimeUncertaintyProxy(scaling_fn=linear_scaling)
    calls = {"n": 0}

    def safe_stop():
        calls["n"] += 1

    orchestrator = SelfHealOrchestrator(
        twin=twin,
        divergence_scorer=divergence_scorer,
        uncertainty_proxy=uncertainty_proxy,
        divergence_threshold=DIVERGENCE_THRESHOLD_FIXTURE,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=safe_stop,
        substitution_max_seconds=SUBSTITUTION_MAX_SECONDS_FIXTURE,
        clock=clock,
    )

    for elapsed in (0.0, 10.0, 20.0, 30.0, 40.0, 50.0):
        clock.t = elapsed
        outcome = orchestrator.process_isolated_channel(
            "temperature", window, raw_value=tracked_value, trust=0.2
        )
        assert outcome.escalated is False, (
            f"divergence stayed ~0 by construction at elapsed={elapsed}s -- "
            "must not escalate from divergence alone"
        )

    clock.t = 60.0
    outcome = orchestrator.process_isolated_channel(
        "temperature", window, raw_value=tracked_value, trust=0.2
    )

    assert outcome.escalated is True
    assert outcome.escalation_reason == EscalationReason.SUBSTITUTION_EXPIRED
    assert calls["n"] == 1
