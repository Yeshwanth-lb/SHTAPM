"""Stateful cross-cycle wrapper around the stateless ``decide_isolation()``
(FR-RL4 follow-up — persistent tracking with D018 recovery).

``edge/pipeline/isolation_fallback.py`` is deliberately unchanged and stays
a pure function of one ``WindowOutcome``. This module adds the one thing that
function cannot: memory across cycles, so a channel judged Malicious stays
isolated while its trust is merely Suspicious instead of flickering out the
moment it climbs above ``MALICIOUS_MAX``.

RECOVERY (D018 pt.2, the rule ``SelfHealOrchestrator`` already applies): a
tracked channel is released when its trust is back at or above
``TRUSTED_MIN``. Entering needs trust < ``MALICIOUS_MAX`` (0.4); leaving needs
trust >= ``TRUSTED_MIN`` (0.7). The Suspicious band between the two is the
hysteresis that keeps the decision non-oscillating (PRD P3-RL-E1): a channel
hovering near either boundary cannot toggle in and out every window.

Before this, the set was monotonically non-shrinking. Combined with the live
monitor's 5-window fit (corrected by D031), one false alarm left a channel
VIRTUAL for the rest of the session and re-requested Safe Pump-Stop every
60 s as each substitution episode expired. Releasing on the orchestrator's own
recovery threshold keeps the two components agreeing about when a channel is
healthy again: the orchestrator stops substituting at exactly the point the
tracker stops reporting the channel as isolated.

No new threshold, cooldown, or fault/attack rule is introduced — both
boundaries are the frozen FR-T3 constants from ``edge/trust/beta.py``.

One instance = one independent tracking session (e.g. one per monitored
device's pipeline). Two instances never share state.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import CHANNELS

from edge.anomaly.pipeline import WindowOutcome
from edge.pipeline.isolation_fallback import decide_isolation
from edge.trust.beta import TRUSTED_MIN


@dataclass(frozen=True)
class IsolationTrackerResult:
    """One ``update()`` call's result.

    ``candidates_this_cycle`` mirrors ``IsolationDecision.isolated_channels``
    for THIS window only — fresh, stateless, identical to calling
    ``decide_isolation()`` directly.

    ``tracked_channels`` is the tracker's persistent state after this cycle:
    every channel that entered isolation and has not yet recovered.

    ``released_this_cycle`` names channels that left isolation in THIS cycle
    because their trust reached ``TRUSTED_MIN``. They are no longer in
    ``tracked_channels``.

    ``reasons`` covers ``tracked_channels`` plus ``released_this_cycle`` (in
    frozen ``CHANNELS`` order, for deterministic logging), distinguishing four
    cases per channel: newly isolated, still Malicious, no longer Malicious
    but not yet recovered, and recovered.
    """

    candidates_this_cycle: frozenset[str]
    tracked_channels: frozenset[str]
    reasons: dict[str, str]
    released_this_cycle: frozenset[str] = frozenset()


class IsolationFallbackTracker:
    """Wraps ``decide_isolation()`` with persistent isolation state that is
    released on recovery to ``TRUSTED_MIN``. Construct one instance per
    monitored pipeline; call ``update()`` once per ``WindowOutcome``."""

    def __init__(self) -> None:
        self._tracked: set[str] = set()

    def update(self, outcome: WindowOutcome) -> IsolationTrackerResult:
        decision = decide_isolation(outcome)
        newly_added = decision.isolated_channels - self._tracked
        self._tracked |= decision.isolated_channels

        released = {
            ch
            for ch in self._tracked
            if ch not in decision.isolated_channels and outcome.trust[ch].trust >= TRUSTED_MIN
        }
        self._tracked -= released

        reasons: dict[str, str] = {}
        for ch in CHANNELS:
            if ch in released:
                reasons[ch] = (
                    f"recovered this cycle: trust={outcome.trust[ch].trust:.3f} >= "
                    f"TRUSTED_MIN={TRUSTED_MIN} -- released from isolation (D018 pt.2)"
                )
            elif ch not in self._tracked:
                continue
            elif ch in newly_added:
                reasons[ch] = f"newly isolated this cycle: {decision.reasons[ch]}"
            elif ch in decision.isolated_channels:
                reasons[ch] = f"still malicious this cycle: {decision.reasons[ch]}"
            else:
                reasons[ch] = (
                    f"not malicious this cycle, still isolated: trust="
                    f"{outcome.trust[ch].trust:.3f} has not reached TRUSTED_MIN={TRUSTED_MIN}"
                )

        return IsolationTrackerResult(
            candidates_this_cycle=decision.isolated_channels,
            tracked_channels=frozenset(self._tracked),
            reasons=reasons,
            released_this_cycle=frozenset(released),
        )
