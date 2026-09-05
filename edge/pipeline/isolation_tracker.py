"""Stateful cross-cycle wrapper around the stateless ``decide_isolation()``
(FR-RL4 follow-up — persistent tracking, still decision-only).

``edge/pipeline/isolation_fallback.py`` is deliberately unchanged and stays
a pure function of one ``WindowOutcome``. This module adds exactly the one
thing that function cannot: memory across cycles — so a channel judged
Malicious once doesn't need to be re-flagged by the caller as "already
known bad."

Recovery is explicitly NOT implemented here, only avoided-by-omission: a
channel is never removed from ``tracked_channels`` just because its trust
recovered this cycle. Per ``edge/pipeline/self_heal.py``'s own recovery
semantics (and ``edge/tests/test_self_heal.py::
test_recovery_before_expiry_avoids_escalation``), real recovery is only
confirmed when the self-healing orchestration step itself is called again
and reports the channel no longer substituted/escalated — that step is not
wired into the live path (no real digital-twin reconstruction or
divergence threshold exists yet — see the investigation record). Claiming
recovery here without that feedback would be inventing information this
module does not have. ``tracked_channels`` is therefore a monotonically
non-shrinking set for the lifetime of one tracker instance: it only ever
grows, by design, until a real recovery-confirmation path exists to
un-track a channel correctly.

No new threshold, cooldown, hysteresis, cap, or fault/attack rule is
introduced — every classification still comes from the unmodified
``decide_isolation()``.

One instance = one independent tracking session (e.g. one per monitored
device's pipeline). Two instances never share state.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import CHANNELS

from edge.anomaly.pipeline import WindowOutcome
from edge.pipeline.isolation_fallback import decide_isolation


@dataclass(frozen=True)
class IsolationTrackerResult:
    """One ``update()`` call's result.

    ``candidates_this_cycle`` mirrors ``IsolationDecision.isolated_channels``
    for THIS window only — fresh, stateless, identical to calling
    ``decide_isolation()`` directly.

    ``tracked_channels`` is the tracker's own persistent state: every
    channel ever seen Malicious by this instance, still tracked. This is
    NOT a claim that any of them are currently isolated for real, nor that
    any earlier one has recovered — it is a log-only, persistent
    isolation-candidate set, pending real ``SelfHealOutcome`` feedback that
    does not exist yet.

    ``reasons`` covers exactly ``tracked_channels`` (in frozen ``CHANNELS``
    order, for deterministic logging), distinguishing three cases per
    channel: newly added this cycle, still Malicious this cycle, or no
    longer Malicious this cycle but still tracked pending confirmed
    recovery.
    """

    candidates_this_cycle: frozenset[str]
    tracked_channels: frozenset[str]
    reasons: dict[str, str]


class IsolationFallbackTracker:
    """Wraps ``decide_isolation()`` with a persistent, monotonically
    non-shrinking ``tracked_channels`` set. Construct one instance per
    monitored pipeline; call ``update()`` once per ``WindowOutcome``."""

    def __init__(self) -> None:
        self._tracked: set[str] = set()

    def update(self, outcome: WindowOutcome) -> IsolationTrackerResult:
        decision = decide_isolation(outcome)
        newly_added = decision.isolated_channels - self._tracked
        self._tracked |= decision.isolated_channels

        reasons: dict[str, str] = {}
        for ch in CHANNELS:
            if ch not in self._tracked:
                continue
            if ch in newly_added:
                reasons[ch] = f"newly isolated this cycle: {decision.reasons[ch]}"
            elif ch in decision.isolated_channels:
                reasons[ch] = f"still malicious this cycle: {decision.reasons[ch]}"
            else:
                reasons[ch] = (
                    "not malicious this cycle, but remains a persistent isolation "
                    "candidate -- no confirmed SelfHealOutcome recovery exists yet "
                    "(recovery tracking not implemented)"
                )

        return IsolationTrackerResult(
            candidates_this_cycle=decision.isolated_channels,
            tracked_channels=frozenset(self._tracked),
            reasons=reasons,
        )
