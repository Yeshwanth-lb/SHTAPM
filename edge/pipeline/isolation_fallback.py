"""Stateless deterministic isolation decision (FR-RL4, decision-only slice).

Classifies each channel's CURRENT ``TrustBand`` (``edge/trust/beta.py``,
FR-T3 — already-frozen boundaries ``TRUSTED_MIN=0.7``/``MALICIOUS_MAX=0.4``)
for exactly one ``WindowOutcome``. No new threshold is introduced: a
``TrustReading.band`` is already computed from those frozen boundaries by
``TrustEngine``/``BetaState.classify()`` — this module only reads it, never
recomputes or re-derives a cutoff.

Explicitly NOT implemented here (deliberately out of scope for this slice,
not forgotten):
  - Cross-cycle state, hysteresis, or recovery tracking. ``LiveP2Monitor``
    currently supplies only a ``WindowOutcome`` per tick, never the outcome
    of the self-healing orchestration step — there is no real
    recovery-confirmation feedback to track against yet (see
    ``edge/pipeline/self_heal.py``'s recovery semantics and
    ``edge/tests/test_self_heal.py::test_recovery_before_expiry_avoids_
    escalation`` for why that feedback specifically matters: a channel's
    episode only clears once the orchestration step itself is called again
    with recovered trust). Pretending that feedback loop exists without
    actually wiring it would be worse than not having it. This module is a
    pure function of one ``WindowOutcome`` and nothing else — call it
    fresh every cycle.
  - Any cooldown, isolation cap, or fault-vs-attack-specific rule — none
    is specified anywhere in the project docs, so none is invented.
  - Calling the P2→P3 adapter or self-healing orchestration step
    (``edge/pipeline/cycle.py``, ``edge/pipeline/self_heal.py``),
    actuation, GPIO, ledger, or MQTT/decision publishing — this module
    only classifies and returns a decision for the caller to log.
  - ``SUSPICIOUS`` channels: FR-RL2 lists "Reduce Weight" as a distinct,
    lesser action from "Isolate Sensor" — conflating them here would
    invent a mapping no doc specifies, so Suspicious is left alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import CHANNELS

from edge.anomaly.pipeline import WindowOutcome
from edge.trust.beta import MALICIOUS_MAX, TrustBand


@dataclass(frozen=True)
class IsolationDecision:
    """Isolation CANDIDATES for exactly one ``WindowOutcome`` — no memory
    of any prior cycle. ``reasons`` (one entry per frozen channel) is
    human-readable, for logging only; it is not consumed by, and carries
    no obligation for, any downstream code."""

    isolated_channels: frozenset[str]
    reasons: dict[str, str]


def decide_isolation(outcome: WindowOutcome) -> IsolationDecision:
    """Classify each frozen channel's CURRENT ``TrustBand``:

        MALICIOUS  -> isolation candidate
        SUSPICIOUS -> not isolated
        TRUSTED    -> not isolated

    Stateless: reads only ``outcome.trust``, returns a fresh decision every
    call. Supports zero, one, or all six channels being malicious at once —
    each channel is judged independently.
    """
    isolated: set[str] = set()
    reasons: dict[str, str] = {}
    for ch in CHANNELS:
        reading = outcome.trust[ch]
        if reading.band is TrustBand.MALICIOUS:
            isolated.add(ch)
            reasons[ch] = (
                f"trust={reading.trust:.3f} < MALICIOUS_MAX={MALICIOUS_MAX} "
                "(band=malicious) -> isolation candidate"
            )
        elif reading.band is TrustBand.SUSPICIOUS:
            reasons[ch] = f"trust={reading.trust:.3f} (band=suspicious) -> not isolated"
        else:
            reasons[ch] = f"trust={reading.trust:.3f} (band=trusted) -> not isolated"
    return IsolationDecision(isolated_channels=frozenset(isolated), reasons=reasons)
