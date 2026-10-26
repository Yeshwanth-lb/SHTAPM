"""Dry-run Safe Pump-Stop demonstration (O7 / AC4) -- NO HARDWARE.

Drives the REAL, unmodified self-heal escalation path end to end:

    channel isolated -> twin substitution -> divergence z-score rises
    -> escalation -> RelayController.safe_off()

against a relay backed by ``FakeActuator`` (in-memory, records state history).
Nothing here touches GPIO.

What is real: ``SelfHealOrchestrator``, ``DivergenceScorer``,
``ElapsedTimeUncertaintyProxy`` + D020's ``linear_scaling``/``UNCERTAINTY_CAP_D020``,
``RelayController``, and D018's 60 s substitution expiry.

What is a fixture, and labelled as such:
  - ``DEMO_DIVERGENCE_THRESHOLD``: NOT a production value. U05 is still open --
    the live wiring keeps ``divergence_threshold=+inf`` because no responsible
    value exists on current reconstruction accuracy. This constant only exists
    to show the escalation path fires when a threshold is crossed.
  - ``_DemoTwinFixture``: a stand-in reconstructor returning a fixed value. It
    satisfies the real ``TwinReconstructor`` protocol and, as that protocol
    requires, never reads the isolated channel's own samples.
  - The clean-baseline residuals the divergence scorer is fitted on.

Run (repo root):
    Windows:  set PYTHONPATH=backend;. && python edge/scripts/dry_run_safe_stop.py
    Pi/Linux: PYTHONPATH=backend:. python edge/scripts/dry_run_safe_stop.py
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from app.schemas.contracts import CHANNELS

from edge.actuation.relay import FakeActuator, RelayController, RelayState
from edge.anomaly.preprocess import Window
from edge.pipeline.divergence import DivergenceScorer
from edge.pipeline.self_heal import (
    SUBSTITUTION_MAX_SECONDS_DEFAULT,
    UNCERTAINTY_CAP_D020,
    SelfHealOrchestrator,
    SelfHealOutcome,
)
from edge.pipeline.uncertainty import ElapsedTimeUncertaintyProxy, linear_scaling

# TEST FIXTURE -- NOT a production value. U05 (divergence_threshold) remains
# OPEN; the deployed system uses +inf (escalation disabled). Chosen only so the
# demo's deliberately-diverging sequence crosses it.
DEMO_DIVERGENCE_THRESHOLD: float = 6.0

DEMO_CHANNEL = "current"
DEMO_ISOLATED_TRUST = 0.30  # below TRUSTED_MIN (0.7): channel stays isolated
DEMO_RECOVERED_TRUST = 0.75  # at/above TRUSTED_MIN: channel re-admitted
DEMO_RECONSTRUCTION = 0.50  # fixture twin output, normalised units

# Fixture clean-baseline residuals (reconstruction - observed), small spread
# around zero, standing in for what a trained twin produces on clean data.
_CLEAN_RESIDUALS = (-0.02, -0.01, 0.0, 0.01, 0.02, -0.015, 0.015, 0.005, -0.005)

Log = Callable[[str], None]


class ManualClock:
    """Deterministic clock so the 60 s expiry path runs instantly."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _DemoTwinFixture:
    """FIXTURE reconstructor (not the trained LSTM). Returns a fixed value and
    never reads ``window.features[missing_channel]``."""

    def reconstruct(self, window: Window, missing_channel: str) -> float:
        return DEMO_RECONSTRUCTION


@dataclass
class DemoResult:
    outcomes: list[SelfHealOutcome] = field(default_factory=list)
    safe_off_calls: int = 0
    relay_history: list[RelayState] = field(default_factory=list)
    final_relay_state: RelayState | None = None


def _window_observing(value: float) -> Window:
    return Window(start_index=0, end_index=1, features={ch: (value,) for ch in CHANNELS})


def _build(
    clock: ManualClock, log: Log
) -> tuple[SelfHealOrchestrator, RelayController, FakeActuator, list]:
    actuator = FakeActuator()
    relay = RelayController(actuator)
    relay.on()
    log(f"  pump relay ON (FakeActuator, no GPIO) -> state={relay.state.value}")

    calls: list[int] = []

    def safe_stop() -> None:
        calls.append(1)
        relay.safe_off()
        log(
            "  >>> relay.safe_off() INVOKED [DRY RUN -- FakeActuator, no hardware] "
            f"-> state={relay.state.value}"
        )

    scorer = DivergenceScorer()
    scorer.fit({DEMO_CHANNEL: list(_CLEAN_RESIDUALS)})

    orchestrator = SelfHealOrchestrator(
        twin=_DemoTwinFixture(),
        divergence_scorer=scorer,
        uncertainty_proxy=ElapsedTimeUncertaintyProxy(linear_scaling),
        divergence_threshold=DEMO_DIVERGENCE_THRESHOLD,
        uncertainty_cap=UNCERTAINTY_CAP_D020,
        safe_stop=safe_stop,
        clock=clock,
    )
    return orchestrator, relay, actuator, calls


def _report(outcome: SelfHealOutcome, t: float, log: Log) -> None:
    if outcome.escalated:
        state = f"ESCALATE ({outcome.escalation_reason})"
    elif outcome.substituted:
        state = "substituting (VIRTUAL value published)"
    else:
        state = "recovered -> real sensor re-admitted"
    div = "-" if outcome.divergence is None else f"{outcome.divergence:6.2f}"
    unc = "-" if outcome.uncertainty is None else f"{outcome.uncertainty:.2f}"
    log(
        f"  t={t:5.1f}s  divergence={div} vs test threshold {DEMO_DIVERGENCE_THRESHOLD:.1f}"
        f"  uncertainty={unc}  -> {state}"
    )


def _finish(
    result: DemoResult, relay: RelayController, actuator: FakeActuator, calls: list
) -> DemoResult:
    result.safe_off_calls = len(calls)
    result.relay_history = list(actuator.history)
    result.final_relay_state = relay.state
    return result


def run_divergence_scenario(log: Log = print) -> DemoResult:
    """Twin and sensor drift apart until divergence crosses the test threshold."""
    log("\n[1] DIVERGENCE PATH -- isolated sensor keeps disagreeing with the twin")
    clock = ManualClock()
    orchestrator, relay, actuator, calls = _build(clock, log)
    log(f"  '{DEMO_CHANNEL}' ISOLATED (trust={DEMO_ISOLATED_TRUST} < 0.7)")
    result = DemoResult()
    for observed in (0.50, 0.51, 0.53, 0.56, 0.60, 0.70):
        outcome = orchestrator.process_isolated_channel(
            DEMO_CHANNEL, _window_observing(observed), raw_value=observed, trust=DEMO_ISOLATED_TRUST
        )
        result.outcomes.append(outcome)
        _report(outcome, clock(), log)
        if outcome.escalated:
            break
        clock.advance(1.0)
    return _finish(result, relay, actuator, calls)


def run_expiry_scenario(log: Log = print) -> DemoResult:
    """Divergence stays low, but the channel never recovers within 60 s (D018)."""
    log(
        f"\n[2] EXPIRY PATH -- no recovery within {SUBSTITUTION_MAX_SECONDS_DEFAULT:.0f} s "
        "substitution limit"
    )
    clock = ManualClock()
    orchestrator, relay, actuator, calls = _build(clock, log)
    log(f"  '{DEMO_CHANNEL}' ISOLATED (trust={DEMO_ISOLATED_TRUST} < 0.7)")
    result = DemoResult()
    while True:
        outcome = orchestrator.process_isolated_channel(
            DEMO_CHANNEL,
            _window_observing(DEMO_RECONSTRUCTION),
            raw_value=DEMO_RECONSTRUCTION,
            trust=DEMO_ISOLATED_TRUST,
        )
        result.outcomes.append(outcome)
        _report(outcome, clock(), log)
        if outcome.escalated or clock() > 2 * SUBSTITUTION_MAX_SECONDS_DEFAULT:
            break
        clock.advance(10.0)
    return _finish(result, relay, actuator, calls)


def run_recovery_scenario(log: Log = print) -> DemoResult:
    """Trust recovers before any threshold is crossed: no safe-stop."""
    log("\n[3] RECOVERY PATH -- sensor becomes trustworthy again, no stop")
    clock = ManualClock()
    orchestrator, relay, actuator, calls = _build(clock, log)
    log(f"  '{DEMO_CHANNEL}' ISOLATED (trust={DEMO_ISOLATED_TRUST} < 0.7)")
    result = DemoResult()
    for observed, trust in ((0.50, 0.30), (0.51, 0.45), (0.51, 0.62), (0.50, 0.75)):
        outcome = orchestrator.process_isolated_channel(
            DEMO_CHANNEL, _window_observing(observed), raw_value=observed, trust=trust
        )
        result.outcomes.append(outcome)
        log(f"  trust={trust:.2f}")
        _report(outcome, clock(), log)
        clock.advance(10.0)
    return _finish(result, relay, actuator, calls)


def main() -> int:
    print("=" * 72)
    print("SHTAPM dry-run Safe Pump-Stop demo (O7) -- NO HARDWARE, FakeActuator relay")
    print(
        f"Divergence threshold {DEMO_DIVERGENCE_THRESHOLD} is a TEST FIXTURE. Production "
        "keeps escalation disabled (+inf) until U05 is resolved."
    )
    print("=" * 72)
    results = (run_divergence_scenario(), run_expiry_scenario(), run_recovery_scenario())
    print("\n" + "=" * 72)
    for name, r in zip(("divergence", "expiry", "recovery"), results, strict=True):
        print(
            f"{name:>10}: safe_off calls={r.safe_off_calls}  final relay="
            f"{r.final_relay_state.value if r.final_relay_state else '-'}"
        )
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
